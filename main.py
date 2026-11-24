import csv
import hashlib
import hmac
import io
import os
import secrets
from contextlib import asynccontextmanager
from datetime import date, timedelta

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from database import Base, SessionLocal, engine, get_db
from models import DENDA_PER_HARI, Anggota, Buku, Peminjaman, User

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

@asynccontextmanager
async def lifespan(_app: FastAPI):
    startup()
    yield


app = FastAPI(title="Sistem Informasi Perpustakaan", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SECRET_KEY", "dev-secret-ubah-di-produksi"),
    max_age=60 * 60 * 8,
)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
templates.env.filters["rupiah"] = lambda v: "Rp {:,.0f}".format(v or 0).replace(",", ".")
templates.env.filters["tgl"] = lambda d: d.strftime("%d-%m-%Y") if d else "-"


# ======================= UTIL: AUTH & TEMPLATE =======================
def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000)
    return f"{salt}${h.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, h = stored.split("$")
    except ValueError:
        return False
    calc = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000)
    return hmac.compare_digest(calc.hex(), h)


def require_login(request: Request, db: Session = Depends(get_db)) -> User:
    uid = request.session.get("uid")
    user = db.get(User, uid) if uid else None
    if not user:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return user


def render(request: Request, name: str, user: User | None = None, **ctx):
    ctx["user"] = user
    ctx["flash"] = request.session.pop("flash", None)
    ctx["denda_per_hari"] = DENDA_PER_HARI
    return templates.TemplateResponse(request, name, ctx)


def flash(request: Request, msg: str, kind: str = "ok"):
    request.session["flash"] = {"msg": msg, "kind": kind}


def go(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


# ======================= STARTUP: TABEL & DATA AWAL =======================
def startup():
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if not db.scalar(select(func.count(User.id))):
            db.add(User(nama="Administrator", username="admin",
                        password_hash=hash_password("admin123"), role="admin"))
            db.commit()
        if os.getenv("SEED_DEMO", "1") == "1" and not db.scalar(select(func.count(Buku.id))):
            seed_demo(db)


def seed_demo(db: Session):
    buku = [
        Buku(kode="B001", judul="Pemrograman Python untuk Pemula", penulis="Budi Santoso", penerbit="Informatika", tahun=2021, kategori="Komputer", stok=5),
        Buku(kode="B002", judul="Basis Data Relasional", penulis="Sari Wulandari", penerbit="Andi", tahun=2019, kategori="Komputer", stok=3),
        Buku(kode="B003", judul="Laskar Pelangi", penulis="Andrea Hirata", penerbit="Bentang", tahun=2005, kategori="Novel", stok=4),
        Buku(kode="B004", judul="Sejarah Indonesia Modern", penulis="M.C. Ricklefs", penerbit="Serambi", tahun=2008, kategori="Sejarah", stok=2),
        Buku(kode="B005", judul="Pengantar Akuntansi", penulis="Dewi Lestari", penerbit="Salemba", tahun=2020, kategori="Ekonomi", stok=3),
    ]
    anggota = [
        Anggota(kode="A001", nama="Andi Pratama", email="andi@example.com", telepon="081234567890", alamat="Jakarta Barat"),
        Anggota(kode="A002", nama="Siti Rahma", email="siti@example.com", telepon="082233445566", alamat="Tangerang"),
        Anggota(kode="A003", nama="Rudi Hartono", email="rudi@example.com", telepon="085711223344", alamat="Jakarta Utara"),
    ]
    db.add_all(buku + anggota)
    db.flush()
    today = date.today()
    contoh = [
        # (anggota, buku, hari lalu dipinjam, lama, sudah kembali hari ke-?)
        (anggota[0], buku[0], 20, 7, 18),   # dikembalikan, terlambat
        (anggota[1], buku[2], 10, 7, 9),    # dikembalikan, tepat waktu
        (anggota[2], buku[1], 12, 7, None),  # terlambat, belum kembali
        (anggota[0], buku[3], 2, 7, None),  # sedang dipinjam
    ]
    for a, b, lalu, lama, kembali_hari in contoh:
        pinjam = today - timedelta(days=lalu)
        tempo = pinjam + timedelta(days=lama)
        p = Peminjaman(anggota_id=a.id, buku_id=b.id, tgl_pinjam=pinjam, tgl_jatuh_tempo=tempo)
        if kembali_hari is not None:
            p.tgl_kembali = pinjam + timedelta(days=kembali_hari)
            p.denda = max(0, (p.tgl_kembali - tempo).days) * DENDA_PER_HARI
        else:
            b.stok -= 1
        db.add(p)
    db.commit()


# ======================= AUTH =======================
@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return render(request, "login.html")


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...),
          db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == username.strip().lower()))
    if not user or not verify_password(password, user.password_hash):
        flash(request, "Username atau password salah.", "err")
        return go("/login")
    request.session["uid"] = user.id
    return go("/")


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return render(request, "register.html")


