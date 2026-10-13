"""SQLAlchemy models and database setup for the shared catalog."""

from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine, inspect, select, text
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
    display_name: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    entries: Mapped[list[LibraryEntry]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Title(Base):
    __tablename__ = "titles"
    __table_args__ = (UniqueConstraint("provider", "media_type", "provider_id", name="uq_title_source"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    provider: Mapped[str] = mapped_column(String(16), index=True)
    media_type: Mapped[str] = mapped_column(String(8), index=True)
    provider_id: Mapped[str] = mapped_column(String(64))
    verified: Mapped[bool] = mapped_column(Boolean, default=True)
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
    rating_half_steps: Mapped[int | None] = mapped_column(Integer)
    review: Mapped[str | None] = mapped_column(Text)
    favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    platforms_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    user: Mapped[CatalogUser] = relationship(back_populates="entries")
    title: Mapped[Title] = relationship(back_populates="entries")
    list_links: Mapped[list[EntryList]] = relationship(back_populates="entry", cascade="all, delete-orphan")


class CustomList(Base):
    __tablename__ = "custom_lists"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_user_list_name"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    user_id: Mapped[str] = mapped_column(ForeignKey("catalog_users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    entry_links: Mapped[list[EntryList]] = relationship(back_populates="custom_list", cascade="all, delete-orphan")


class EntryList(Base):
    __tablename__ = "entry_lists"
    __table_args__ = (UniqueConstraint("entry_id", "list_id", name="uq_entry_list"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    entry_id: Mapped[str] = mapped_column(ForeignKey("library_entries.id", ondelete="CASCADE"), index=True)
    list_id: Mapped[str] = mapped_column(ForeignKey("custom_lists.id", ondelete="CASCADE"), index=True)
    entry: Mapped[LibraryEntry] = relationship(back_populates="list_links")
    custom_list: Mapped[CustomList] = relationship(back_populates="entry_links")


class EntryRevision(Base):
    """Private operational audit trail; never returned by public endpoints."""

    __tablename__ = "entry_revisions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    user_id: Mapped[str] = mapped_column(ForeignKey("catalog_users.id", ondelete="CASCADE"), index=True)
    title_id: Mapped[str] = mapped_column(ForeignKey("titles.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(24), default="manual")
    before_json: Mapped[str | None] = mapped_column(Text)
    after_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SeasonProgress(Base):
    __tablename__ = "season_progress"
    __table_args__ = (UniqueConstraint("user_id", "title_id", "season_number", name="uq_user_tv_season"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    user_id: Mapped[str] = mapped_column(ForeignKey("catalog_users.id", ondelete="CASCADE"), index=True)
    title_id: Mapped[str] = mapped_column(ForeignKey("titles.id", ondelete="CASCADE"), index=True)
    season_number: Mapped[int] = mapped_column(Integer)
    through_episode: Mapped[int | None] = mapped_column(Integer)
    marked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ShareLink(Base):
    __tablename__ = "share_links"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    user_id: Mapped[str] = mapped_column(ForeignKey("catalog_users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    user_id: Mapped[str] = mapped_column(ForeignKey("catalog_users.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(32))
    created_list_names_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    reverted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ImportChange(Base):
    __tablename__ = "import_changes"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    batch_id: Mapped[str] = mapped_column(ForeignKey("import_batches.id", ondelete="CASCADE"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    title_id: Mapped[str | None] = mapped_column(ForeignKey("titles.id", ondelete="CASCADE"))
    object_kind: Mapped[str] = mapped_column(String(16))
    season_number: Mapped[int | None] = mapped_column(Integer)
    before_json: Mapped[str | None] = mapped_column(Text)
    after_json: Mapped[str | None] = mapped_column(Text)
    reverted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SearchSnapshot(Base):
    __tablename__ = "search_snapshots"

    key: Mapped[str] = mapped_column(String(256), primary_key=True)
    title_ids_json: Mapped[str] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    result_count: Mapped[int] = mapped_column(Integer, default=0)


class ProviderRateWindow(Base):
    """Shared admission counter for all API instances using one provider key."""

    __tablename__ = "provider_rate_windows"

    provider: Mapped[str] = mapped_column(String(16), primary_key=True)
    second: Mapped[int] = mapped_column(Integer, primary_key=True)
    used: Mapped[int] = mapped_column(Integer, default=0)


class CatalogRefreshCursor(Base):
    """Persist the next browse page for each refresh lane."""

    __tablename__ = "catalog_refresh_cursors"

    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    next_page: Mapped[int] = mapped_column(Integer, default=2)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


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
    excluded_title_ids_json: Mapped[str] = mapped_column(Text, default="[]")
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
    # add columns to existing tables, so apply additive report fields.
    with engine.begin() as connection:
        columns = {column["name"] for column in inspect(connection).get_columns("missing_title_reports")}
        timestamp_type = DateTime(timezone=True).compile(dialect=engine.dialect)
        for column in ("github_issue_closed_at", "admin_notified_at"):
            if column not in columns:
                connection.execute(text(f"ALTER TABLE missing_title_reports ADD COLUMN {column} {timestamp_type}"))
        if "excluded_title_ids_json" not in columns:
            connection.execute(text("ALTER TABLE missing_title_reports ADD COLUMN excluded_title_ids_json TEXT DEFAULT '[]'"))
        entry_columns = {column["name"] for column in inspect(connection).get_columns("library_entries")}
        additions = {
            "rating_half_steps": "INTEGER",
            "review": "TEXT",
            "favorite": "BOOLEAN DEFAULT FALSE",
            "platforms_json": "TEXT DEFAULT '[]'",
        }
        for column, definition in additions.items():
            if column not in entry_columns:
                connection.execute(text(f"ALTER TABLE library_entries ADD COLUMN {column} {definition}"))
        user_columns = {column["name"] for column in inspect(connection).get_columns("catalog_users")}
        if "display_name" not in user_columns:
            connection.execute(text("ALTER TABLE catalog_users ADD COLUMN display_name VARCHAR(80)"))
        title_columns = {column["name"] for column in inspect(connection).get_columns("titles")}
        if "verified" not in title_columns:
            connection.execute(text("ALTER TABLE titles ADD COLUMN verified BOOLEAN DEFAULT TRUE"))
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
