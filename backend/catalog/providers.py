"""Normalized search adapters for TMDB and IGDB."""

from __future__ import annotations

import asyncio
import html
import os
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from itertools import zip_longest

import httpx

from .identity import close_name, normalize_name
from .limits import ProviderRateLimited, reserve_provider_call


@dataclass(frozen=True)
class ProviderTitle:
    provider: str
    media_type: str
    provider_id: str
    name: str
    overview: str
    poster_url: str | None
    release_date: date | None
    popularity: float = 0.0
    aliases: tuple[str, ...] = ()
    external_ids: tuple[tuple[str, str], ...] = ()


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


class ProviderSearchError(Exception):
    pass


async def tv_seasons(provider: str, provider_id: str) -> list[dict]:
    """Return numbered seasons from the title's canonical TV source."""
    async with httpx.AsyncClient(timeout=12) as client:
        if provider == "tvmaze":
            response = await provider_request(client, "tvmaze", "GET", f"https://api.tvmaze.com/shows/{provider_id}/seasons")
            response.raise_for_status()
            return [{"number": item["number"], "name": item.get("name") or f"Season {item['number']}",
                     "episode_count": item.get("episodeOrder")} for item in response.json() if isinstance(item.get("number"), int)]
        token = os.getenv("TMDB_READ_TOKEN")
        if provider != "tmdb" or not token:
            raise ProviderSearchError("TV season source is unavailable")
        response = await provider_request(client, "tmdb", "GET", f"https://api.themoviedb.org/3/tv/{provider_id}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
        response.raise_for_status()
        return [{"number": item["season_number"], "name": item.get("name") or f"Season {item['season_number']}",
                 "episode_count": item.get("episode_count")} for item in response.json().get("seasons", [])
                if isinstance(item.get("season_number"), int)]


async def tv_episodes(provider: str, provider_id: str, season_number: int) -> list[dict]:
    """Return episodes with stable numbering and provider air dates."""
    async with httpx.AsyncClient(timeout=12) as client:
        if provider == "tvmaze":
            response = await provider_request(client, "tvmaze", "GET",
                f"https://api.tvmaze.com/shows/{provider_id}/episodes", params={"specials": 1})
            response.raise_for_status()
            items = [item for item in response.json() if item.get("season") == season_number]
            return [{"number": item["number"], "name": item.get("name") or f"Episode {item['number']}",
                     "air_date": parse_date(item.get("airdate"))} for item in items if isinstance(item.get("number"), int)]
        token = os.getenv("TMDB_READ_TOKEN")
        if provider != "tmdb" or not token:
            raise ProviderSearchError("TV episode source is unavailable")
        response = await provider_request(client, "tmdb", "GET",
            f"https://api.themoviedb.org/3/tv/{provider_id}/season/{season_number}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
        response.raise_for_status()
        return [{"number": item["episode_number"], "name": item.get("name") or f"Episode {item['episode_number']}",
                 "air_date": parse_date(item.get("air_date"))} for item in response.json().get("episodes", [])
                if isinstance(item.get("episode_number"), int)]


async def provider_request(client: httpx.AsyncClient, provider: str, method: str, url: str, **kwargs) -> httpx.Response:
    """Reserve a shared request slot before sending provider traffic."""
    for attempt in range(2):
        try:
            await asyncio.to_thread(reserve_provider_call, provider)
            break
        except ProviderRateLimited as error:
            if attempt:
                raise ProviderSearchError(str(error)) from error
            # A report may refresh both game feeds and then search IGDB. Let the
            # shared counter advance to its next second before giving up.
            await asyncio.sleep(max(0.05, 1.02 - time.time() % 1))
    return await client.request(method, url, **kwargs)


_igdb_token = ""
_igdb_expires = 0.0
_igdb_lock = asyncio.Lock()


async def igdb_token(client: httpx.AsyncClient) -> str:
    global _igdb_token, _igdb_expires
    if _igdb_token and time.monotonic() < _igdb_expires:
        return _igdb_token
    async with _igdb_lock:
        if _igdb_token and time.monotonic() < _igdb_expires:
            return _igdb_token
        client_id = os.getenv("TWITCH_CLIENT_ID")
        secret = os.getenv("TWITCH_CLIENT_SECRET")
        if not client_id or not secret:
            raise ProviderSearchError("IGDB credentials are missing")
        response = await client.post(
            "https://id.twitch.tv/oauth2/token",
            data={"client_id": client_id, "client_secret": secret, "grant_type": "client_credentials"},
        )
        response.raise_for_status()
        payload = response.json()
        _igdb_token = payload["access_token"]
        _igdb_expires = time.monotonic() + max(0, int(payload.get("expires_in", 3600)) - 60)
        return _igdb_token


async def search_tmdb(client: httpx.AsyncClient, query: str, media_type: str) -> list[ProviderTitle]:
    token = os.getenv("TMDB_READ_TOKEN")
    if not token:
        raise ProviderSearchError("TMDB credentials are missing")
    response = await provider_request(client, "tmdb", "GET",
        f"https://api.themoviedb.org/3/search/{media_type}",
        params={"query": query, "include_adult": "false", "page": 1},
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    response.raise_for_status()
    payload = response.json()
    items = payload.get("results", [])
    # TMDB sorts by relevance/popularity. Check a few more pages only when page one
    # has no close title, so an obscure exact match is not lost behind popular hits.
    if not any(close_name(query, item.get("title" if media_type == "movie" else "name") or "") for item in items):
        for page in range(2, min(int(payload.get("total_pages") or 1), 3) + 1):
            more = await provider_request(client, "tmdb", "GET",
                f"https://api.themoviedb.org/3/search/{media_type}",
                params={"query": query, "include_adult": "false", "page": page},
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
            more.raise_for_status()
            items.extend(more.json().get("results", []))
            if any(close_name(query, item.get("title" if media_type == "movie" else "name") or "") for item in items):
                break
    return normalize_tmdb(items[:40], media_type)


def normalize_tmdb(items: list[dict], media_type: str) -> list[ProviderTitle]:
    results = []
    for item in items:
        name = item.get("title" if media_type == "movie" else "name")
        if not name or item.get("id") is None:
            continue
        poster = item.get("poster_path")
        original = item.get("original_title" if media_type == "movie" else "original_name")
        results.append(ProviderTitle(
            provider="tmdb", media_type=media_type, provider_id=str(item["id"]),
            name=name, overview=item.get("overview") or "",
            poster_url=f"https://image.tmdb.org/t/p/w342{poster}" if poster else None,
            release_date=parse_date(item.get("release_date" if media_type == "movie" else "first_air_date")),
            popularity=float(item.get("popularity") or 0),
            aliases=(original,) if original and normalize_name(original) != normalize_name(name) else (),
        ))
    return results


async def search_igdb(client: httpx.AsyncClient, query: str) -> list[ProviderTitle]:
    client_id = os.getenv("TWITCH_CLIENT_ID")
    if not client_id:
        raise ProviderSearchError("IGDB credentials are missing")
    token = await igdb_token(client)
    escaped = query.replace("\\", "\\\\").replace('"', '\\"')
    body = (
        f'search "{escaped}"; '
        'fields id,name,first_release_date,summary,cover.image_id,alternative_names.name,version_parent,total_rating_count; limit 30;'
    )
    response = await provider_request(client, "igdb", "POST",
        "https://api.igdb.com/v4/games",
        content=body.encode("utf-8"),
        headers={"Client-ID": client_id, "Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    response.raise_for_status()
    items = response.json()
    normalized_query = query.casefold()
    items.sort(key=lambda item: (
        0 if (item.get("name") or "").casefold() == normalized_query else
        1 if (item.get("name") or "").casefold().startswith(normalized_query) else 2,
        -(item.get("total_rating_count") or 0),
    ))
    return normalize_igdb(items[:20])


def normalize_igdb(items: list[dict]) -> list[ProviderTitle]:
    results = []
    for item in items:
        if not item.get("name") or item.get("id") is None:
            continue
        timestamp = item.get("first_release_date")
        released = datetime.fromtimestamp(timestamp, timezone.utc).date() if timestamp else None
        cover = (item.get("cover") or {}).get("image_id")
        aliases = tuple(alias["name"] for alias in item.get("alternative_names") or []
                        if isinstance(alias, dict) and alias.get("name"))
        results.append(ProviderTitle(
            provider="igdb", media_type="game", provider_id=str(item["id"]),
            name=item["name"], overview=item.get("summary") or "",
            poster_url=f"https://images.igdb.com/igdb/image/upload/t_cover_big/{cover}.jpg" if cover else None,
            release_date=released,
            popularity=float(item.get("total_rating_count") or 0),
            aliases=aliases,
        ))
    return results


async def browse_tmdb(client: httpx.AsyncClient, section: str, media_type: str, today: date, page: int = 1) -> list[ProviderTitle]:
    token = os.getenv("TMDB_READ_TOKEN")
    if not token:
        raise ProviderSearchError("TMDB credentials are missing")
    date_field = "primary_release_date" if media_type == "movie" else "first_air_date"
    sort_by = "popularity.desc" if section == "popular" else f"{date_field}.{'desc' if section == 'recent' else 'asc'}"
    params = {"include_adult": "false", "page": page, "sort_by": sort_by}
    if section != "popular":
        start, end = (
            (today - timedelta(days=90), today)
            if section == "recent" else
            (today + timedelta(days=1), today + timedelta(days=180))
        )
        params.update({f"{date_field}.gte": start.isoformat(), f"{date_field}.lte": end.isoformat()})
    response = await provider_request(client, "tmdb", "GET",
        f"https://api.themoviedb.org/3/discover/{media_type}",
        params=params,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    response.raise_for_status()
    return normalize_tmdb(response.json().get("results", []), media_type)


async def browse_igdb(client: httpx.AsyncClient, section: str, today: date, page: int = 1) -> list[ProviderTitle]:
    client_id = os.getenv("TWITCH_CLIENT_ID")
    if not client_id:
        raise ProviderSearchError("IGDB credentials are missing")
    token = await igdb_token(client)
    date_filter = ""
    if section != "popular":
        start, end = (
            (today - timedelta(days=90), today + timedelta(days=1))
            if section == "recent" else
            (today + timedelta(days=1), today + timedelta(days=181))
        )
        start_ts = int(datetime.combine(start, datetime_time.min, timezone.utc).timestamp())
        end_ts = int(datetime.combine(end, datetime_time.min, timezone.utc).timestamp())
        date_filter = f"where first_release_date >= {start_ts} & first_release_date < {end_ts}; "
    sort_by = "total_rating_count desc" if section == "popular" else f"first_release_date {'desc' if section == 'recent' else 'asc'}"
    body = (
        "fields id,name,first_release_date,summary,cover.image_id,total_rating_count; "
        f"{date_filter}"
        f"sort {sort_by}; limit 20; offset {(page - 1) * 20};"
    )
    response = await provider_request(client, "igdb", "POST",
        "https://api.igdb.com/v4/games", content=body.encode("utf-8"),
        headers={"Client-ID": client_id, "Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    response.raise_for_status()
    return normalize_igdb(response.json())


async def browse_providers(section: str, media_type: str, today: date, page: int = 1) -> tuple[list[ProviderTitle], list[str]]:
    async with httpx.AsyncClient(timeout=12.0) as client:
        searches = []
        names = []
        if media_type in {"all", "movie"}:
            searches.append(browse_tmdb(client, section, "movie", today, page))
            names.append("movies")
        if media_type in {"all", "tv"}:
            searches.append(browse_tmdb(client, section, "tv", today, page))
            names.append("TV")
        if media_type in {"all", "game"}:
            searches.append(browse_igdb(client, section, today, page))
            names.append("games")
        responses = await asyncio.gather(*searches, return_exceptions=True)

    groups: list[list[ProviderTitle]] = []
    warnings: list[str] = []
    for name, response in zip(names, responses):
        if isinstance(response, Exception):
            warnings.append(f"{name} browse is temporarily unavailable")
        else:
            groups.append(response)
    if not groups:
        raise ProviderSearchError("All selected catalog sources are unavailable")
    # Interleave source groups so one provider cannot crowd out other media.
    titles = [item for row in zip_longest(*groups) for item in row if item is not None]
    return titles[:18] if media_type == "all" else titles, warnings


async def search_tvmaze(client: httpx.AsyncClient, query: str) -> list[ProviderTitle]:
    response = await provider_request(client, "tvmaze", "GET",
        "https://api.tvmaze.com/search/shows", params={"q": query},
        headers={"User-Agent": "MediaCatalog/0.1 (open-source catalog)", "Accept": "application/json"},
    )
    response.raise_for_status()
    results = []
    for item in response.json()[:20]:
        show = item.get("show") or {}
        name = show.get("name") or ""
        if not show.get("id") or not close_name(query, name):
            continue
        imdb = (show.get("externals") or {}).get("imdb")
        external_ids = (("imdb", imdb),) if isinstance(imdb, str) and re.fullmatch(r"tt\d{7,10}", imdb) else ()
        summary = html.unescape(re.sub(r"<[^>]+>", " ", show.get("summary") or ""))
        results.append(ProviderTitle(
            provider="tvmaze", media_type="tv", provider_id=str(show["id"]),
            name=name, overview=" ".join(summary.split()),
            poster_url=(show.get("image") or {}).get("medium"),
            release_date=parse_date(show.get("premiered")),
            popularity=float(item.get("score") or 0), external_ids=external_ids,
        ))
    return results


async def search_rawg(client: httpx.AsyncClient, query: str) -> list[ProviderTitle]:
    key = os.getenv("RAWG_API_KEY")
    if not key:
        return []
    response = await provider_request(client, "rawg", "GET",
        "https://api.rawg.io/api/games",
        params={"key": key, "search": query, "search_precise": "true", "page_size": 20},
        headers={"Accept": "application/json"},
    )
    response.raise_for_status()
    results = []
    for item in response.json().get("results", []):
        name = item.get("name") or ""
        if item.get("id") is None or not close_name(query, name):
            continue
        results.append(ProviderTitle(
            provider="rawg", media_type="game", provider_id=str(item["id"]),
            name=name, overview="", poster_url=item.get("background_image"),
            release_date=parse_date(item.get("released")),
            popularity=float(item.get("rating") or 0),
        ))
    return results


async def title_media(provider: str, media_type: str, provider_id: str) -> dict[str, str | None]:
    """Fetch a trailer and a verified detail URL only when a title is opened."""
    async with httpx.AsyncClient(timeout=12.0) as client:
        if provider == "tmdb":
            token = os.getenv("TMDB_READ_TOKEN")
            if not token:
                raise ProviderSearchError("TMDB credentials are missing")
            response = await provider_request(client, "tmdb", "GET",
                f"https://api.themoviedb.org/3/{media_type}/{provider_id}",
                params={"append_to_response": "videos,external_ids"},
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
            response.raise_for_status()
            payload = response.json()
            videos = (payload.get("videos") or {}).get("results") or []
            trailers = [video for video in videos if video.get("site") == "YouTube" and video.get("type") == "Trailer" and re.fullmatch(r"[A-Za-z0-9_-]{11}", video.get("key") or "")]
            trailers.sort(key=lambda video: (not bool(video.get("official")), video.get("iso_639_1") != "en"))
            trailer = f"https://www.youtube-nocookie.com/embed/{trailers[0]['key']}" if trailers else None
            imdb = (payload.get("external_ids") or {}).get("imdb_id") or payload.get("imdb_id")
            external = f"https://www.imdb.com/title/{imdb}/" if isinstance(imdb, str) and re.fullmatch(r"tt\d{7,10}", imdb) else f"https://www.themoviedb.org/{media_type}/{provider_id}"
            return {"trailer_url": trailer, "external_url": external, "external_label": "IMDb" if "imdb.com" in external else "TMDB"}
        if provider == "igdb":
            client_id = os.getenv("TWITCH_CLIENT_ID")
            if not client_id:
                raise ProviderSearchError("IGDB credentials are missing")
            token = await igdb_token(client)
            response = await provider_request(client, "igdb", "POST",
                "https://api.igdb.com/v4/games",
                content=f"fields url,videos.video_id; where id = {int(provider_id)}; limit 1;".encode(),
                headers={"Client-ID": client_id, "Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
            response.raise_for_status()
            item = next(iter(response.json()), {})
            video_id = next((video.get("video_id") for video in item.get("videos") or [] if re.fullmatch(r"[A-Za-z0-9_-]{11}", video.get("video_id") or "")), None)
            url = item.get("url") or ""
            external = url if isinstance(url, str) and url.startswith("https://www.igdb.com/games/") else f"https://www.igdb.com/games/{provider_id}"
            return {"trailer_url": f"https://www.youtube-nocookie.com/embed/{video_id}" if video_id else None, "external_url": external, "external_label": "IGDB"}
        if provider == "tvmaze":
            response = await provider_request(client, "tvmaze", "GET", f"https://api.tvmaze.com/shows/{int(provider_id)}")
            response.raise_for_status()
            url = response.json().get("url") or ""
            external = url if isinstance(url, str) and url.startswith("https://www.tvmaze.com/shows/") else f"https://www.tvmaze.com/shows/{provider_id}"
            return {"trailer_url": None, "external_url": external, "external_label": "TVmaze"}
        if provider == "rawg":
            key = os.getenv("RAWG_API_KEY")
            if not key:
                raise ProviderSearchError("RAWG credentials are missing")
            response = await provider_request(client, "rawg", "GET", f"https://api.rawg.io/api/games/{int(provider_id)}", params={"key": key})
            response.raise_for_status()
            slug = response.json().get("slug") or provider_id
            if not re.fullmatch(r"[a-z0-9-]+", slug):
                slug = provider_id
            return {"trailer_url": None, "external_url": f"https://rawg.io/games/{slug}", "external_label": "RAWG"}
    raise ProviderSearchError("Unsupported title source")


async def search_providers(query: str, media_type: str) -> tuple[list[ProviderTitle], list[str]]:
    async with httpx.AsyncClient(timeout=12.0) as client:
        searches = []
        names = []
        if media_type in {"all", "movie"}:
            searches.append(search_tmdb(client, query, "movie"))
            names.append("movies")
        if media_type in {"all", "tv"}:
            searches.append(search_tmdb(client, query, "tv"))
            names.append("TV")
        if media_type in {"all", "game"}:
            searches.append(search_igdb(client, query))
            names.append("games")
        responses = await asyncio.gather(*searches, return_exceptions=True)

    groups: list[list[ProviderTitle]] = []
    warnings: list[str] = []
    for name, response in zip(names, responses):
        if isinstance(response, Exception):
            warnings.append(f"{name} search is temporarily unavailable")
        else:
            groups.append(response)
    titles = [item for group in groups for item in group]
    # Supplemental sources are queried only when their primary category lacks a
    # plausible match. They are separate records unless a verified ID links them.
    if len(normalize_name(query)) >= 4:
        async with httpx.AsyncClient(timeout=12.0) as client:
            fallbacks = []
            labels = []
            if media_type in {"all", "tv"} and not any(item.media_type == "tv" and close_name(query, item.name) for item in titles):
                fallbacks.append(search_tvmaze(client, query))
                labels.append("TVmaze")
            if media_type in {"all", "game"} and os.getenv("RAWG_API_KEY") and not any(item.media_type == "game" and close_name(query, item.name) for item in titles):
                fallbacks.append(search_rawg(client, query))
                labels.append("RAWG")
            for label, response in zip(labels, await asyncio.gather(*fallbacks, return_exceptions=True)):
                if isinstance(response, Exception):
                    warnings.append(f"{label} search is temporarily unavailable")
                else:
                    titles.extend(response)
    if not groups and not titles:
        raise ProviderSearchError("All selected catalog sources are unavailable")
    normalized_query = query.casefold()
    titles.sort(key=lambda item: (
        0 if item.name.casefold() == normalized_query else
        1 if item.name.casefold().startswith(normalized_query) else 2,
        -item.popularity,
    ))
    return titles, warnings