@app.post("/register")
def register(request: Request, nama: str = Form(...), username: str = Form(...),
             password: str = Form(...), password2: str = Form(...),
             db: Session = Depends(get_db)):
    username = username.strip().lower()
    if len(password) < 6:
        flash(request, "Password minimal 6 karakter.", "err")
        return go("/register")
    if password != password2:
        flash(request, "Konfirmasi password tidak sama.", "err")
        return go("/register")
    if db.scalar(select(User).where(User.username == username)):
        flash(request, "Username sudah dipakai.", "err")
        return go("/register")
    db.add(User(nama=nama.strip(), username=username, password_hash=hash_password(password)))
    db.commit()
    flash(request, "Registrasi berhasil, silakan login.")
    return go("/login")


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return go("/login")


# ======================= DASHBOARD =======================
@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db), user: User = Depends(require_login)):
    today = date.today()
    aktif = db.scalar(select(func.count(Peminjaman.id)).where(Peminjaman.tgl_kembali.is_(None)))
    terlambat = db.scalars(
        select(Peminjaman).where(Peminjaman.tgl_kembali.is_(None), Peminjaman.tgl_jatuh_tempo < today)
        .order_by(Peminjaman.tgl_jatuh_tempo)
    ).all()
    stats = {
        "buku": db.scalar(select(func.count(Buku.id))),
        "stok": db.scalar(select(func.coalesce(func.sum(Buku.stok), 0))),
        "anggota": db.scalar(select(func.count(Anggota.id))),
        "aktif": aktif,
        "terlambat": len(terlambat),
        "denda_terkumpul": db.scalar(select(func.coalesce(func.sum(Peminjaman.denda), 0))),
        "denda_berjalan": sum(p.denda_efektif for p in terlambat),
    }
    terbaru = db.scalars(select(Peminjaman).order_by(Peminjaman.id.desc()).limit(5)).all()
    populer = db.execute(
        select(Buku.judul, func.count(Peminjaman.id).label("n"))
        .join(Peminjaman, Peminjaman.buku_id == Buku.id)
        .group_by(Buku.id).order_by(func.count(Peminjaman.id).desc()).limit(5)
    ).all()
    return render(request, "dashboard.html", user, stats=stats, terbaru=terbaru,
                  terlambat=terlambat[:5], populer=populer)


# ======================= MASTER: BUKU =======================
@app.get("/buku", response_class=HTMLResponse)
def buku_list(request: Request, q: str = "", db: Session = Depends(get_db),
              user: User = Depends(require_login)):
    stmt = select(Buku).order_by(Buku.kode)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Buku.judul.ilike(like), Buku.penulis.ilike(like),
                              Buku.kode.ilike(like), Buku.kategori.ilike(like)))
    return render(request, "buku_list.html", user, rows=db.scalars(stmt).all(), q=q)


@app.get("/buku/tambah", response_class=HTMLResponse)
def buku_new(request: Request, user: User = Depends(require_login)):
    return render(request, "buku_form.html", user, item=None)


