# SI Perpustakaan (FastAPI + Jinja2 + SQLAlchemy)

Studi kasus CRUD untuk Proyek Tugas Pemrograman Web.

| Syarat tugas | Di aplikasi ini |
|---|---|
| Basis data | SQLite (lokal otomatis) atau PostgreSQL (`DATABASE_URL`) |
| Login / register / dashboard | `/login`, `/register`, `/` (statistik, terlambat, buku terpopuler) |
| File Master | `buku`, `anggota` (CRUD penuh + pencarian), `users` |
| File Transaksi | `peminjaman` (pinjam, kembalikan, hapus; stok otomatis berubah) |
| File Report | Laporan peminjaman (filter tanggal/status, CSV, cetak PDF) dan laporan denda |
| Hosting gratis | lihat bagian Deploy |

## Jalankan di laptop (VS Code)

```bash
python -m venv venv
venv\Scripts\activate          # Windows  (Mac/Linux: source venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env         # Mac/Linux: cp .env.example .env
uvicorn main:app --reload
```
ctrl + shift + P lalu pilih Python: Select Interpreter lalu click perpustakaan\venv\Scripts\python.exe jika mengalami eror di main.py bagian fastapinya eror
buka neon untuk melihat databasenya

Buka http://127.0.0.1:8000, login `admin` / `admin123`.

Tanpa `DATABASE_URL`, aplikasi memakai file `perpustakaan.db` (SQLite), jadi langsung jalan.
Untuk PostgreSQL + pgAdmin: buat database `perpustakaan`, lalu isi di `.env`:

```
DATABASE_URL=postgresql://postgres:admin@localhost:5432/db_perpustakaan
```

Tabel dibuat otomatis saat aplikasi pertama kali jalan, dan data contoh diisi jika database kosong (`SEED_DEMO=1`).

## Deploy gratis: Render (aplikasi) + Neon (PostgreSQL)

Syarat gratis bisa berubah, jadi cek halaman harga masing-masing sebelum presentasi.

1. **Database**: daftar di neon.tech, buat project, salin *connection string* (`postgresql://...`).
2. **GitHub**: push folder ini ke repository (file `.env` jangan ikut; sudah aman karena hanya `.env.example` yang disertakan, tambahkan `.env` ke `.gitignore`).
3. **Render**: New → Web Service → pilih repo, lalu isi:
   - Runtime: Python 3
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - Instance type: Free
4. **Environment Variables** di Render:
   - `DATABASE_URL` = connection string dari Neon
   - `SECRET_KEY` = string acak panjang
   - `SEED_DEMO` = `1` (data contoh untuk demo)
5. Deploy. Setelah hidup, buka URL `*.onrender.com` dan login.

Catatan:
- Layanan gratis Render "tidur" saat tidak dipakai, akses pertama bisa lambat ±1 menit. Buka sebelum presentasi.
- Segera ganti password `admin` setelah deploy (register akun baru lalu jangan pakai admin default untuk demo publik).
- Alternatif hosting: Koyeb, Railway (kredit trial), Fly.io. Langkahnya serupa (start command yang sama + `DATABASE_URL`).

## Struktur

```
main.py        routes, auth, laporan
models.py      tabel (users, anggota, buku, peminjaman) + aturan denda
database.py    koneksi DB
templates/     halaman Jinja2
static/        CSS
```

## Alur pembagian tugas kelompok (saran)
- Master (buku, anggota) · Transaksi (peminjaman/pengembalian) · Auth + dashboard · Laporan + hosting + slide
