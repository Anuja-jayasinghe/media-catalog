from __future__ import annotations

import asyncio
import json
import csv
import io
from datetime import date, timedelta
from types import SimpleNamespace

import httpx
import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from catalog import main, database, limits
from catalog import auth
from catalog.auth import require_clerk_user
from catalog.database import Base, CatalogRefreshCursor, CatalogUser, CustomList, EntryRevision, ImportBatch, ImportChange, LibraryEntry, MissingTitleReport, ProviderRateWindow, ReportSubscriber, SearchSnapshot, SeasonProgress, ShareLink, Title, TitleAlias, TitleIdentity
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


def test_catalog_page_persistence_uses_bounded_database_reads(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'batch.sqlite3'}")
    Base.metadata.create_all(engine)
    titles = [ProviderTitle("igdb", "game", str(index), f"Game {index}", "", None, None)
              for index in range(20)]
    reads = 0

    def count_reads(_connection, _cursor, statement, _parameters, _context, _executemany):
        nonlocal reads
        if statement.lstrip().upper().startswith("SELECT"):
            reads += 1

    event.listen(engine, "before_cursor_execute", count_reads)
    with sessionmaker(bind=engine)() as session:
        main.persist_titles(session, titles)
        session.commit()
    assert reads <= 6

    reads = 0
    with sessionmaker(bind=engine)() as session:
        main.persist_titles(session, titles)
        session.commit()
    assert reads <= 8
    engine.dispose()


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


def test_shared_provider_budget_is_atomic_and_resets_next_second(tmp_path, monkeypatch):
    test_engine = create_engine(f"sqlite:///{tmp_path / 'budget.sqlite3'}")
    Base.metadata.create_all(test_engine)
    monkeypatch.setattr(limits, "engine", test_engine)
    monkeypatch.setattr(limits, "SessionLocal", sessionmaker(bind=test_engine))
    limits.reserve_provider_call("igdb", second=100)
    limits.reserve_provider_call("igdb", second=100)
    with pytest.raises(limits.ProviderRateLimited):
        limits.reserve_provider_call("igdb", second=100)
    limits.reserve_provider_call("igdb", second=101)
    with limits.SessionLocal() as session:
        assert [(row.second, row.used) for row in session.scalars(
            select(ProviderRateWindow).order_by(ProviderRateWindow.second)
        )] == [(100, 2), (101, 1)]
    test_engine.dispose()


def test_refresh_rotates_lanes_and_updates_released_dates(client, monkeypatch):
    http, sessions = client
    monkeypatch.setenv("CATALOG_JOB_TOKEN", "test-job-token")
    calls = []
    release_date = date(2027, 1, 1)

    async def fake_browse(section, media_type, today, page):
        calls.append((section, media_type, page))
        if page == 1:
            provider = "igdb" if media_type == "game" else "tmdb"
            return ([ProviderTitle(provider, media_type, "42", "Changing release", "", None, release_date)], [])
        return ([], [])

    monkeypatch.setattr(main, "browse_providers", fake_browse)
    assert http.post("/api/internal/refresh").status_code == 401
    headers = {"Authorization": "Bearer test-job-token"}
    first = http.post("/api/internal/refresh", headers=headers)
    assert first.status_code == 200
    assert first.json()["media_type"] == "movie"
    assert first.json()["pages"] == {"1": 1, "2": 0}
    with sessions() as session:
        movie = session.scalar(select(Title).where(Title.media_type == "movie"))
        assert movie.release_date == release_date
        assert session.get(SearchSnapshot, f"discover:recent:movie:1:{date.today().isoformat()}") is not None
        assert session.get(CatalogRefreshCursor, "slot").next_page == 2

    second = http.post("/api/internal/refresh", headers=headers)
    assert second.status_code == 200
    assert second.json()["media_type"] == "tv"
    assert calls == [("recent", "movie", 1), ("recent", "movie", 2),
                     ("recent", "tv", 1), ("recent", "tv", 2)]
    for _ in range(4):
        assert http.post("/api/internal/refresh", headers=headers).status_code == 200
    release_date = date(2027, 2, 1)
    seventh = http.post("/api/internal/refresh", headers=headers)
    assert seventh.json()["media_type"] == "movie"
    with sessions() as session:
        movies = session.scalars(select(Title).where(Title.media_type == "movie")).all()
        assert len(movies) == 1
        assert movies[0].release_date == release_date


