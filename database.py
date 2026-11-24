import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # python-dotenv opsional
    pass

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


def _database_url() -> str:
    # Lokal: SQLite otomatis. Hosting/PostgreSQL: isi DATABASE_URL.
    url = os.getenv("DATABASE_URL", "sqlite:///./perpustakaan.db")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


DATABASE_URL = _database_url()
_is_sqlite = DATABASE_URL.startswith("sqlite")

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
