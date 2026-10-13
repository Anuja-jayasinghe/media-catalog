"""Public catalog search and Clerk-protected personal library."""

from __future__ import annotations

import json
import os
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import require_clerk_user
from .database import CatalogUser, LibraryEntry, SearchSnapshot, SessionLocal, Title, engine, init_database, utc_now
from .providers import ProviderSearchError, ProviderTitle, browse_providers, search_providers


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
    allow_methods=["GET", "PUT", "DELETE"],
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


class TrackingUpdate(BaseModel):
    status: Literal["planned", "in_progress", "completed", "dropped"]
    completed_on: date | None = None
    date_precision: Literal["none", "day", "month"] = "none"

    @model_validator(mode="after")
    def valid_date(self):
        if self.status != "completed" and (self.completed_on or self.date_precision != "none"):
            raise ValueError("Only completed entries can have a completion date")
        if (self.date_precision == "none") != (self.completed_on is None):
            raise ValueError("A completion date and its precision must be provided together")
        if self.date_precision == "month" and self.completed_on and self.completed_on.day != 1:
            raise ValueError("Month-only dates must use the first day of the month")
        return self


class LibraryOut(BaseModel):
    title: TitleOut
    status: str
    completed_on: date | None
    date_precision: str
    updated_at: datetime


def title_out(title: Title) -> TitleOut:
    return TitleOut.model_validate({column.name: getattr(title, column.name) for column in Title.__table__.columns})


def entry_out(entry: LibraryEntry) -> LibraryOut:
    return LibraryOut(
        title=title_out(entry.title), status=entry.status,
        completed_on=entry.completed_on, date_precision=entry.date_precision,
        updated_at=entry.updated_at,
    )


def upsert_statement(model, values: dict, constraint_columns: list[str], updates: dict):
    if engine.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    elif engine.dialect.name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:
        raise RuntimeError("Use PostgreSQL or SQLite")
    return insert(model).values(**values).on_conflict_do_update(index_elements=constraint_columns, set_=updates)


def persist_titles(session: Session, found: list[ProviderTitle]) -> list[Title]:
    for item in found:
        values = {
            "id": uuid.uuid4().hex, "provider": item.provider, "media_type": item.media_type,
            "provider_id": item.provider_id, "name": item.name, "overview": item.overview,
            "poster_url": item.poster_url, "release_date": item.release_date,
            "created_at": utc_now(), "updated_at": utc_now(),
        }
        updates = {key: values[key] for key in ("name", "overview", "poster_url", "release_date", "updated_at")}
        session.execute(upsert_statement(Title, values, ["provider", "media_type", "provider_id"], updates))
    session.flush()
    ordered = []
    for item in found:
        title = session.scalar(select(Title).where(
            Title.provider == item.provider,
            Title.media_type == item.media_type,
            Title.provider_id == item.provider_id,
        ))
        if title is not None:
            ordered.append(title)
    return ordered


def snapshot_titles(session: Session, snapshot: SearchSnapshot) -> list[Title]:
    ids = json.loads(snapshot.title_ids_json)
    by_id = {item.id: item for item in session.scalars(select(Title).where(Title.id.in_(ids))).all()} if ids else {}
    return [by_id[item_id] for item_id in ids if item_id in by_id]


@app.get("/health")
def health():
    return {"status": "ok"}


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
        return SearchOut(results=[title_out(title) for title in snapshot_titles(session, snapshot)], cached=True)

    try:
        found, warnings = await search_providers(query, media_type)
    except ProviderSearchError as error:
        if snapshot:
            return SearchOut(results=[title_out(title) for title in snapshot_titles(session, snapshot)], warnings=["Showing older results while sources are unavailable"], cached=True)
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
    return SearchOut(results=[title_out(title) for title in titles], warnings=warnings)


@app.get("/api/discover", response_model=SearchOut)
async def discover(
    session: Db,
    section: Literal["recent", "upcoming"],
    media_type: Literal["all", "movie", "tv", "game"] = "all",
):
    today = datetime.now(timezone.utc).date()
    key = f"discover:{section}:{media_type}:{today.isoformat()}"
    snapshot = session.get(SearchSnapshot, key)
    fetched_at = snapshot.fetched_at if snapshot else None
    if fetched_at and fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    if snapshot and fetched_at and datetime.now(timezone.utc) - fetched_at < timedelta(hours=6):
        return SearchOut(results=[title_out(title) for title in snapshot_titles(session, snapshot)], cached=True)

    try:
        found, warnings = await browse_providers(section, media_type, today)
    except ProviderSearchError as error:
        if snapshot:
            return SearchOut(results=[title_out(title) for title in snapshot_titles(session, snapshot)], warnings=["Showing older releases while sources are unavailable"], cached=True)
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
    return SearchOut(results=[title_out(title) for title in titles], warnings=warnings)


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


@app.put("/api/library/{title_id}", response_model=LibraryOut)
def save_to_library(title_id: str, change: TrackingUpdate, session: Db, clerk_user_id: ClerkUser):
    title = session.get(Title, title_id)
    if title is None:
        raise HTTPException(status_code=404, detail="Title is not in the shared catalog")
    user = find_user(session, clerk_user_id, create=True)
    assert user is not None
    entry = session.scalar(select(LibraryEntry).where(LibraryEntry.user_id == user.id, LibraryEntry.title_id == title.id))
    if entry is None:
        entry = LibraryEntry(user_id=user.id, title_id=title.id, status=change.status)
        session.add(entry)
    entry.status = change.status
    entry.completed_on = change.completed_on
    entry.date_precision = change.date_precision
    entry.updated_at = utc_now()
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
        session.delete(entry)
        session.commit()
    return None
