from __future__ import annotations

import asyncio
from datetime import date
from types import SimpleNamespace

import httpx
import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from catalog import main
from catalog import auth
from catalog.auth import require_clerk_user
from catalog.database import Base, CatalogUser, LibraryEntry, Title
from catalog.providers import ProviderTitle
from catalog import providers


@pytest.fixture
def client(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.sqlite3'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    def test_session():
        with session_factory() as session:
            yield session

    def test_user(request: Request):
        return request.headers.get("X-Test-User", "user-a")

    main.app.dependency_overrides[main.get_session] = test_session
    main.app.dependency_overrides[require_clerk_user] = test_user
    yield TestClient(main.app), session_factory
    main.app.dependency_overrides.clear()
    engine.dispose()


def test_unified_search_creates_shared_titles_and_reuses_snapshot(client, monkeypatch):
    http, sessions = client
    calls = 0

    async def fake_search(query, media_type):
        nonlocal calls
        calls += 1
        assert (query, media_type) == ("Dune", "all")
        return ([
            ProviderTitle("tmdb", "movie", "1", "Dune", "Desert world", None, date(2021, 10, 22)),
            ProviderTitle("tmdb", "tv", "2", "Dune: Prophecy", "Sisterhood", None, date(2024, 11, 17)),
            ProviderTitle("igdb", "game", "3", "Dune: Awakening", "Survival", None, date(2025, 6, 10)),
        ], [])

    monkeypatch.setattr(main, "search_providers", fake_search)
    first = http.get("/api/search", params={"q": "Dune"})
    assert first.status_code == 200
    assert {result["media_type"] for result in first.json()["results"]} == {"movie", "tv", "game"}
    second = http.get("/api/search", params={"q": "dune"})
    assert second.status_code == 200
    assert second.json()["cached"] is True
    assert calls == 1
    with sessions() as session:
        assert len(session.scalars(select(Title)).all()) == 3


def test_discover_reuses_snapshot_and_adds_releases_to_shared_catalog(client, monkeypatch):
    http, sessions = client
    calls = 0

    async def fake_browse(section, media_type, today, page):
        nonlocal calls
        calls += 1
        assert (section, media_type, page) == ("upcoming", "all", 1)
        return ([
            ProviderTitle("tmdb", "movie", "10", "Future Film", "", None, date(2027, 1, 1)),
            ProviderTitle("igdb", "game", "20", "Future Game", "", None, date(2027, 2, 1)),
        ], [])

    monkeypatch.setattr(main, "browse_providers", fake_browse)
    first = http.get("/api/discover", params={"section": "upcoming"})
    second = http.get("/api/discover", params={"section": "upcoming"})
    assert first.status_code == 200
    assert second.json()["cached"] is True
    assert calls == 1
    assert {item["media_type"] for item in first.json()["results"]} == {"movie", "game"}
    with sessions() as session:
        assert len(session.scalars(select(Title)).all()) == 2


def test_discover_pages_continue_until_source_runs_out(client, monkeypatch):
    http, _ = client
    calls = []

    async def fake_browse(section, media_type, today, page):
        calls.append(page)
        count = 20 if page == 1 else 5
        return ([ProviderTitle("tmdb", "movie", str((page - 1) * 20 + index), f"Film {page}-{index}", "", None, None) for index in range(count)], [])

    monkeypatch.setattr(main, "browse_providers", fake_browse)
    first = http.get("/api/discover", params={"section": "popular", "media_type": "movie", "page": 1})
    second = http.get("/api/discover", params={"section": "popular", "media_type": "movie", "page": 2})
    cached_second = http.get("/api/discover", params={"section": "popular", "media_type": "movie", "page": 2})
    assert first.json()["has_more"] is True
    assert second.json()["has_more"] is False
    assert len(second.json()["results"]) == 5
    assert cached_second.json()["cached"] is True
    assert calls == [1, 2]


def test_title_media_returns_trailer_and_external_link(client, monkeypatch):
    http, sessions = client
    with sessions() as session:
        title = Title(provider="tmdb", media_type="movie", provider_id="42", name="A film")
        session.add(title)
        session.commit()
        title_id = title.id

    async def fake_media(provider, media_type, provider_id):
        assert (provider, media_type, provider_id) == ("tmdb", "movie", "42")
        return {"trailer_url": "https://www.youtube-nocookie.com/embed/ABCDEFGHIJK", "external_url": "https://www.imdb.com/title/tt1234567/", "external_label": "IMDb"}

    monkeypatch.setattr(main, "title_media", fake_media)
    response = http.get(f"/api/titles/{title_id}/media")
    assert response.status_code == 200
    assert response.json()["external_label"] == "IMDb"
    assert http.get("/api/titles/missing/media").status_code == 404


def test_tmdb_media_without_trailer_uses_imdb_destination(monkeypatch):
    monkeypatch.setenv("TMDB_READ_TOKEN", "test-token")
    original_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json={
            "videos": {"results": [{"site": "YouTube", "type": "Teaser", "key": "ABCDEFGHIJK"}]},
            "external_ids": {"imdb_id": "tt12345678"},
        }))
        return original_client(transport=transport, *args, **kwargs)

    monkeypatch.setattr(providers.httpx, "AsyncClient", fake_client)
    media = asyncio.run(providers.title_media("tmdb", "movie", "42"))
    assert media == {
        "trailer_url": None,
        "external_url": "https://www.imdb.com/title/tt12345678/",
        "external_label": "IMDb",
    }