def test_refresh_retries_lane_after_first_page_fails(client, monkeypatch):
    http, sessions = client
    monkeypatch.setenv("CATALOG_JOB_TOKEN", "test-job-token")

    async def fake_browse(_section, _media_type, _today, page):
        if page == 1:
            raise providers.ProviderSearchError("source unavailable")
        return ([], [])

    monkeypatch.setattr(main, "browse_providers", fake_browse)
    response = http.post("/api/internal/refresh", headers={"Authorization": "Bearer test-job-token"})
    assert response.status_code == 503
    with sessions() as session:
        assert session.get(CatalogRefreshCursor, "slot").next_page == 1


def test_refresh_accepts_explicit_lane_without_advancing_rotation(client, monkeypatch):
    http, sessions = client
    monkeypatch.setenv("CATALOG_JOB_TOKEN", "test-job-token")
    calls = []

    async def fake_browse(section, media_type, _today, page):
        calls.append((section, media_type, page))
        return ([], [])

    monkeypatch.setattr(main, "browse_providers", fake_browse)
    headers = {"Authorization": "Bearer test-job-token"}
    assert http.post("/api/internal/refresh?media_type=game", headers=headers).status_code == 422
    response = http.post("/api/internal/refresh?media_type=game&section=upcoming", headers=headers)
    assert response.status_code == 200
    assert response.json()["media_type"] == "game"
    assert calls == [("upcoming", "game", 1), ("upcoming", "game", 2)]
    with sessions() as session:
        assert session.get(CatalogRefreshCursor, "slot") is None


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
    monkeypatch.setattr(providers, "reserve_provider_call", lambda _provider: None)
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


def test_library_details_lists_and_revision_history_are_private(client):
    http, sessions = client
    with sessions() as session:
        game = Title(provider="igdb", media_type="game", provider_id="77", name="Example game")
        session.add(game)
        session.commit()
        title_id = game.id
    path = f"/api/library/{title_id}"
    alice = {"X-Test-User": "alice"}
    bob = {"X-Test-User": "bob"}
    saved = http.put(path, headers=alice, json={"status": "completed", "rating_half_steps": 9,
        "review": "  Worth replaying  ", "favorite": True, "platforms": ["PC", "Switch"],
        "lists": ["Favorites", "Co-op"]})
    assert saved.status_code == 200
    assert saved.json()["review"] == "Worth replaying"
    assert saved.json()["lists"] == ["Co-op", "Favorites"]
    assert http.put(path, headers=alice, json={"status": "completed", "lists": ["Favorites", "Co-op"]}).status_code == 200
    assert http.get("/api/library", headers=bob).json() == []
    assert http.get("/api/lists", headers=bob).json() == []
    assert http.get("/api/lists", headers=alice).json()[0]["count"] == 1
    # Status-only updates from existing clients must preserve optional details.
    changed = http.put(path, headers=alice, json={"status": "dropped"})
    assert changed.json()["rating_half_steps"] == 9
    assert changed.json()["platforms"] == ["PC", "Switch"]
    assert changed.json()["favorite"] is True
    first_list = http.get("/api/lists", headers=alice).json()[0]
    assert http.put(f"/api/lists/{first_list['id']}", headers=bob, json={"name": "Private"}).status_code == 404
    assert http.put(f"/api/lists/{first_list['id']}", headers=alice, json={"name": "Together"}).status_code == 200
    with sessions() as session:
        revisions = session.scalars(select(EntryRevision).order_by(EntryRevision.created_at)).all()
        assert len(revisions) == 3
        assert json.loads(revisions[-1].after_json)["lists"] == ["Favorites", "Together"]
    assert http.delete(path, headers=alice).status_code == 204
    with sessions() as session:
        assert len(session.scalars(select(EntryRevision)).all()) == 4
        assert len(session.scalars(select(CustomList)).all()) == 2


