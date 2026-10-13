"""Public catalog search and Clerk-protected personal library."""

from __future__ import annotations

import json
import os
import re
import asyncio
import time
import uuid
from hmac import compare_digest
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import delete, func, select, text, tuple_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .auth import require_clerk_user
from .database import CatalogRefreshCursor, CatalogUser, CustomList, EntryList, EntryRevision, LibraryEntry, MissingTitleReport, ProviderRateWindow, ReportSubscriber, SearchSnapshot, SessionLocal, Title, TitleAlias, TitleIdentity, engine, init_database, utc_now
from .identity import normalize_name
from .providers import ProviderSearchError, ProviderTitle, browse_providers, search_providers, title_media
from .reports import create_github_issue, close_github_issue, send_admin_email, send_publication_email


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Production schema is initialized as a deployment step, not on each Function invocation.
    if os.getenv("AUTO_CREATE_SCHEMA", "1" if engine.dialect.name == "sqlite" else "0") == "1":
        init_database()
    yield


app = FastAPI(title="Media Catalog API", version="0.1.0", lifespan=lifespan)
origins = [origin.strip() for origin in os.getenv("FRONTEND_ORIGINS", "http://localhost:3000").split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


def get_session():
    with SessionLocal() as session:
        yield session


Db = Annotated[Session, Depends(get_session)]
ClerkUser = Annotated[str, Depends(require_clerk_user)]


class TitleOut(BaseModel):
    id: str
    media_type: str
    provider: str
    provider_id: str
    name: str
    overview: str
    poster_url: str | None
    release_date: date | None


class SearchOut(BaseModel):
    results: list[TitleOut]
    warnings: list[str] = []
    cached: bool = False
    has_more: bool = False


class TitleMediaOut(BaseModel):
    trailer_url: str | None
    external_url: str
    external_label: str


class MissingTitleCreate(BaseModel):
    name: str
    media_type: Literal["movie", "tv", "game"]
    email: str | None = None
    force_report: bool = False

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) < 2 or len(value) > 160 or not normalize_name(value):
            raise ValueError("Enter a title between 2 and 160 characters")
        return value

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str | None) -> str | None:
        if not value:
            return None
        value = value.strip().casefold()
        if len(value) > 320 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Enter a valid email address or leave it blank")
        return value


class MissingTitleOut(BaseModel):
    status: Literal["found", "choices", "reported"]
    title: TitleOut | None = None
    choices: list[TitleOut] = []
    report_id: str | None = None