def test_library_is_private_and_one_entry_per_user(client):
    http, sessions = client
    with sessions() as session:
        title = Title(provider="tmdb", media_type="movie", provider_id="42", name="A film")
        session.add(title)
        session.commit()
        title_id = title.id

    saved = http.put(f"/api/library/{title_id}", json={"status": "planned"}, headers={"X-Test-User": "alice"})
    assert saved.status_code == 200
    assert saved.json()["status"] == "planned"
    assert http.get("/api/library", headers={"X-Test-User": "bob"}).json() == []
    updated = http.put(f"/api/library/{title_id}", json={"status": "completed"}, headers={"X-Test-User": "alice"})
    assert updated.status_code == 200
    assert updated.json()["date_precision"] == "none"
    assert len(http.get("/api/library", headers={"X-Test-User": "alice"}).json()) == 1
    with sessions() as session:
        assert len(session.scalars(select(CatalogUser)).all()) == 1
        assert len(session.scalars(select(LibraryEntry)).all()) == 1


def test_completion_date_validation_and_removal(client):
    http, sessions = client
    with sessions() as session:
        title = Title(provider="igdb", media_type="game", provider_id="7", name="A game")
        session.add(title)
        session.commit()
        title_id = title.id
    path = f"/api/library/{title_id}"
    invalid = http.put(path, json={"status": "planned", "completed_on": "2026-10-01", "date_precision": "day"})
    assert invalid.status_code == 422
    valid = http.put(path, json={"status": "completed", "completed_on": "2026-10-01", "date_precision": "month"})
    assert valid.status_code == 200
    assert valid.json()["completed_on"] == "2026-10-01"
    assert http.delete(path).status_code == 204
    assert http.get("/api/library").json() == []


def test_unknown_title_cannot_be_saved(client):
    http, _ = client
    response = http.put("/api/library/missing", json={"status": "planned"})
    assert response.status_code == 404


def test_library_fails_closed_without_clerk_configuration(monkeypatch):
    monkeypatch.delenv("CLERK_SECRET_KEY", raising=False)
    main.app.dependency_overrides.clear()
    response = TestClient(main.app).get("/api/library")
    assert response.status_code == 503


def test_clerk_verification_uses_session_subject(monkeypatch):
    monkeypatch.setenv("CLERK_SECRET_KEY", "test-secret")
    monkeypatch.setenv("CLERK_AUTHORIZED_PARTIES", "http://localhost:3000")
    captured = {}

    def fake_authenticate(request, options):
        captured["options"] = options
        return SimpleNamespace(is_signed_in=True, payload={"sub": "user_123"})

    monkeypatch.setattr(
        auth, "authenticate_request",
        fake_authenticate,
    )
    request = Request({"type": "http", "method": "GET", "path": "/api/library", "headers": []})
    assert require_clerk_user(request) == "user_123"
    assert captured["options"].authorized_parties == ["http://localhost:3000"]
    assert captured["options"].accepts_token == ["session_token"]