def test_library_details_reject_invalid_values(client):
    http, sessions = client
    with sessions() as session:
        movie = Title(provider="tmdb", media_type="movie", provider_id="88", name="Example movie")
        session.add(movie)
        session.commit()
        title_id = movie.id
    path = f"/api/library/{title_id}"
    for change in ({"rating_half_steps": 11}, {"lists": ["Same", "same"]},
                   {"platforms": ["PC"]}, {"review": "a" * 10001}):
        response = http.put(path, json={"status": "completed", **change})
        assert response.status_code == 422


def test_tv_progress_uses_dashboard_mark_time_and_keeps_future_episodes_unwatched(client, monkeypatch):
    http, sessions = client
    with sessions() as session:
        show = Title(provider="tmdb", media_type="tv", provider_id="55", name="Example show")
        session.add(show)
        session.commit()
        title_id = show.id
    today = database.utc_now().date()
    episodes = [
        {"number": 1, "name": "Pilot", "air_date": today - timedelta(days=30)},
        {"number": 2, "name": "Second", "air_date": today - timedelta(days=1)},
        {"number": 3, "name": "Coming soon", "air_date": today + timedelta(days=30)},
        {"number": 4, "name": "Date unknown", "air_date": None},
    ]
    async def fake_seasons(*_):
        return [{"number": 1, "name": "Season 1", "episode_count": 4}]
    async def fake_episodes(*_):
        return episodes
    monkeypatch.setattr(main, "tv_seasons", fake_seasons)
    monkeypatch.setattr(main, "tv_episodes", fake_episodes)
    path = f"/api/library/{title_id}/seasons/1"
    alice = {"X-Test-User": "alice"}
    bob = {"X-Test-User": "bob"}
    assert http.get(f"/api/library/{title_id}/seasons", headers=alice).json()[0]["marked_at"] is None
    partial = http.put(path, headers=alice, json={"through_episode": 1})
    assert partial.status_code == 200
    assert [item["watched"] for item in partial.json()] == [True, False, False, False]
    assert all(not item["watched"] for item in http.get(path, headers=bob).json())
    assert http.put(path, headers=alice, json={"through_episode": 3}).status_code == 422
    full = http.put(path, headers=alice, json={})
    assert [item["watched"] for item in full.json()] == [True, True, False, False]
    assert http.get("/api/library", headers=alice).json()[0]["status"] == "in_progress"
    assert http.delete(path, headers=alice).status_code == 204
    assert all(not item["watched"] for item in http.get(path, headers=alice).json())
    with sessions() as session:
        assert session.scalars(select(SeasonProgress)).all() == []
        assert len(session.scalars(select(EntryRevision).where(EntryRevision.source == "season")).all()) == 3