@app.post("/buku/tambah")
def buku_create(request: Request, kode: str = Form(...), judul: str = Form(...),
                penulis: str = Form(""), penerbit: str = Form(""), tahun: str = Form(""),
                kategori: str = Form("Umum"), stok: int = Form(1),
                db: Session = Depends(get_db), user: User = Depends(require_login)):
    if stok < 0:
        flash(request, "Stok tidak boleh negatif.", "err")
        return go("/buku/tambah")
    db.add(Buku(kode=kode.strip().upper(), judul=judul.strip(), penulis=penulis.strip(),
                penerbit=penerbit.strip(), tahun=int(tahun) if tahun.strip().isdigit() else None,
                kategori=kategori.strip() or "Umum", stok=stok))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        flash(request, "Kode buku sudah ada.", "err")
        return go("/buku/tambah")
    flash(request, "Buku ditambahkan.")
    return go("/buku")


@app.get("/buku/{id}/edit", response_class=HTMLResponse)
def buku_edit(id: int, request: Request, db: Session = Depends(get_db),
              user: User = Depends(require_login)):
    item = db.get(Buku, id)
    if not item:
        raise HTTPException(404, "Buku tidak ditemukan")
    return render(request, "buku_form.html", user, item=item)


@app.post("/buku/{id}/edit")
def buku_update(id: int, request: Request, kode: str = Form(...), judul: str = Form(...),
                penulis: str = Form(""), penerbit: str = Form(""), tahun: str = Form(""),
                kategori: str = Form("Umum"), stok: int = Form(1),
                db: Session = Depends(get_db), user: User = Depends(require_login)):
    item = db.get(Buku, id)
    if not item:
        raise HTTPException(404, "Buku tidak ditemukan")
    if stok < 0:
        flash(request, "Stok tidak boleh negatif.", "err")
        return go(f"/buku/{id}/edit")
    item.kode, item.judul = kode.strip().upper(), judul.strip()
    item.penulis, item.penerbit = penulis.strip(), penerbit.strip()
    item.tahun = int(tahun) if tahun.strip().isdigit() else None
    item.kategori, item.stok = kategori.strip() or "Umum", stok
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        flash(request, "Kode buku sudah dipakai buku lain.", "err")
        return go(f"/buku/{id}/edit")
    flash(request, "Buku diperbarui.")
    return go("/buku")


@app.post("/buku/{id}/hapus")
def buku_delete(id: int, request: Request, db: Session = Depends(get_db),
                user: User = Depends(require_login)):
    item = db.get(Buku, id)
    if item:
        if item.peminjaman:
            flash(request, "Buku tidak bisa dihapus karena sudah punya riwayat peminjaman.", "err")
        else:
            db.delete(item)
            db.commit()
            flash(request, "Buku dihapus.")
    return go("/buku")


# ======================= MASTER: ANGGOTA =======================
@app.get("/anggota", response_class=HTMLResponse)
def anggota_list(request: Request, q: str = "", db: Session = Depends(get_db),
                 user: User = Depends(require_login)):
    stmt = select(Anggota).order_by(Anggota.kode)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Anggota.nama.ilike(like), Anggota.kode.ilike(like),
                              Anggota.email.ilike(like)))
    return render(request, "anggota_list.html", user, rows=db.scalars(stmt).all(), q=q)


@app.get("/anggota/tambah", response_class=HTMLResponse)
def anggota_new(request: Request, user: User = Depends(require_login)):
    return render(request, "anggota_form.html", user, item=None)


@app.post("/anggota/tambah")
def anggota_create(request: Request, kode: str = Form(...), nama: str = Form(...),
                   email: str = Form(""), telepon: str = Form(""), alamat: str = Form(""),
                   db: Session = Depends(get_db), user: User = Depends(require_login)):
    db.add(Anggota(kode=kode.strip().upper(), nama=nama.strip(), email=email.strip(),
                   telepon=telepon.strip(), alamat=alamat.strip()))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        flash(request, "Kode anggota sudah ada.", "err")
        return go("/anggota/tambah")
    flash(request, "Anggota ditambahkan.")
    return go("/anggota")


