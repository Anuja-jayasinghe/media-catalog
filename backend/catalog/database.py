"""SQLAlchemy models and database setup for the shared catalog."""

from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


BACKEND = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND.parent / ".env")
load_dotenv(BACKEND / ".env")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


DEFAULT_SQLITE = f"sqlite:///{BACKEND / 'catalog.sqlite3'}"
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_SQLITE)
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class CatalogUser(Base):
    __tablename__ = "catalog_users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    clerk_user_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    entries: Mapped[list[LibraryEntry]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Title(Base):
    __tablename__ = "titles"
    __table_args__ = (UniqueConstraint("provider", "media_type", "provider_id", name="uq_title_source"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    provider: Mapped[str] = mapped_column(String(16), index=True)
    media_type: Mapped[str] = mapped_column(String(8), index=True)
    provider_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(500), index=True)
    overview: Mapped[str] = mapped_column(Text, default="")
    poster_url: Mapped[str | None] = mapped_column(Text)
    release_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    entries: Mapped[list[LibraryEntry]] = relationship(back_populates="title")


class LibraryEntry(Base):
    __tablename__ = "library_entries"
    __table_args__ = (UniqueConstraint("user_id", "title_id", name="uq_user_title"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    user_id: Mapped[str] = mapped_column(ForeignKey("catalog_users.id", ondelete="CASCADE"), index=True)
    title_id: Mapped[str] = mapped_column(ForeignKey("titles.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(16))
    completed_on: Mapped[date | None] = mapped_column(Date)
    date_precision: Mapped[str] = mapped_column(String(8), default="none")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    user: Mapped[CatalogUser] = relationship(back_populates="entries")
    title: Mapped[Title] = relationship(back_populates="entries")


class SearchSnapshot(Base):
    __tablename__ = "search_snapshots"

    key: Mapped[str] = mapped_column(String(256), primary_key=True)
    title_ids_json: Mapped[str] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    result_count: Mapped[int] = mapped_column(Integer, default=0)


def init_database() -> None:
    Base.metadata.create_all(engine)


if __name__ == "__main__":
    init_database()
    print("Database schema ready")