def test_share_links_expire_revoke_and_never_publish_private_reviews(client):
    http, sessions = client
    with sessions() as session:
        title = Title(provider="tmdb", media_type="movie", provider_id="99", name="A private favorite")
        session.add(title)
        session.commit()
        title_id = title.id
    alice = {"X-Test-User": "alice"}
    bob = {"X-Test-User": "bob"}
    assert http.put(f"/api/library/{title_id}", headers=alice, json={"status": "completed", "rating_half_steps": 10,
        "review": "Do not publish this", "lists": ["Watch together"]}).status_code == 200
    assert http.put("/api/profile", headers=alice, json={"display_name": "Alice's movies"}).status_code == 200
    assert http.post("/api/shares", headers=alice, json={"days": 15}).status_code == 422
    created = http.post("/api/shares", headers=alice, json={"days": 14})
    assert created.status_code == 201
    token = created.json()["token"]
    assert len(token) >= 32
    public = http.get(f"/api/public/shares/{token}")
    assert public.status_code == 200
    assert public.json()["display_name"] == "Alice's movies"
    assert public.json()["entries"][0]["lists"] == ["Watch together"]
    assert "review" not in json.dumps(public.json())
    share_id = created.json()["id"]
    assert http.delete(f"/api/shares/{share_id}", headers=bob).status_code == 404
    assert http.delete(f"/api/shares/{share_id}", headers=alice).status_code == 204
    assert http.get(f"/api/public/shares/{token}").status_code == 404
    expired = http.post("/api/shares", headers=alice, json={"days": 1}).json()
    with sessions() as session:
        share = session.get(ShareLink, expired["id"])
        share.expires_at = database.utc_now() - timedelta(seconds=1)
        session.commit()
    assert http.get(f"/api/public/shares/{expired['token']}").status_code == 404


def test_account_deletion_erases_private_catalog_after_clerk_succeeds(client, monkeypatch):
    http, sessions = client
    with sessions() as session:
        title = Title(provider="igdb", media_type="game", provider_id="100", name="A game")
        session.add(title)
        session.commit()
        title_id = title.id
    assert http.put(f"/api/library/{title_id}", headers={"X-Test-User": "alice"},
        json={"status": "completed", "lists": ["Old games"]}).status_code == 200
    assert http.post("/api/shares", headers={"X-Test-User": "alice"}, json={"days": 1}).status_code == 201
    assert http.put(f"/api/library/{title_id}", headers={"X-Test-User": "bob"}, json={"status": "planned"}).status_code == 200
    backup = http.get("/api/export/backup", headers={"X-Test-User": "alice"}).json()
    backup["entries"][0]["rating_half_steps"] = 8
    assert http.post("/api/imports/backup", headers={"X-Test-User": "alice"}, json=backup).status_code == 200
    deleted = []
    async def fake_delete(clerk_id):
        deleted.append(clerk_id)
    monkeypatch.setattr(main, "delete_clerk_user", fake_delete)
    assert http.delete("/api/account", headers={"X-Test-User": "alice"}).status_code == 204
    assert deleted == ["alice"]
    with sessions() as session:
        assert [user.clerk_user_id for user in session.scalars(select(CatalogUser)).all()] == ["bob"]
        assert len(session.scalars(select(LibraryEntry)).all()) == 1
        assert session.scalars(select(CustomList)).all() == []
        assert session.scalars(select(ShareLink)).all() == []
        assert len(session.scalars(select(EntryRevision)).all()) == 1
        assert session.scalars(select(ImportBatch)).all() == []
        assert session.scalars(select(ImportChange)).all() == []


def test_native_backup_preserves_private_fields_and_csv_is_portable(client):
    http, sessions = client
    with sessions() as session:
        title = Title(provider="tmdb", media_type="movie", provider_id="200", name="=FORMULA")
        session.add(title)
        session.commit()
        title_id = title.id
    alice = {"X-Test-User": "alice"}
    assert http.put(f"/api/library/{title_id}", headers=alice, json={"status": "completed",
        "rating_half_steps": 7, "review": "=HYPERLINK(\"bad\")", "favorite": True,
        "lists": ["Worth keeping"]}).status_code == 200
    backup = http.get("/api/export/backup", headers=alice)
    assert backup.status_code == 200
    assert backup.headers["cache-control"] == "no-store"
    assert backup.json()["format"] == "media-catalog-backup"
    assert backup.json()["entries"][0]["review"] == '=HYPERLINK("bad")'
    assert backup.json()["entries"][0]["rating_half_steps"] == 7
    assert backup.json()["lists"] == ["Worth keeping"]
    assert http.get("/api/export/backup", headers={"X-Test-User": "bob"}).json()["entries"] == []
    rows = list(csv.DictReader(io.StringIO(http.get("/api/export/csv", headers=alice).text)))
    assert rows[0]["title"] == "'=FORMULA"
    assert rows[0]["review"] == "'=HYPERLINK(\"bad\")"
    assert rows[0]["rating_5"] == "3.5"