@app.get("/anggota/{id}/edit", response_class=HTMLResponse)
def anggota_edit(id: int, request: Request, db: Session = Depends(get_db),
                 user: User = Depends(require_login)):
    item = db.get(Anggota, id)
    if not item:
        raise HTTPException(404, "Anggota tidak ditemukan")
    return render(request, "anggota_form.html", user, item=item)


@app.post("/anggota/{id}/edit")
def anggota_update(id: int, request: Request, kode: str = Form(...), nama: str = Form(...),
                   email: str = Form(""), telepon: str = Form(""), alamat: str = Form(""),
                   db: Session = Depends(get_db), user: User = Depends(require_login)):
    item = db.get(Anggota, id)
    if not item:
        raise HTTPException(404, "Anggota tidak ditemukan")
    item.kode, item.nama = kode.strip().upper(), nama.strip()
    item.email, item.telepon, item.alamat = email.strip(), telepon.strip(), alamat.strip()
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        flash(request, "Kode anggota sudah dipakai anggota lain.", "err")
        return go(f"/anggota/{id}/edit")
    flash(request, "Anggota diperbarui.")
    return go("/anggota")


@app.post("/anggota/{id}/hapus")
def anggota_delete(id: int, request: Request, db: Session = Depends(get_db),
                   user: User = Depends(require_login)):
    item = db.get(Anggota, id)
    if item:
        if item.peminjaman:
            flash(request, "Anggota tidak bisa dihapus karena sudah punya riwayat peminjaman.", "err")
        else:
            db.delete(item)
            db.commit()
            flash(request, "Anggota dihapus.")
    return go("/anggota")


# ======================= TRANSAKSI: PEMINJAMAN =======================
@app.get("/peminjaman", response_class=HTMLResponse)
def pinjam_list(request: Request, status: str = "", db: Session = Depends(get_db),
                user: User = Depends(require_login)):
    stmt = select(Peminjaman).order_by(Peminjaman.id.desc())
    stmt = apply_status(stmt, status)
    return render(request, "peminjaman_list.html", user, rows=db.scalars(stmt).all(), status=status)


def apply_status(stmt, status: str):
    today = date.today()
    if status == "dikembalikan":
        return stmt.where(Peminjaman.tgl_kembali.is_not(None))
    if status == "dipinjam":
        return stmt.where(Peminjaman.tgl_kembali.is_(None), Peminjaman.tgl_jatuh_tempo >= today)
    if status == "terlambat":
        return stmt.where(Peminjaman.tgl_kembali.is_(None), Peminjaman.tgl_jatuh_tempo < today)
    return stmt


@app.get("/peminjaman/tambah", response_class=HTMLResponse)
def pinjam_new(request: Request, db: Session = Depends(get_db), user: User = Depends(require_login)):
    return render(request, "peminjaman_form.html", user,
                  anggota=db.scalars(select(Anggota).order_by(Anggota.nama)).all(),
                  buku=db.scalars(select(Buku).where(Buku.stok > 0).order_by(Buku.judul)).all())


@app.post("/peminjaman/tambah")
def pinjam_create(request: Request, anggota_id: int = Form(...), buku_id: int = Form(...),
                  lama: int = Form(7), db: Session = Depends(get_db),
                  user: User = Depends(require_login)):
    anggota, buku = db.get(Anggota, anggota_id), db.get(Buku, buku_id)
    if not anggota or not buku:
        flash(request, "Anggota atau buku tidak valid.", "err")
        return go("/peminjaman/tambah")
    if buku.stok < 1:
        flash(request, "Stok buku habis.", "err")
        return go("/peminjaman/tambah")
    if not 1 <= lama <= 60:
        flash(request, "Lama pinjam harus 1-60 hari.", "err")
        return go("/peminjaman/tambah")
    sudah = db.scalar(select(func.count(Peminjaman.id)).where(
        Peminjaman.anggota_id == anggota_id, Peminjaman.buku_id == buku_id,
        Peminjaman.tgl_kembali.is_(None)))
    if sudah:
        flash(request, "Anggota ini masih meminjam buku yang sama.", "err")
        return go("/peminjaman/tambah")
    today = date.today()
    buku.stok -= 1
    db.add(Peminjaman(anggota_id=anggota_id, buku_id=buku_id, petugas_id=user.id,
                      tgl_pinjam=today, tgl_jatuh_tempo=today + timedelta(days=lama)))
    db.commit()
    flash(request, f"Peminjaman dicatat. Jatuh tempo {(today + timedelta(days=lama)):%d-%m-%Y}.")
    return go("/peminjaman")


