from pathlib import Path
import os

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.orm import DeclarativeBase, sessionmaker

BASE_DIR = Path(__file__).resolve().parents[1]
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'schedulo.db'}")
if DATABASE_URL.startswith("postgresql://"):
    # SQLAlchemy otherwise selects the psycopg2 dialect for this shorthand,
    # while the project intentionally installs the psycopg v3 driver.
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    pool_pre_ping=True,
    pool_recycle=300,
    poolclass=NullPool if not DATABASE_URL.startswith("sqlite") else None,
)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