def test_native_backup_restores_fields_and_reverts_a_batch(client):
    http, sessions = client
    with sessions() as session:
        title = Title(provider="tmdb", media_type="movie", provider_id="211", name="Restore this")
        session.add(title)
        session.commit()
        title_id = title.id
    alice = {"X-Test-User": "alice"}
    bob = {"X-Test-User": "bob"}
    assert http.put(f"/api/library/{title_id}", headers=alice, json={"status": "completed",
        "completed_on": "2020-01-01", "date_precision": "month", "rating_half_steps": 8,
        "review": "A note", "favorite": True, "lists": ["Classics"]}).status_code == 200
    backup = http.get("/api/export/backup", headers=alice).json()
    result = http.post("/api/imports/backup", headers=bob, json=backup)
    assert result.status_code == 200, result.text
    assert result.json()["created"] == 1
    assert result.json()["provisional"] == 0
    restored = http.get("/api/library", headers=bob).json()[0]
    assert restored["review"] == "A note"
    assert restored["lists"] == ["Classics"]
    assert restored["completed_on"] == "2020-01-01"
    batch_id = result.json()["batch_id"]
    assert http.get("/api/imports", headers=bob).json()[0]["id"] == batch_id
    reverted = http.post(f"/api/imports/{batch_id}/revert", headers=bob)
    assert reverted.json()["skipped_changed_since_import"] == 0
    assert http.get("/api/library", headers=bob).json() == []
    assert http.get("/api/lists", headers=bob).json() == []
    assert len(http.get("/api/library", headers=alice).json()) == 1


def test_unverified_backup_title_is_private_to_library_until_provider_confirms(client, monkeypatch):
    http, sessions = client
    backup = {"format": "media-catalog-backup", "version": 1, "profile": {"display_name": "Collector"},
        "lists": [], "entries": [{"title": {"id": "old-id", "provider": "tmdb", "provider_id": "99999",
        "media_type": "movie", "name": "A restored film", "overview": "", "poster_url": None,
        "release_date": None}, "status": "completed", "rating_half_steps": 7,
        "review": "Still private", "favorite": False, "platforms": [], "lists": []}],
        "season_progress": []}
    imported = http.post("/api/imports/backup", json=backup)
    assert imported.status_code == 200, imported.text
    assert imported.json()["provisional"] == 1
    entry = http.get("/api/library").json()[0]
    assert entry["title"]["verified"] is False
    title_id = entry["title"]["id"]
    assert http.get(f"/api/titles/{title_id}").status_code == 404
    with sessions() as session:
        assert main.local_search(session, "A restored film", "movie") == []
    with sessions() as session:
        main.persist_titles(session, [ProviderTitle("tmdb", "movie", "99999", "A restored film", "Official", None, None)])
        session.commit()
    assert http.get(f"/api/titles/{title_id}").json()["verified"] is True
    assert http.get("/api/library").json()[0]["review"] == "Still private"
    with sessions() as session:
        assert len(session.scalars(select(Title)).all()) == 1


def test_import_revert_skips_items_changed_after_import(client):
    http, sessions = client
    with sessions() as session:
        title = Title(provider="igdb", media_type="game", provider_id="502", name="Keep newer edit")
        session.add(title)
        session.commit()
        title_id = title.id
    backup = {"format": "media-catalog-backup", "version": 1,
        "entries": [{"title": {"id": title_id, "provider": "igdb", "provider_id": "502",
        "media_type": "game", "name": "Keep newer edit", "overview": "", "poster_url": None,
        "release_date": None}, "status": "planned", "lists": []}]}
    batch = http.post("/api/imports/backup", json=backup).json()["batch_id"]
    assert http.put(f"/api/library/{title_id}", json={"status": "completed"}).status_code == 200
    result = http.post(f"/api/imports/{batch}/revert")
    assert result.json()["skipped_changed_since_import"] == 1
    assert http.get("/api/library").json()[0]["status"] == "completed"