@app.post("/peminjaman/{id}/kembali")
def pinjam_return(id: int, request: Request, db: Session = Depends(get_db),
                  user: User = Depends(require_login)):
    p = db.get(Peminjaman, id)
    if not p or p.tgl_kembali:
        flash(request, "Data tidak ditemukan atau sudah dikembalikan.", "err")
        return go("/peminjaman")
    p.tgl_kembali = date.today()
    p.denda = p.hari_terlambat * DENDA_PER_HARI
    p.buku.stok += 1
    db.commit()
    if p.denda:
        flash(request, f"Buku dikembalikan. Terlambat {p.hari_terlambat} hari, denda Rp {p.denda:,}".replace(",", "."), "err")
    else:
        flash(request, "Buku dikembalikan tepat waktu.")
    return go("/peminjaman")


@app.post("/peminjaman/{id}/hapus")
def pinjam_delete(id: int, request: Request, db: Session = Depends(get_db),
                  user: User = Depends(require_login)):
    p = db.get(Peminjaman, id)
    if p:
        if not p.tgl_kembali:
            p.buku.stok += 1  # kembalikan stok jika transaksi dibatalkan
        db.delete(p)
        db.commit()
        flash(request, "Transaksi dihapus.")
    return go("/peminjaman")


# ======================= REPORT =======================
def parse_date(s: str):
    try:
        return date.fromisoformat(s) if s else None
    except ValueError:
        return None


def query_laporan(db: Session, dari: str, sampai: str, status: str):
    stmt = select(Peminjaman).order_by(Peminjaman.tgl_pinjam.desc(), Peminjaman.id.desc())
    d1, d2 = parse_date(dari), parse_date(sampai)
    if d1:
        stmt = stmt.where(Peminjaman.tgl_pinjam >= d1)
    if d2:
        stmt = stmt.where(Peminjaman.tgl_pinjam <= d2)
    return db.scalars(apply_status(stmt, status)).all()


@app.get("/laporan/peminjaman", response_class=HTMLResponse)
def laporan_pinjam(request: Request, dari: str = "", sampai: str = "", status: str = "",
                   db: Session = Depends(get_db), user: User = Depends(require_login)):
    rows = query_laporan(db, dari, sampai, status)
    return render(request, "laporan_peminjaman.html", user, rows=rows, dari=dari,
                  sampai=sampai, status=status, hari_ini=date.today())


@app.get("/laporan/peminjaman.csv")
def laporan_pinjam_csv(dari: str = "", sampai: str = "", status: str = "",
                       db: Session = Depends(get_db), user: User = Depends(require_login)):
    rows = query_laporan(db, dari, sampai, status)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["No", "Anggota", "Buku", "Tgl Pinjam", "Jatuh Tempo", "Tgl Kembali", "Status", "Denda"])
    for i, p in enumerate(rows, 1):
        w.writerow([i, p.anggota.nama, p.buku.judul, p.tgl_pinjam, p.tgl_jatuh_tempo,
                    p.tgl_kembali or "", p.status, p.denda_efektif])
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=laporan_peminjaman.csv"})


@app.get("/laporan/denda", response_class=HTMLResponse)
def laporan_denda(request: Request, db: Session = Depends(get_db), user: User = Depends(require_login)):
    rows = [p for p in db.scalars(select(Peminjaman).order_by(Peminjaman.tgl_jatuh_tempo.desc())).all()
            if p.denda_efektif > 0]
    total_lunas = sum(p.denda for p in rows if p.tgl_kembali)
    total_berjalan = sum(p.denda_efektif for p in rows if not p.tgl_kembali)
    return render(request, "laporan_denda.html", user, rows=rows,
                  total_lunas=total_lunas, total_berjalan=total_berjalan)
