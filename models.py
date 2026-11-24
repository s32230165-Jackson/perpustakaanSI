import os
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base

DENDA_PER_HARI = int(os.getenv("DENDA_PER_HARI", "1000"))


# ---------- FILE MASTER ----------
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    nama: Mapped[str] = mapped_column(String(100))
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="petugas")  # admin / petugas
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Anggota(Base):
    __tablename__ = "anggota"
    id: Mapped[int] = mapped_column(primary_key=True)
    kode: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    nama: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(100), default="")
    telepon: Mapped[str] = mapped_column(String(30), default="")
    alamat: Mapped[str] = mapped_column(Text, default="")

    peminjaman: Mapped[list["Peminjaman"]] = relationship(back_populates="anggota")


class Buku(Base):
    __tablename__ = "buku"
    id: Mapped[int] = mapped_column(primary_key=True)
    kode: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    judul: Mapped[str] = mapped_column(String(200))
    penulis: Mapped[str] = mapped_column(String(100), default="")
    penerbit: Mapped[str] = mapped_column(String(100), default="")
    tahun: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kategori: Mapped[str] = mapped_column(String(60), default="Umum")
    stok: Mapped[int] = mapped_column(Integer, default=1)

    peminjaman: Mapped[list["Peminjaman"]] = relationship(back_populates="buku")


# ---------- FILE TRANSAKSI ----------
class Peminjaman(Base):
    __tablename__ = "peminjaman"
    id: Mapped[int] = mapped_column(primary_key=True)
    anggota_id: Mapped[int] = mapped_column(ForeignKey("anggota.id"))
    buku_id: Mapped[int] = mapped_column(ForeignKey("buku.id"))
    petugas_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    tgl_pinjam: Mapped[date] = mapped_column(Date)
    tgl_jatuh_tempo: Mapped[date] = mapped_column(Date)
    tgl_kembali: Mapped[date | None] = mapped_column(Date, nullable=True)
    denda: Mapped[int] = mapped_column(Integer, default=0)  # final, diisi saat dikembalikan

    anggota: Mapped[Anggota] = relationship(back_populates="peminjaman")
    buku: Mapped[Buku] = relationship(back_populates="peminjaman")
    petugas: Mapped[User | None] = relationship()

    @property
    def hari_terlambat(self) -> int:
        akhir = self.tgl_kembali or date.today()
        return max(0, (akhir - self.tgl_jatuh_tempo).days)

    @property
    def denda_efektif(self) -> int:
        """Denda final jika sudah kembali, perkiraan berjalan jika belum."""
        if self.tgl_kembali:
            return self.denda
        return self.hari_terlambat * DENDA_PER_HARI

    @property
    def status(self) -> str:
        if self.tgl_kembali:
            return "dikembalikan"
        return "terlambat" if date.today() > self.tgl_jatuh_tempo else "dipinjam"