def test_native_backup_restores_tv_cutoff_and_can_revert_one_change(client, monkeypatch):
    http, sessions = client
    with sessions() as session:
        show = Title(provider="tmdb", media_type="tv", provider_id="603", name="Seasonal show")
        session.add(show)
        session.commit()
        title_id = show.id
    today = database.utc_now().date()
    async def episodes(*_):
        return [{"number": 1, "name": "Aired", "air_date": today - timedelta(days=2)},
                {"number": 2, "name": "Future", "air_date": today + timedelta(days=2)}]
    monkeypatch.setattr(main, "tv_episodes", episodes)
    path = f"/api/library/{title_id}/seasons/1"
    alice = {"X-Test-User": "alice"}
    bob = {"X-Test-User": "bob"}
    assert http.put(path, headers=alice, json={}).status_code == 200
    backup = http.get("/api/export/backup", headers=alice).json()
    imported = http.post("/api/imports/backup", headers=bob, json=backup).json()
    assert imported.get("season_marks") == 1, imported
    assert [item["watched"] for item in http.get(path, headers=bob).json()] == [True, False]
    changes = http.get(f"/api/imports/{imported['batch_id']}/changes", headers=bob).json()
    season_change = next(item for item in changes if item["kind"] == "season")
    assert http.post(f"/api/imports/{imported['batch_id']}/changes/{season_change['id']}/revert",
                     headers=bob).status_code == 200
    assert [item["watched"] for item in http.get(path, headers=bob).json()] == [False, False]
    assert len(http.get("/api/library", headers=bob).json()) == 1


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
    browse_calls = []

    async def empty_browse(section, media_type, _today, page):
        browse_calls.append((section, media_type, page))
        return [], []

    async def empty_search(*_):
        return [], []

    async def fake_issue(report):
        assert not hasattr(report, "email")
        return 17, "https://github.com/example/catalog/issues/17"

    monkeypatch.setattr(main, "search_providers", empty_search)
    monkeypatch.setattr(main, "browse_providers", empty_browse)
    monkeypatch.setattr(main, "create_github_issue", fake_issue)
    one = http.post("/api/missing-titles", json={"name": "Lost Film", "media_type": "movie", "email": "a@example.com"})
    two = http.post("/api/missing-titles", json={"name": "lost-film", "media_type": "movie", "email": "b@example.com"})
    assert one.status_code == two.status_code == 200
    assert one.json()["report_id"] == two.json()["report_id"]
    assert "email" not in str(one.json())
    assert browse_calls == [("recent", "movie", 1), ("upcoming", "movie", 1)]
    with sessions() as session:
        assert len(session.scalars(select(MissingTitleReport)).all()) == 1
        assert {item.email for item in session.scalars(select(ReportSubscriber))} == {"a@example.com", "b@example.com"}


def test_missing_title_refresh_finds_release_before_other_methods(client, monkeypatch):
    http, sessions = client
    calls = []

    async def fake_browse(section, media_type, _today, page):
        calls.append(("browse", section, media_type, page))
        if section == "recent":
            return [ProviderTitle("tmdb", "movie", "91", "New Film", "", None, date(2026, 10, 1))], []
        return [], []

    async def unexpected_search(*_):
        raise AssertionError("provider search should not run after freshness finds the title")

    monkeypatch.setattr(main, "browse_providers", fake_browse)
    monkeypatch.setattr(main, "search_providers", unexpected_search)
    response = http.post("/api/missing-titles", json={"name": "New Film", "media_type": "movie"})
    assert response.status_code == 200
    assert response.json()["status"] == "found"
    assert calls == [("browse", "recent", "movie", 1), ("browse", "upcoming", "movie", 1)]
    with sessions() as session:
        assert len(session.scalars(select(Title)).all()) == 1
        assert session.scalars(select(MissingTitleReport)).all() == []