class TrackingUpdate(BaseModel):
    status: Literal["planned", "in_progress", "completed", "dropped"]
    completed_on: date | None = None
    date_precision: Literal["none", "day", "month"] = "none"
    rating_half_steps: int | None = Field(default=None, ge=1, le=10)
    review: str | None = Field(default=None, max_length=10000)
    favorite: bool | None = None
    platforms: list[str] | None = Field(default=None, max_length=20)
    lists: list[str] | None = Field(default=None, max_length=20)

    @model_validator(mode="after")
    def valid_date(self):
        if self.status != "completed" and (self.completed_on or self.date_precision != "none"):
            raise ValueError("Only completed entries can have a completion date")
        if (self.date_precision == "none") != (self.completed_on is None):
            raise ValueError("A completion date and its precision must be provided together")
        if self.date_precision == "month" and self.completed_on and self.completed_on.day != 1:
            raise ValueError("Month-only dates must use the first day of the month")
        return self

    @field_validator("platforms", "lists")
    @classmethod
    def valid_labels(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        cleaned = [" ".join(value.split()) for value in values]
        if any(not value or len(value) > 80 for value in cleaned):
            raise ValueError("Names must be between 1 and 80 characters")
        if len({value.casefold() for value in cleaned}) != len(cleaned):
            raise ValueError("Names must be unique")
        return cleaned


class LibraryOut(BaseModel):
    title: TitleOut
    status: str
    completed_on: date | None
    date_precision: str
    rating_half_steps: int | None
    review: str | None
    favorite: bool
    platforms: list[str]
    lists: list[str]
    updated_at: datetime


class CustomListOut(BaseModel):
    id: str
    name: str
    count: int


class RenameList(BaseModel):
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("A list needs a name")
        return value


def title_out(title: Title) -> TitleOut:
    return TitleOut.model_validate({column.name: getattr(title, column.name) for column in Title.__table__.columns})


def entry_out(entry: LibraryEntry) -> LibraryOut:
    return LibraryOut(
        title=title_out(entry.title), status=entry.status,
        completed_on=entry.completed_on, date_precision=entry.date_precision,
        rating_half_steps=entry.rating_half_steps, review=entry.review,
        favorite=bool(entry.favorite), platforms=json.loads(entry.platforms_json or "[]"),
        lists=sorted((link.custom_list.name for link in entry.list_links), key=str.casefold),
        updated_at=entry.updated_at,
    )


def entry_snapshot(entry: LibraryEntry) -> dict:
    return {
        "status": entry.status,
        "completed_on": entry.completed_on.isoformat() if entry.completed_on else None,
        "date_precision": entry.date_precision,
        "rating_half_steps": entry.rating_half_steps,
        "review": entry.review,
        "favorite": bool(entry.favorite),
        "platforms": json.loads(entry.platforms_json or "[]"),
        "lists": sorted((link.custom_list.name for link in entry.list_links), key=str.casefold),
    }


def record_revision(session: Session, user_id: str, title_id: str, before: dict | None, after: dict | None):
    if before != after:
        session.add(EntryRevision(user_id=user_id, title_id=title_id, source="manual",
                                  before_json=json.dumps(before) if before else None,
                                  after_json=json.dumps(after) if after else None))


def upsert_statement(model, values: dict, constraint_columns: list[str], updates: dict):
    if engine.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    elif engine.dialect.name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:
        raise RuntimeError("Use PostgreSQL or SQLite")
    return insert(model).values(**values).on_conflict_do_update(index_elements=constraint_columns, set_=updates)


def persist_titles(session: Session, found: list[ProviderTitle]) -> list[Title]:
    ordered: list[Title] = []
    seen: set[str] = set()
    for item in found:
        identity = session.scalar(select(TitleIdentity).where(
            TitleIdentity.namespace == item.provider,
            TitleIdentity.media_type == item.media_type,
            TitleIdentity.external_id == item.provider_id,
        ))
        title = session.get(Title, identity.title_id) if identity else None
        if title is None:
            for namespace, external_id in item.external_ids:
                identity = session.scalar(select(TitleIdentity).where(
                    TitleIdentity.namespace == namespace,
                    TitleIdentity.media_type == item.media_type,
                    TitleIdentity.external_id == external_id,
                ))
                if identity:
                    title = session.get(Title, identity.title_id)
                    break
        if title is None:
            title = session.scalar(select(Title).where(
                Title.provider == item.provider,
                Title.media_type == item.media_type,
                Title.provider_id == item.provider_id,
            ))
        if title is None:
            title = Title(id=uuid.uuid4().hex, provider=item.provider, media_type=item.media_type,
                          provider_id=item.provider_id, name=item.name,
                          overview=item.overview, poster_url=item.poster_url,
                          release_date=item.release_date)
            session.add(title)
            session.flush()
            previous_name = item.name
        else:
            previous_name = title.name
            # A primary source can replace a supplemental display record while
            # preserving the canonical ID and every attached user entry.
            promote = item.provider in {"tmdb", "igdb"} and title.provider in {"tvmaze", "rawg"}
            if promote:
                title.provider = item.provider
                title.provider_id = item.provider_id
            if promote or item.provider == title.provider:
                title.name = item.name
                title.overview = item.overview or title.overview
                title.poster_url = item.poster_url or title.poster_url
                title.release_date = item.release_date or title.release_date
                title.updated_at = utc_now()
        for namespace, external_id in ((item.provider, item.provider_id), *item.external_ids):
            linked = session.scalar(select(TitleIdentity).where(
                TitleIdentity.namespace == namespace,
                TitleIdentity.media_type == item.media_type,
                TitleIdentity.external_id == external_id,
            ))
            if linked is None:
                session.add(TitleIdentity(title_id=title.id, namespace=namespace,
                                          media_type=item.media_type, external_id=external_id))
        for value in (previous_name, title.name, item.name, *item.aliases):
            key = normalize_name(value)
            if key and session.scalar(select(TitleAlias.id).where(
                TitleAlias.title_id == title.id, TitleAlias.normalized == key,
            )) is None:
                session.add(TitleAlias(title_id=title.id, value=value,
                                       normalized=key, source=item.provider))
        session.flush()
        if title.id not in seen:
            ordered.append(title)
            seen.add(title.id)
    resolve_known_reports(session, ordered)
    return ordered


def resolve_known_reports(session: Session, titles: list[Title]) -> None:
    keys = set()
    for title in titles:
        for alias in session.scalars(select(TitleAlias).where(TitleAlias.title_id == title.id)):
            keys.add((title.media_type, alias.normalized))
    if not keys:
        return
    reports = session.scalars(select(MissingTitleReport).where(
        MissingTitleReport.status == "open",
        tuple_(MissingTitleReport.media_type, MissingTitleReport.normalized_name).in_(keys),
    )).all()
    for report in reports:
        excluded = set(json.loads(report.excluded_title_ids_json or "[]"))
        matches = session.scalars(select(Title).join(TitleAlias, TitleAlias.title_id == Title.id).where(
            Title.media_type == report.media_type,
            TitleAlias.normalized == report.normalized_name,
        )).all()
        unique = {title.id: title for title in matches if title.id not in excluded}
        if len(unique) == 1:
            report.status = "resolved"
            report.resolved_title_id = next(iter(unique))
            report.updated_at = utc_now()


def local_search(session: Session, query: str, media_type: str) -> list[Title]:
    key = normalize_name(query)
    if not key:
        return []
    statement = select(Title).join(TitleAlias, TitleAlias.title_id == Title.id).where(
        TitleAlias.normalized.like(f"{key}%"),
    )
    if media_type != "all":
        statement = statement.where(Title.media_type == media_type)
    titles = session.scalars(statement.limit(60)).all()
    unique = {title.id: title for title in titles}
    return sorted(unique.values(), key=lambda title: (
        normalize_name(title.name) != key,
        not normalize_name(title.name).startswith(key),
        title.name.casefold(),
    ))[:30]


def snapshot_titles(session: Session, snapshot: SearchSnapshot) -> list[Title]:
    ids = json.loads(snapshot.title_ids_json)
    by_id = {item.id: item for item in session.scalars(select(Title).where(Title.id.in_(ids))).all()} if ids else {}
    return [by_id[item_id] for item_id in ids if item_id in by_id]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/health/ready")
def readiness(session: Db):
    """Report whether the configured catalog database accepts queries."""
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError as error:
        raise HTTPException(status_code=503, detail="Catalog database is unavailable") from error
    return {"status": "ready"}


@app.get("/api/search", response_model=SearchOut)
async def search(
    session: Db,
    q: Annotated[str, Query(min_length=2, max_length=120)],
    media_type: Literal["all", "movie", "tv", "game"] = "all",
):
    query = q.strip()
    if len(query) < 2:
        raise HTTPException(status_code=422, detail="Enter at least two characters")
    key = f"{media_type}:{query.casefold()}"
    snapshot = session.get(SearchSnapshot, key)
    fetched_at = snapshot.fetched_at if snapshot else None
    if fetched_at and fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    if snapshot and fetched_at and datetime.now(timezone.utc) - fetched_at < timedelta(minutes=10):
        cached = snapshot_titles(session, snapshot)
        cached_ids = {title.id for title in cached}
        cached.extend(title for title in local_search(session, query, media_type) if title.id not in cached_ids)
        return SearchOut(results=[title_out(title) for title in cached], cached=True)

    local = local_search(session, query, media_type)
    try:
        found, warnings = await search_providers(query, media_type)
    except ProviderSearchError as error:
        if snapshot:
            return SearchOut(results=[title_out(title) for title in snapshot_titles(session, snapshot)], warnings=["Showing older results while sources are unavailable"], cached=True)
        if local:
            return SearchOut(results=[title_out(title) for title in local], warnings=["Showing saved catalog matches while sources are unavailable"])
        raise HTTPException(status_code=502, detail=str(error)) from error

    titles = persist_titles(session, found)
    seen = {title.id for title in titles}
    titles.extend(title for title in local if title.id not in seen)
    if not warnings:
        values = {
            "key": key, "title_ids_json": json.dumps([title.id for title in titles]),
            "fetched_at": utc_now(), "result_count": len(titles),
        }
        session.execute(upsert_statement(
            SearchSnapshot, values, ["key"],
            {field: values[field] for field in ("title_ids_json", "fetched_at", "result_count")},
        ))
    session.commit()
    return SearchOut(results=[title_out(title) for title in titles], warnings=warnings)


@app.get("/api/discover", response_model=SearchOut)
async def discover(
    session: Db,
    section: Literal["popular", "recent", "upcoming"],
    media_type: Literal["all", "movie", "tv", "game"] = "all",
    page: Annotated[int, Query(ge=1, le=500)] = 1,
):
    today = datetime.now(timezone.utc).date()
    key = f"discover:{section}:{media_type}:{page}:{today.isoformat()}"
    snapshot = session.get(SearchSnapshot, key)
    fetched_at = snapshot.fetched_at if snapshot else None
    if fetched_at and fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    if snapshot and fetched_at and datetime.now(timezone.utc) - fetched_at < timedelta(hours=6):
        cached_titles = snapshot_titles(session, snapshot)
        return SearchOut(results=[title_out(title) for title in cached_titles], cached=True, has_more=len(cached_titles) >= 20)

    try:
        found, warnings = await browse_providers(section, media_type, today, page)
    except ProviderSearchError as error:
        if snapshot:
            cached_titles = snapshot_titles(session, snapshot)
            return SearchOut(results=[title_out(title) for title in cached_titles], warnings=["Showing older releases while sources are unavailable"], cached=True, has_more=len(cached_titles) >= 20)
        raise HTTPException(status_code=502, detail=str(error)) from error

    titles = persist_titles(session, found)
    if not warnings:
        values = {
            "key": key, "title_ids_json": json.dumps([title.id for title in titles]),
            "fetched_at": utc_now(), "result_count": len(titles),
        }
        session.execute(upsert_statement(
            SearchSnapshot, values, ["key"],
            {field: values[field] for field in ("title_ids_json", "fetched_at", "result_count")},
        ))
    session.commit()
    return SearchOut(results=[title_out(title) for title in titles], warnings=warnings, has_more=len(titles) >= 20)


@app.get("/api/titles/{title_id}/media", response_model=TitleMediaOut)
async def get_title_media(title_id: str, session: Db):
    title = session.get(Title, title_id)
    if title is None:
        raise HTTPException(status_code=404, detail="Title not found")
    try:
        media = await title_media(title.provider, title.media_type, title.provider_id)
        imdb_url = media.get("external_url") or ""
        if imdb_url.startswith("https://www.imdb.com/title/tt"):
            imdb_id = imdb_url.removeprefix("https://www.imdb.com/title/").strip("/")
            existing = session.scalar(select(TitleIdentity).where(
                TitleIdentity.namespace == "imdb", TitleIdentity.media_type == title.media_type,
                TitleIdentity.external_id == imdb_id,
            ))
            if existing is None:
                session.add(TitleIdentity(title_id=title.id, namespace="imdb",
                                          media_type=title.media_type, external_id=imdb_id))
                session.commit()
        return media
    except (ProviderSearchError, ValueError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=502, detail="Title media is temporarily unavailable") from error


@app.get("/api/titles/{title_id}", response_model=TitleOut)
def get_public_title(title_id: str, session: Db):
    title = session.get(Title, title_id)
    if title is None:
        raise HTTPException(status_code=404, detail="Title not found")
    return title_out(title)


def exact_catalog_matches(session: Session, name: str, media_type: str) -> list[Title]:
    found = session.scalars(select(Title).join(TitleAlias, TitleAlias.title_id == Title.id).where(
        Title.media_type == media_type,
        TitleAlias.normalized == normalize_name(name),
    )).all()
    return list({title.id: title for title in found}.values())


async def publish_report_operations(session: Session, report: MissingTitleReport) -> None:
    """Best-effort external effects. Unfinished work remains in the DB for retry."""
    if report.status == "open" and report.github_issue_number is None:
        try:
            issue = await create_github_issue(report)
            if issue:
                report.github_issue_number, report.github_issue_url = issue
                session.commit()
        except Exception:
            session.rollback()
    if report.admin_notified_at is None:
        try:
            if await send_admin_email(report):
                report.admin_notified_at = utc_now()
                session.commit()
        except Exception:
            session.rollback()


async def refresh_release_pages_for_title(session: Session, name: str, media_type: str) -> None:
    """Try current release pages once per title per hour before other fallbacks."""
    key = f"missing-refresh:{media_type}:{normalize_name(name)}"
    snapshot = session.get(SearchSnapshot, key)
    fetched_at = snapshot.fetched_at if snapshot else None
    if fetched_at and fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    if fetched_at and utc_now() - fetched_at < timedelta(hours=1):
        return

    today = datetime.now(timezone.utc).date()
    responses = await asyncio.gather(
        browse_providers("recent", media_type, today, 1),
        browse_providers("upcoming", media_type, today, 1),
        return_exceptions=True,
    )
    refreshed: list[Title] = []
    succeeded = 0
    for response in responses:
        if isinstance(response, asyncio.CancelledError):
            raise response
        if isinstance(response, Exception):
            continue
        found, warnings = response
        if warnings:
            continue
        refreshed.extend(persist_titles(session, found))
        succeeded += 1
    if succeeded == 2:
        values = {"key": key, "title_ids_json": json.dumps([title.id for title in refreshed]),
                  "fetched_at": utc_now(), "result_count": len(refreshed)}
        session.execute(upsert_statement(
            SearchSnapshot, values, ["key"],
            {field: values[field] for field in ("title_ids_json", "fetched_at", "result_count")},
        ))
    session.commit()


@app.post("/api/missing-titles", response_model=MissingTitleOut)
async def report_missing_title(payload: MissingTitleCreate, session: Db):
    existing = exact_catalog_matches(session, payload.name, payload.media_type)
    if not payload.force_report and len(existing) == 1:
        return MissingTitleOut(status="found", title=title_out(existing[0]))
    known_ids = {title.id for title in existing}
    try:
        await refresh_release_pages_for_title(session, payload.name, payload.media_type)
    except ProviderSearchError:
        pass
    existing = exact_catalog_matches(session, payload.name, payload.media_type)
    if payload.force_report:
        newly_found = [title for title in existing if title.id not in known_ids]
        if len(newly_found) == 1:
            return MissingTitleOut(status="found", title=title_out(newly_found[0]))
    elif len(existing) == 1:
        return MissingTitleOut(status="found", title=title_out(existing[0]))

    try:
        found, _ = await search_providers(payload.name, payload.media_type)
    except ProviderSearchError:
        found = []
    exact = [item for item in found if normalize_name(item.name) == normalize_name(payload.name)
             or any(normalize_name(alias) == normalize_name(payload.name) for alias in item.aliases)]
    if exact:
        persist_titles(session, exact)
        session.commit()
        existing = exact_catalog_matches(session, payload.name, payload.media_type)
    if payload.force_report:
        newly_found = [title for title in existing if title.id not in known_ids]
        if len(newly_found) == 1:
            return MissingTitleOut(status="found", title=title_out(newly_found[0]))
    else:
        if len(existing) == 1:
            return MissingTitleOut(status="found", title=title_out(existing[0]))
        if len(existing) > 1:
            return MissingTitleOut(status="choices", choices=[title_out(title) for title in existing[:10]])

    key = normalize_name(payload.name)
    report = session.scalar(select(MissingTitleReport).where(
        MissingTitleReport.media_type == payload.media_type,
        MissingTitleReport.normalized_name == key,
    ))
    if report is None:
        recent_count = session.scalar(select(func.count()).select_from(MissingTitleReport).where(
            MissingTitleReport.created_at >= utc_now() - timedelta(hours=1),
        )) or 0
        if recent_count >= 20:
            raise HTTPException(status_code=429, detail="Too many new reports right now. Please try again later.")
        report = MissingTitleReport(media_type=payload.media_type, name=payload.name,
                                    normalized_name=key, status="open")
        session.add(report)
        session.flush()
    if payload.force_report and known_ids and report.status == "open":
        excluded = set(json.loads(report.excluded_title_ids_json or "[]"))
        report.excluded_title_ids_json = json.dumps(sorted(excluded | known_ids))
    if payload.email and session.scalar(select(ReportSubscriber.id).where(
        ReportSubscriber.report_id == report.id, ReportSubscriber.email == payload.email,
    )) is None:
        session.add(ReportSubscriber(report_id=report.id, email=payload.email))
    session.commit()
    if report.status == "resolved" and report.resolved_title_id:
        title = session.get(Title, report.resolved_title_id)
        if title:
            return MissingTitleOut(status="found", title=title_out(title))
    await publish_report_operations(session, report)
    return MissingTitleOut(status="reported", report_id=report.id)


@app.post("/api/internal/reconcile")
async def reconcile_missing_titles(
    session: Db,
    authorization: Annotated[str | None, Header()] = None,
):
    require_job_authorization(authorization)
    checked = resolved = notified = 0
    open_reports = session.scalars(select(MissingTitleReport).where(
        MissingTitleReport.status == "open",
    ).order_by(MissingTitleReport.updated_at, MissingTitleReport.created_at).limit(20)).all()
    for report in open_reports:
        checked += 1
        excluded = set(json.loads(report.excluded_title_ids_json or "[]"))
        exact = [title for title in exact_catalog_matches(session, report.name, report.media_type)
                 if title.id not in excluded]
        if not exact:
            try:
                found, _ = await search_providers(report.name, report.media_type)
                matches = [item for item in found if normalize_name(item.name) == report.normalized_name
                           or any(normalize_name(alias) == report.normalized_name for alias in item.aliases)]
                if matches:
                    exact = [title for title in persist_titles(session, matches) if title.id not in excluded]
                    session.commit()
            except Exception:
                session.rollback()
        if len({title.id for title in exact}) == 1 and report.status == "open":
            report.status = "resolved"
            report.resolved_title_id = exact[0].id
            report.updated_at = utc_now()
            session.commit()
        if report.status == "resolved":
            resolved += 1
        else:
            await publish_report_operations(session, report)
            report.updated_at = utc_now()
            session.commit()
    resolved_reports = session.scalars(select(MissingTitleReport).where(
        MissingTitleReport.status == "resolved",
    ).limit(50)).all()
    for report in resolved_reports:
        title = session.get(Title, report.resolved_title_id) if report.resolved_title_id else None
        if title is None:
            continue  # Publication has not been verified in the shared catalog.
        subscribers = session.scalars(select(ReportSubscriber).where(
            ReportSubscriber.report_id == report.id, ReportSubscriber.notified_at.is_(None),
        )).all()
        for subscriber in subscribers:
            try:
                delivery = await send_publication_email(report, subscriber, title)
                if delivery:
                    subscriber.delivery_id = delivery
                    subscriber.notified_at = utc_now()
                    session.commit()
                    notified += 1
            except Exception:
                session.rollback()
        if report.github_issue_number and report.github_issue_closed_at is None:
            try:
                await close_github_issue(report)
                report.github_issue_closed_at = utc_now()
                session.commit()
            except Exception:
                session.rollback()
    return {"checked": checked, "resolved": resolved, "notified": notified}


def require_job_authorization(authorization: str | None) -> None:
    secret = os.getenv("CATALOG_JOB_TOKEN")
    if not secret:
        raise HTTPException(status_code=503, detail="Catalog jobs are not configured")
    if not authorization or not compare_digest(authorization, f"Bearer {secret}"):
        raise HTTPException(status_code=401, detail="Unauthorized")


REFRESH_LANES = (("movie", "recent"), ("tv", "recent"), ("game", "recent"),
                 ("movie", "upcoming"), ("tv", "upcoming"), ("game", "upcoming"))


@app.post("/api/internal/refresh")
async def refresh_catalog(
    session: Db,
    authorization: Annotated[str | None, Header()] = None,
    media_type: Literal["movie", "tv", "game"] | None = None,
    section: Literal["recent", "upcoming"] | None = None,
):
    """Refresh page one and one deeper page of a selected or rotating lane."""
    require_job_authorization(authorization)
    if (media_type is None) != (section is None):
        raise HTTPException(status_code=422, detail="Provide both media_type and section")
    slot = None
    if media_type is None:
        slot = session.get(CatalogRefreshCursor, "slot")
        if slot is None:
            slot = CatalogRefreshCursor(key="slot", next_page=1)
            session.add(slot)
        lane_index = (slot.next_page - 1) % len(REFRESH_LANES)
        media_type, section = REFRESH_LANES[lane_index]
    else:
        lane_index = REFRESH_LANES.index((media_type, section))
    lane_key = f"{media_type}:{section}"
    cursor = session.get(CatalogRefreshCursor, lane_key)
    if cursor is None:
        cursor = CatalogRefreshCursor(key=lane_key, next_page=2)
        session.add(cursor)
    deeper_page = max(2, cursor.next_page)
    today = datetime.now(timezone.utc).date()
    pages = (1, deeper_page)
    responses = await asyncio.gather(
        *(browse_providers(section, media_type, today, page) for page in pages),
        return_exceptions=True,
    )
    counts: dict[int, int] = {}
    warnings: list[str] = []
    for page, response in zip(pages, responses):
        if isinstance(response, asyncio.CancelledError):
            raise response
        if isinstance(response, Exception):
            warnings.append(f"{media_type} {section} page {page} unavailable")
            continue
        found, source_warnings = response
        if source_warnings:
            warnings.extend(source_warnings)
            continue
        titles = persist_titles(session, found)
        values = {
            "key": f"discover:{section}:{media_type}:{page}:{today.isoformat()}",
            "title_ids_json": json.dumps([title.id for title in titles]),
            "fetched_at": utc_now(), "result_count": len(titles),
        }
        session.execute(upsert_statement(
            SearchSnapshot, values, ["key"],
            {field: values[field] for field in ("title_ids_json", "fetched_at", "result_count")},
        ))
        counts[page] = len(titles)
        if page == deeper_page:
            cursor.next_page = page + 1 if len(found) >= 20 and page < 50 else 2
            cursor.updated_at = utc_now()
    if 1 in counts and slot is not None:
        slot.next_page = (lane_index + 1) % len(REFRESH_LANES) + 1
        slot.updated_at = utc_now()
    session.execute(delete(ProviderRateWindow).where(ProviderRateWindow.second < int(time.time()) - 86400))
    session.commit()
    if 1 not in counts:
        raise HTTPException(status_code=503, detail="Release refresh could not load the first page")
    return {"media_type": media_type, "section": section, "pages": counts,
            "next_page": cursor.next_page, "warnings": warnings}


def find_user(session: Session, clerk_user_id: str, *, create: bool) -> CatalogUser | None:
    user = session.scalar(select(CatalogUser).where(CatalogUser.clerk_user_id == clerk_user_id))
    if user or not create:
        return user
    values = {"id": uuid.uuid4().hex, "clerk_user_id": clerk_user_id, "created_at": utc_now()}
    if engine.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    session.execute(insert(CatalogUser).values(**values).on_conflict_do_nothing(index_elements=["clerk_user_id"]))
    session.flush()
    return session.scalar(select(CatalogUser).where(CatalogUser.clerk_user_id == clerk_user_id))


@app.get("/api/library", response_model=list[LibraryOut])
def list_library(session: Db, clerk_user_id: ClerkUser):
    user = find_user(session, clerk_user_id, create=False)
    if user is None:
        return []
    entries = session.scalars(select(LibraryEntry).where(LibraryEntry.user_id == user.id).order_by(LibraryEntry.updated_at.desc())).all()
    return [entry_out(entry) for entry in entries]


@app.get("/api/lists", response_model=list[CustomListOut])
def list_custom_lists(session: Db, clerk_user_id: ClerkUser):
    user = find_user(session, clerk_user_id, create=False)
    if user is None:
        return []
    lists = session.scalars(select(CustomList).where(CustomList.user_id == user.id).order_by(CustomList.name)).all()
    return [CustomListOut(id=item.id, name=item.name, count=len(item.entry_links)) for item in lists]


@app.put("/api/lists/{list_id}", response_model=CustomListOut)
def rename_custom_list(list_id: str, change: RenameList, session: Db, clerk_user_id: ClerkUser):
    user = find_user(session, clerk_user_id, create=False)
    item = session.get(CustomList, list_id)
    if user is None or item is None or item.user_id != user.id:
        raise HTTPException(status_code=404, detail="List not found")
    conflict = session.scalar(select(CustomList).where(CustomList.user_id == user.id,
                              func.lower(CustomList.name) == change.name.casefold(), CustomList.id != list_id))
    if conflict:
        raise HTTPException(status_code=409, detail="A list with that name already exists")
    if item.name != change.name:
        # List names are stored in revisions, so a rename updates the log for each affected title.
        previous = [(link.entry, entry_snapshot(link.entry)) for link in item.entry_links]
        item.name = change.name
        for entry, before in previous:
            record_revision(session, user.id, entry.title_id, before, entry_snapshot(entry))
        session.commit()
    return CustomListOut(id=item.id, name=item.name, count=len(item.entry_links))


@app.delete("/api/lists/{list_id}", status_code=204)
def delete_custom_list(list_id: str, session: Db, clerk_user_id: ClerkUser):
    user = find_user(session, clerk_user_id, create=False)
    item = session.get(CustomList, list_id)
    if user is None or item is None or item.user_id != user.id:
        raise HTTPException(status_code=404, detail="List not found")
    previous = [(link.entry, entry_snapshot(link.entry)) for link in item.entry_links]
    session.delete(item)
    session.flush()
    for entry, before in previous:
        record_revision(session, user.id, entry.title_id, before, entry_snapshot(entry))
    session.commit()


@app.put("/api/library/{title_id}", response_model=LibraryOut)
def save_to_library(title_id: str, change: TrackingUpdate, session: Db, clerk_user_id: ClerkUser):
    title = session.get(Title, title_id)
    if title is None:
        raise HTTPException(status_code=404, detail="Title is not in the shared catalog")
    user = find_user(session, clerk_user_id, create=True)
    assert user is not None
    entry = session.scalar(select(LibraryEntry).where(LibraryEntry.user_id == user.id, LibraryEntry.title_id == title.id))
    before = entry_snapshot(entry) if entry else None
    if entry is None:
        entry = LibraryEntry(user_id=user.id, title_id=title.id, status=change.status)
        session.add(entry)
        session.flush()
    entry.status = change.status
    if change.status != "completed":
        entry.completed_on = None
        entry.date_precision = "none"
    elif {"completed_on", "date_precision"} & change.model_fields_set or before is None:
        entry.completed_on = change.completed_on
        entry.date_precision = change.date_precision
    if "rating_half_steps" in change.model_fields_set:
        entry.rating_half_steps = change.rating_half_steps
    if "review" in change.model_fields_set:
        entry.review = change.review.strip() or None if change.review is not None else None
    if "favorite" in change.model_fields_set:
        entry.favorite = bool(change.favorite)
    if "platforms" in change.model_fields_set:
        if title.media_type != "game" and change.platforms:
            raise HTTPException(status_code=422, detail="Platforms apply to games only")
        entry.platforms_json = json.dumps(change.platforms or [])
    if "lists" in change.model_fields_set:
        desired = change.lists or []
        existing = {item.name.casefold(): item for item in session.scalars(
            select(CustomList).where(CustomList.user_id == user.id)).all()}
        if len(existing) + len([name for name in desired if name.casefold() not in existing]) > 50:
            raise HTTPException(status_code=422, detail="A library can have at most 50 lists")
        resolved = []
        for name in desired:
            item = existing.get(name.casefold())
            if item is None:
                item = CustomList(user_id=user.id, name=name)
                session.add(item)
                session.flush()
                existing[name.casefold()] = item
            resolved.append(item)
        entry.list_links = [EntryList(list_id=item.id) for item in resolved]
        session.flush()
    after = entry_snapshot(entry)
    if before != after:
        entry.updated_at = utc_now()
        record_revision(session, user.id, title.id, before, after)
    session.commit()
    session.refresh(entry)
    return entry_out(entry)


@app.delete("/api/library/{title_id}", status_code=204)
def remove_from_library(title_id: str, session: Db, clerk_user_id: ClerkUser):
    user = find_user(session, clerk_user_id, create=False)
    if user is None:
        return None
    entry = session.scalar(select(LibraryEntry).where(LibraryEntry.user_id == user.id, LibraryEntry.title_id == title_id))
    if entry is not None:
        record_revision(session, user.id, title_id, entry_snapshot(entry), None)
        session.delete(entry)
        session.commit()
    return None
