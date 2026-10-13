from __future__ import annotations

import asyncio
from datetime import date
from types import SimpleNamespace

import httpx
import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from catalog import main, database
from catalog import auth
from catalog.auth import require_clerk_user
from catalog.database import Base, CatalogUser, LibraryEntry, MissingTitleReport, ReportSubscriber, Title, TitleAlias, TitleIdentity
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


def test_readiness_checks_database_without_exposing_connection_details(client):
    http, _ = client
    assert http.get("/health/ready").json() == {"status": "ready"}

    class UnavailableSession:
        def execute(self, _statement):
            raise SQLAlchemyError("private connection details")

    def unavailable_session():
        yield UnavailableSession()

    main.app.dependency_overrides[main.get_session] = unavailable_session
    response = http.get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {"detail": "Catalog database is unavailable"}


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


def test_exact_external_identity_joins_sources_without_merging_same_name(client):
    _, sessions = client
    with sessions() as session:
        tvmaze = ProviderTitle("tvmaze", "tv", "12", "The Return", "", None, None,
                               external_ids=(("imdb", "tt1234567"),))
        tmdb = ProviderTitle("tmdb", "tv", "98", "Return, The", "", None, None,
                             external_ids=(("imdb", "tt1234567"),))
        first = main.persist_titles(session, [tvmaze])[0]
        canonical_id = first.id
        merged = main.persist_titles(session, [tmdb])[0]
        assert merged.id == canonical_id
        assert merged.provider == "tmdb"
        unrelated = main.persist_titles(session, [ProviderTitle("tmdb", "tv", "99", "The Return", "", None, None)])[0]
        assert unrelated.id != canonical_id
        session.commit()
        aliases = {item.value for item in session.scalars(select(TitleAlias).where(TitleAlias.title_id == canonical_id))}
        assert {"The Return", "Return, The"} <= aliases
        assert len(session.scalars(select(TitleIdentity)).all()) == 4


def test_alias_search_survives_provider_outage(client, monkeypatch):
    http, sessions = client
    with sessions() as session:
        main.persist_titles(session, [ProviderTitle("tmdb", "movie", "7", "Amélie", "", None, None,
                                                   aliases=("Le Fabuleux Destin d’Amélie Poulain",))])
        session.commit()

    async def unavailable(*_):
        raise providers.ProviderSearchError("offline")

    monkeypatch.setattr(main, "search_providers", unavailable)
    result = http.get("/api/search", params={"q": "Le Fabuleux"})
    assert result.status_code == 200
    assert result.json()["results"][0]["name"] == "Amélie"


def test_newly_published_title_appears_during_search_snapshot(client, monkeypatch):
    http, sessions = client

    async def empty_search(*_):
        return [], []

    monkeypatch.setattr(main, "search_providers", empty_search)
    first = http.get("/api/search", params={"q": "Hidden Film", "media_type": "movie"})
    assert first.json()["results"] == []
    with sessions() as session:
        main.persist_titles(session, [ProviderTitle("tmdb", "movie", "91", "Hidden Film", "", None, None)])
        session.commit()
    second = http.get("/api/search", params={"q": "Hidden Film", "media_type": "movie"})
    assert second.json()["cached"] is True
    assert [title["name"] for title in second.json()["results"]] == ["Hidden Film"]


def test_missing_report_is_deduped_and_email_stays_private(client, monkeypatch):
    http, sessions = client

    async def empty_search(*_):
        return [], []

    async def fake_issue(report):
        assert not hasattr(report, "email")
        return 17, "https://github.com/example/catalog/issues/17"

    monkeypatch.setattr(main, "search_providers", empty_search)
    monkeypatch.setattr(main, "create_github_issue", fake_issue)
    one = http.post("/api/missing-titles", json={"name": "Lost Film", "media_type": "movie", "email": "a@example.com"})
    two = http.post("/api/missing-titles", json={"name": "lost-film", "media_type": "movie", "email": "b@example.com"})
    assert one.status_code == two.status_code == 200
    assert one.json()["report_id"] == two.json()["report_id"]
    assert "email" not in str(one.json())
    with sessions() as session:
        assert len(session.scalars(select(MissingTitleReport)).all()) == 1
        assert {item.email for item in session.scalars(select(ReportSubscriber))} == {"a@example.com", "b@example.com"}