def test_missing_title_search_runs_after_empty_release_refresh(client, monkeypatch):
    http, _ = client
    calls = []

    async def empty_browse(section, _media_type, _today, _page):
        calls.append(section)
        return [], []

    async def found_search(*_):
        calls.append("search")
        return [ProviderTitle("igdb", "game", "77", "Lost Game", "", None, None)], []

    monkeypatch.setattr(main, "browse_providers", empty_browse)
    monkeypatch.setattr(main, "search_providers", found_search)
    response = http.post("/api/missing-titles", json={"name": "Lost Game", "media_type": "game"})
    assert response.json()["status"] == "found"
    assert calls == ["recent", "upcoming", "search"]


def test_missing_title_search_still_runs_when_refresh_is_unavailable(client, monkeypatch):
    http, _ = client
    calls = []

    async def unavailable_browse(section, *_):
        calls.append(section)
        raise providers.ProviderSearchError("release feed unavailable")

    async def found_search(*_):
        calls.append("search")
        return [ProviderTitle("tmdb", "tv", "83", "Lost Show", "", None, None)], []

    monkeypatch.setattr(main, "browse_providers", unavailable_browse)
    monkeypatch.setattr(main, "search_providers", found_search)
    response = http.post("/api/missing-titles", json={"name": "Lost Show", "media_type": "tv"})
    assert response.json()["status"] == "found"
    assert calls == ["recent", "upcoming", "search"]


def test_ambiguous_name_offers_choices_before_reporting(client, monkeypatch):
    http, sessions = client

    async def two_titles(*_):
        return [
            ProviderTitle("igdb", "game", "10", "Hades", "", None, date(2018, 12, 6)),
            ProviderTitle("igdb", "game", "11", "Hades", "", None, date(2020, 9, 17)),
        ], []

    async def empty_browse(*_):
        return [], []

    monkeypatch.setattr(main, "search_providers", two_titles)
    monkeypatch.setattr(main, "browse_providers", empty_browse)
    result = http.post("/api/missing-titles", json={"name": "Hades", "media_type": "game"})
    assert result.status_code == 200
    assert result.json()["status"] == "choices"
    assert len(result.json()["choices"]) == 2
    with sessions() as session:
        assert session.scalars(select(MissingTitleReport)).all() == []
    forced = http.post("/api/missing-titles", json={"name": "Hades", "media_type": "game", "force_report": True})
    assert forced.json()["status"] == "reported"
    with sessions() as session:
        report = session.scalar(select(MissingTitleReport))
        assert len(json.loads(report.excluded_title_ids_json)) == 2


def test_rejected_match_does_not_resolve_missing_report(client, monkeypatch):
    http, sessions = client
    with sessions() as session:
        main.persist_titles(session, [ProviderTitle("tmdb", "movie", "1", "The Return", "", None, None)])
        session.commit()

    async def empty_browse(*_):
        return [], []

    async def old_match(*_):
        return [ProviderTitle("tmdb", "movie", "1", "The Return", "", None, None)], []

    monkeypatch.setattr(main, "browse_providers", empty_browse)
    monkeypatch.setattr(main, "search_providers", old_match)
    response = http.post("/api/missing-titles", json={"name": "The Return", "media_type": "movie", "force_report": True})
    assert response.json()["status"] == "reported"
    monkeypatch.setenv("CATALOG_JOB_TOKEN", "test-job-token")
    result = http.post("/api/internal/reconcile", headers={"Authorization": "Bearer test-job-token"})
    assert result.json()["resolved"] == 0
    with sessions() as session:
        assert session.scalar(select(MissingTitleReport)).status == "open"

    with sessions() as session:
        main.persist_titles(session, [ProviderTitle("tmdb", "movie", "2", "The Return", "", None, None)])
        session.commit()
        report = session.scalar(select(MissingTitleReport))
        assert report.status == "resolved"
        assert report.resolved_title_id != next(iter(json.loads(report.excluded_title_ids_json)))


