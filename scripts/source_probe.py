#!/usr/bin/env python3
"""Small, bounded TMDB/IGDB probe. Never stores credentials or full API responses."""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "smoke.json"
USER_AGENT = "media-catalog-source-validation/0.1"


def load_local_env() -> None:
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if key in {"TMDB_READ_TOKEN", "TWITCH_CLIENT_ID", "TWITCH_CLIENT_SECRET"}:
            os.environ.setdefault(key, value.strip("\"'"))


def fixtures(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        raise ValueError("fixture must be a nonempty JSON array")
    for index, item in enumerate(data):
        if not isinstance(item, dict) or item.get("media_type") not in {"movie", "tv", "game"}:
            raise ValueError(f"fixture {index}: invalid media_type")
        if not isinstance(item.get("query"), str) or not item["query"].strip():
            raise ValueError(f"fixture {index}: query is required")
        if not isinstance(item.get("expected_title"), str) or not item["expected_title"].strip():
            raise ValueError(f"fixture {index}: expected_title is required")
        if "expected_year" in item and not isinstance(item["expected_year"], int):
            raise ValueError(f"fixture {index}: expected_year must be an integer")
    return data


def request_json(url: str, *, headers: dict | None = None, data: bytes | None = None) -> dict | list:
    request = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        retry_after = error.headers.get("Retry-After", "")
        suffix = f"; Retry-After={retry_after}" if retry_after else ""
        raise RuntimeError(f"HTTP {error.code}{suffix}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"network error: {error.reason}") from error


def twitch_token() -> str:
    client_id = os.environ.get("TWITCH_CLIENT_ID")
    client_secret = os.environ.get("TWITCH_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError("TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET are required for game queries")
    data = urllib.parse.urlencode({"client_id": client_id, "client_secret": client_secret, "grant_type": "client_credentials"}).encode()
    response = request_json("https://id.twitch.tv/oauth2/token", data=data)
    return response["access_token"]


def tmdb_search(item: dict) -> list[dict]:
    token = os.environ.get("TMDB_READ_TOKEN")
    if not token:
        raise RuntimeError("TMDB_READ_TOKEN is required for movie/TV queries")
    media_type = item["media_type"]
    query = urllib.parse.urlencode({"query": item["query"], "include_adult": "false", "page": 1})
    response = request_json(
        f"https://api.themoviedb.org/3/search/{media_type}?{query}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    title_field = "title" if media_type == "movie" else "name"
    date_field = "release_date" if media_type == "movie" else "first_air_date"
    return [
        {"id": result["id"], "title": result.get(title_field, ""), "year": year(result.get(date_field)), "rank": rank}
        for rank, result in enumerate(response.get("results", [])[:20], 1)
    ]


def igdb_search(item: dict, token: str) -> list[dict]:
    client_id = os.environ["TWITCH_CLIENT_ID"]
    escaped = item["query"].replace("\\", "\\\\").replace('"', '\\"')
    body = f'search "{escaped}"; fields id,name,first_release_date; limit 20;'.encode()
    response = request_json(
        "https://api.igdb.com/v4/games",
        headers={"Client-ID": client_id, "Authorization": f"Bearer {token}", "Accept": "application/json"},
        data=body,
    )
    return [
        {"id": result["id"], "title": result.get("name", ""),
         "year": time.gmtime(result["first_release_date"]).tm_year if result.get("first_release_date") else None,
         "rank": rank}
        for rank, result in enumerate(response[:20], 1)
    ]


def year(value: str | None) -> int | None:
    return int(value[:4]) if value and len(value) >= 4 and value[:4].isdigit() else None


def search(item: dict, token: str | None) -> list[dict]:
    return igdb_search(item, token) if item["media_type"] == "game" else tmdb_search(item)


def run_search(items: list[dict], delay: float) -> int:
    token = twitch_token() if any(item["media_type"] == "game" for item in items) else None
    graded = found_top_1 = found_top_5 = errors = 0
    for index, item in enumerate(items):
        if index:
            time.sleep(delay)
        started = time.monotonic()
        try:
            candidates = search(item, token)
            expected_id = item.get("expected_id")
            match_rank = next((candidate["rank"] for candidate in candidates if candidate["id"] == expected_id), None) if expected_id is not None else None
            if expected_id is not None:
                graded += 1
                found_top_1 += match_rank == 1
                found_top_5 += match_rank is not None and match_rank <= 5
            print(json.dumps({"query": item["query"], "media_type": item["media_type"], "expected_id": expected_id, "bucket": item.get("bucket"), "expected_title": item["expected_title"], "expected_year": item.get("expected_year"), "match_rank": match_rank, "candidates": candidates[:5], "latency_ms": round((time.monotonic() - started) * 1000)}))
        except RuntimeError as error:
            errors += 1
            print(json.dumps({"query": item["query"], "media_type": item["media_type"], "expected_id": item.get("expected_id"), "bucket": item.get("bucket"), "error": str(error)}))
    print(json.dumps({"summary": {"queries": len(items), "graded_by_provider_id": graded, "top_1": found_top_1, "top_5": found_top_5, "errors": errors, "manual_review_required": len(items) - graded}}))
    return 1 if errors else 0


def run_browse(window_days: int) -> int:
    """Check first-page browse and dated-release queries without storing responses."""
    today = datetime.date.today()
    end = today + datetime.timedelta(days=window_days)
    tmdb_token = os.environ.get("TMDB_READ_TOKEN")
    if not tmdb_token:
        raise RuntimeError("TMDB_READ_TOKEN is required for movie/TV browse queries")
    tmdb_headers = {"Authorization": f"Bearer {tmdb_token}", "Accept": "application/json"}
    for media_type in ("movie", "tv"):
        for mode in ("popular", "upcoming"):
            params = {"page": 1, "sort_by": "popularity.desc"}
            if mode == "upcoming":
                date_field = "primary_release_date" if media_type == "movie" else "first_air_date"
                params = {
                    "page": 1,
                    "sort_by": f"{date_field}.asc",
                    f"{date_field}.gte": today.isoformat(),
                    f"{date_field}.lte": end.isoformat(),
                }
            response = request_json(
                f"https://api.themoviedb.org/3/discover/{media_type}?{urllib.parse.urlencode(params)}",
                headers=tmdb_headers,
            )
            title_field = "title" if media_type == "movie" else "name"
            result_date_field = "release_date" if media_type == "movie" else "first_air_date"
            print(json.dumps({
                "provider": "tmdb", "media_type": media_type, "mode": mode,
                "results_on_first_page": len(response.get("results", [])),
                "reported_pages": response.get("total_pages"),
                "examples": [
                    {"id": result["id"], "title": result.get(title_field), "date": result.get(result_date_field)}
                    for result in response.get("results", [])[:3]
                ],
            }))

    token = twitch_token()
    start_ts = int(datetime.datetime.combine(today, datetime.time.min, tzinfo=datetime.timezone.utc).timestamp())
    end_ts = int(datetime.datetime.combine(end, datetime.time.min, tzinfo=datetime.timezone.utc).timestamp())
    body = (
        "fields id,date,game.id,game.name,platform.name,release_region; "
        f"where date >= {start_ts} & date < {end_ts}; sort date asc; limit 20;"
    ).encode()
    response = request_json(
        "https://api.igdb.com/v4/release_dates",
        headers={"Client-ID": os.environ["TWITCH_CLIENT_ID"], "Authorization": f"Bearer {token}", "Accept": "application/json"},
        data=body,
    )
    print(json.dumps({
        "provider": "igdb", "media_type": "game", "mode": "upcoming_release_dates",
        "results_on_first_page": len(response),
        "unique_games_on_first_page": len({item.get("game", {}).get("id") for item in response}),
        "examples": [
            {"id": item["id"], "date": item.get("date"), "game": item.get("game"), "platform": item.get("platform")}
            for item in response[:3]
        ],
    }))
    return 0


def percentile(values: list[float], percentage: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int((len(ordered) - 1) * percentage))], 1)


def run_soak(items: list[dict], provider: str, duration: int, rps: float) -> int:
    selected = [item for item in items if (item["media_type"] == "game") == (provider == "igdb")]
    if not selected:
        raise ValueError(f"no {provider} fixtures")
    token = twitch_token() if provider == "igdb" else None
    latencies: list[float] = []
    errors: dict[str, int] = {}
    started = time.monotonic()
    next_request = started
    count = 0
    while time.monotonic() - started < duration:
        time.sleep(max(0, next_request - time.monotonic()))
        next_request = time.monotonic() + 1 / rps
        item = selected[count % len(selected)]
        request_start = time.monotonic()
        try:
            search(item, token)
            latencies.append((time.monotonic() - request_start) * 1000)
        except RuntimeError as error:
            label = str(error)
            errors[label] = errors.get(label, 0) + 1
            count += 1
            if label.startswith("HTTP 429"):
                # Stop immediately rather than continue probing a provider that is throttling us.
                break
            continue
        count += 1
    print(json.dumps({"provider": provider, "requests": count, "duration_s": round(time.monotonic() - started, 1), "p50_ms": percentile(latencies, 0.50), "p95_ms": percentile(latencies, 0.95), "p99_ms": percentile(latencies, 0.99), "errors": errors}))
    return 1 if errors else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["validate", "search", "browse", "soak"])
    parser.add_argument("--fixture", type=Path, default=FIXTURE)
    parser.add_argument("--delay", type=float, default=0.5, help="seconds between search requests")
    parser.add_argument("--provider", choices=["tmdb", "igdb"], help="required for soak")
    parser.add_argument("--duration", type=int, default=60, help="soak seconds, max 3600")
    parser.add_argument("--rps", type=float, default=1.0, help="soak request rate, max 2")
    parser.add_argument("--window-days", type=int, default=30, help="browse upcoming window in days, max 365")
    args = parser.parse_args()
    load_local_env()
    items = fixtures(args.fixture)
    if args.command == "validate":
        print(json.dumps({"fixtures": len(items), "media_types": {kind: sum(item["media_type"] == kind for item in items) for kind in ("movie", "tv", "game")}}))
        return 0
    if args.command == "search":
        if args.delay < 0.5:
            parser.error("--delay must be at least 0.5 seconds")
        return run_search(items, args.delay)
    if args.command == "browse":
        if not 1 <= args.window_days <= 365:
            parser.error("--window-days must be 1..365")
        return run_browse(args.window_days)
    if not args.provider or not 1 <= args.duration <= 3600 or not 0 < args.rps <= 2:
        parser.error("soak requires --provider, --duration 1..3600, and --rps >0..2")
    return run_soak(items, args.provider, args.duration, args.rps)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(2)