def test_ambiguous_name_offers_choices_before_reporting(client, monkeypatch):
    http, sessions = client

    async def two_titles(*_):
        return [
            ProviderTitle("igdb", "game", "10", "Hades", "", None, date(2018, 12, 6)),
            ProviderTitle("igdb", "game", "11", "Hades", "", None, date(2020, 9, 17)),
        ], []

    monkeypatch.setattr(main, "search_providers", two_titles)
    result = http.post("/api/missing-titles", json={"name": "Hades", "media_type": "game"})
    assert result.status_code == 200
    assert result.json()["status"] == "choices"
    assert len(result.json()["choices"]) == 2
    with sessions() as session:
        assert session.scalars(select(MissingTitleReport)).all() == []
    forced = http.post("/api/missing-titles", json={"name": "Hades", "media_type": "game", "force_report": True})
    assert forced.json()["status"] == "reported"


def test_reconcile_notifies_once_after_public_title_exists(client, monkeypatch):
    http, sessions = client
    sent = []

    async def empty_search(*_):
        return [], []

    async def found_search(*_):
        return [ProviderTitle("tmdb", "movie", "24", "Hidden Film", "", None, None)], []

    async def fake_email(report, subscriber, title):
        sent.append((subscriber.email, title.id))
        return "delivery-1"

    monkeypatch.setattr(main, "search_providers", empty_search)
    monkeypatch.setattr(main, "send_publication_email", fake_email)
    response = http.post("/api/missing-titles", json={"name": "Hidden Film", "media_type": "movie", "email": "watcher@example.com"})
    assert response.json()["status"] == "reported"
    monkeypatch.setattr(main, "search_providers", found_search)
    monkeypatch.setenv("CATALOG_JOB_TOKEN", "test-job-token")
    assert http.post("/api/internal/reconcile").status_code == 401
    headers = {"Authorization": "Bearer test-job-token"}
    first = http.post("/api/internal/reconcile", headers=headers)
    second = http.post("/api/internal/reconcile", headers=headers)
    assert first.status_code == second.status_code == 200
    assert first.json()["resolved"] == 1
    assert len(sent) == 1
    with sessions() as session:
        report = session.scalar(select(MissingTitleReport))
        assert report.status == "resolved"
        assert http.get(f"/api/titles/{report.resolved_title_id}").status_code == 200
        assert session.scalar(select(ReportSubscriber)).notified_at is not None


def test_tvmaze_fallback_when_tmdb_has_no_close_series(monkeypatch):
    monkeypatch.setenv("TMDB_READ_TOKEN", "test-token")
    original_client = httpx.AsyncClient
    calls = []

    def respond(request):
        calls.append(str(request.url))
        if request.url.host == "api.themoviedb.org":
            return httpx.Response(200, json={"results": [], "total_pages": 1})
        if request.url.host == "api.tvmaze.com":
            return httpx.Response(200, json=[{"score": 0.9, "show": {
                "id": 55, "name": "Rare Series", "summary": "<p>A small show.</p>",
                "premiered": "2025-02-01", "image": None,
                "externals": {"imdb": "tt1234567"},
            }}])
        return httpx.Response(404)

    def fake_client(*args, **kwargs):
        return original_client(transport=httpx.MockTransport(respond), *args, **kwargs)

    monkeypatch.setattr(providers.httpx, "AsyncClient", fake_client)
    titles, warnings = asyncio.run(providers.search_providers("Rare Series", "tv"))
    assert warnings == []
    assert len(titles) == 1
    assert titles[0].provider == "tvmaze"
    assert titles[0].external_ids == (("imdb", "tt1234567"),)
    assert titles[0].overview == "A small show."
    assert any("tvmaze.com" in url for url in calls)


def test_existing_report_table_gets_additive_columns(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.sqlite3'}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE missing_title_reports (id VARCHAR(32) PRIMARY KEY, media_type VARCHAR(8), name VARCHAR(500), normalized_name VARCHAR(500), status VARCHAR(16), resolved_title_id VARCHAR(32), github_issue_number INTEGER, github_issue_url TEXT, created_at DATETIME, updated_at DATETIME)")
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    database.init_database()
    columns = {column["name"] for column in inspect(engine).get_columns("missing_title_reports")}
    assert {"github_issue_closed_at", "admin_notified_at"} <= columns
    engine.dispose()