def test_reconcile_notifies_once_after_public_title_exists(client, monkeypatch):
    http, sessions = client
    sent = []

    async def empty_search(*_):
        return [], []

    async def empty_browse(*_):
        return [], []

    async def found_search(*_):
        return [ProviderTitle("tmdb", "movie", "24", "Hidden Film", "", None, None)], []

    async def fake_email(report, subscriber, title):
        sent.append((subscriber.email, title.id))
        return "delivery-1"

    monkeypatch.setattr(main, "search_providers", empty_search)
    monkeypatch.setattr(main, "browse_providers", empty_browse)
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
    monkeypatch.setattr(providers, "reserve_provider_call", lambda _provider: None)
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


def test_release_browse_orders_by_date_not_popularity(monkeypatch):
    monkeypatch.setenv("TMDB_READ_TOKEN", "test-token")
    monkeypatch.setenv("TWITCH_CLIENT_ID", "test-client")
    seen = []

    async def fake_request(_client, provider, method, url, **kwargs):
        seen.append((provider, kwargs))
        return httpx.Response(200, request=httpx.Request(method, url),
                              json=[] if provider == "igdb" else {"results": []})

    async def fake_token(_client):
        return "test-token"

    monkeypatch.setattr(providers, "provider_request", fake_request)
    monkeypatch.setattr(providers, "igdb_token", fake_token)
    async def browse():
        async with httpx.AsyncClient() as api:
            await providers.browse_tmdb(api, "recent", "movie", date(2026, 10, 13))
            await providers.browse_tmdb(api, "upcoming", "tv", date(2026, 10, 13))
            await providers.browse_igdb(api, "recent", date(2026, 10, 13))
            await providers.browse_igdb(api, "upcoming", date(2026, 10, 13))

    asyncio.run(browse())
    assert seen[0][1]["params"]["sort_by"] == "primary_release_date.desc"
    assert seen[1][1]["params"]["sort_by"] == "first_air_date.asc"
    assert b"sort first_release_date desc" in seen[2][1]["content"]
    assert b"sort first_release_date asc" in seen[3][1]["content"]


def test_provider_call_waits_for_next_budget_window(monkeypatch):
    reservations = 0
    waits = []

    def reserve(_provider):
        nonlocal reservations
        reservations += 1
        if reservations == 1:
            raise limits.ProviderRateLimited("budget exhausted")

    async def fake_sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr(providers, "reserve_provider_call", reserve)
    monkeypatch.setattr(providers.asyncio, "sleep", fake_sleep)
    async def request():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _request: httpx.Response(200))) as api:
            return await providers.provider_request(api, "igdb", "GET", "https://example.test/")

    assert asyncio.run(request()).status_code == 200
    assert reservations == 2
    assert len(waits) == 1


def test_existing_report_table_gets_additive_columns(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.sqlite3'}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE missing_title_reports (id VARCHAR(32) PRIMARY KEY, media_type VARCHAR(8), name VARCHAR(500), normalized_name VARCHAR(500), status VARCHAR(16), resolved_title_id VARCHAR(32), github_issue_number INTEGER, github_issue_url TEXT, created_at DATETIME, updated_at DATETIME)")
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    database.init_database()
    columns = {column["name"] for column in inspect(engine).get_columns("missing_title_reports")}
    assert {"github_issue_closed_at", "admin_notified_at", "excluded_title_ids_json"} <= columns
    engine.dispose()
