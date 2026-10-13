"""SQLAlchemy models and database setup for the shared catalog."""

from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine, inspect, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


BACKEND = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND.parent / ".env")
load_dotenv(BACKEND / ".env")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


DEFAULT_SQLITE = f"sqlite:///{BACKEND / 'catalog.sqlite3'}"
# The module entrypoint runs schema setup. Neon recommends a direct connection
# for that job, while regular API traffic should use the pooled DATABASE_URL.
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_SQLITE)
if __name__ == "__main__":
    DATABASE_URL = os.getenv("DATABASE_URL_UNPOOLED") or DATABASE_URL
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


class TitleIdentity(Base):
    """An exact provider or external ID attached to a canonical title."""

    __tablename__ = "title_identities"
    __table_args__ = (UniqueConstraint("namespace", "media_type", "external_id", name="uq_title_identity"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    title_id: Mapped[str] = mapped_column(ForeignKey("titles.id", ondelete="CASCADE"), index=True)
    namespace: Mapped[str] = mapped_column(String(32))
    media_type: Mapped[str] = mapped_column(String(8))
    external_id: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class TitleAlias(Base):
    """Search text; aliases never establish identity on their own."""

    __tablename__ = "title_aliases"
    __table_args__ = (UniqueConstraint("title_id", "normalized", name="uq_title_alias"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    title_id: Mapped[str] = mapped_column(ForeignKey("titles.id", ondelete="CASCADE"), index=True)
    value: Mapped[str] = mapped_column(String(500))
    normalized: Mapped[str] = mapped_column(String(500), index=True)
    source: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class MissingTitleReport(Base):
    __tablename__ = "missing_title_reports"
    __table_args__ = (UniqueConstraint("media_type", "normalized_name", name="uq_missing_title"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    media_type: Mapped[str] = mapped_column(String(8), index=True)
    name: Mapped[str] = mapped_column(String(500))
    normalized_name: Mapped[str] = mapped_column(String(500), index=True)
    status: Mapped[str] = mapped_column(String(16), default="open")
    resolved_title_id: Mapped[str | None] = mapped_column(ForeignKey("titles.id"))
    github_issue_number: Mapped[int | None] = mapped_column(Integer)
    github_issue_url: Mapped[str | None] = mapped_column(Text)
    github_issue_closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    admin_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class ReportSubscriber(Base):
    __tablename__ = "report_subscribers"
    __table_args__ = (UniqueConstraint("report_id", "email", name="uq_report_subscriber"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    report_id: Mapped[str] = mapped_column(ForeignKey("missing_title_reports.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(320))
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivery_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


def init_database() -> None:
    Base.metadata.create_all(engine)
    # Older development databases already have this table. create_all does not
    # add columns to existing tables, so apply the two additive report fields.
    with engine.begin() as connection:
        columns = {column["name"] for column in inspect(connection).get_columns("missing_title_reports")}
        timestamp_type = DateTime(timezone=True).compile(dialect=engine.dialect)
        for column in ("github_issue_closed_at", "admin_notified_at"):
            if column not in columns:
                connection.execute(text(f"ALTER TABLE missing_title_reports ADD COLUMN {column} {timestamp_type}"))
    # Existing local records predate the identity and alias tables.
    from .identity import normalize_name

    with SessionLocal() as session:
        for title in session.scalars(select(Title)).all():
            if session.scalar(select(TitleIdentity.id).where(
                TitleIdentity.namespace == title.provider,
                TitleIdentity.media_type == title.media_type,
                TitleIdentity.external_id == title.provider_id,
            )) is None:
                session.add(TitleIdentity(title_id=title.id, namespace=title.provider,
                                          media_type=title.media_type, external_id=title.provider_id))
            key = normalize_name(title.name)
            if key and session.scalar(select(TitleAlias.id).where(
                TitleAlias.title_id == title.id, TitleAlias.normalized == key,
            )) is None:
                session.add(TitleAlias(title_id=title.id, value=title.name,
                                       normalized=key, source=title.provider))
        session.commit()


if __name__ == "__main__":
    init_database()
    print("Database schema ready")
