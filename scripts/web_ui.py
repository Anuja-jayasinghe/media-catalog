#!/usr/bin/env python3
"""Local search UI for inspecting TMDB and IGDB requests and responses."""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    from . import source_probe as probe
except ImportError:  # Direct execution: python3 scripts/web_ui.py
    import source_probe as probe


WEB = Path(__file__).resolve().parents[1] / "web"
MEDIA_TYPES = {"movie": "TMDB", "tv": "TMDB", "game": "IGDB"}
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
}


class TokenCache:
    def __init__(self) -> None:
        self._token = ""
        self._expires_at = 0.0
        self._lock = threading.Lock()

    def get(self) -> str:
        with self._lock:
            if self._token and time.monotonic() < self._expires_at:
                return self._token
            client_id = os.environ.get("TWITCH_CLIENT_ID")
            client_secret = os.environ.get("TWITCH_CLIENT_SECRET")
            if not client_id or not client_secret:
                raise RuntimeError("Twitch client ID and secret are required for game search")
            data = urllib.parse.urlencode({
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "client_credentials",
            }).encode()
            response = probe.request_json("https://id.twitch.tv/oauth2/token", data=data)
            self._token = response["access_token"]
            self._expires_at = time.monotonic() + max(0, int(response.get("expires_in", 3600)) - 60)
            return self._token


TOKENS = TokenCache()


def parse_result(media_type: str, item: dict, rank: int) -> dict:
    if media_type == "game":
        timestamp = item.get("first_release_date")
        released = datetime.datetime.fromtimestamp(timestamp, datetime.timezone.utc).date().isoformat() if timestamp else None
        cover_id = item.get("cover", {}).get("image_id")
        return {
            "id": item["id"], "rank": rank, "title": item.get("name", "Untitled game"),
            "type": "game", "release_date": released, "year": int(released[:4]) if released else None,
            "description": item.get("summary", ""),
            "poster_url": f"https://images.igdb.com/igdb/image/upload/t_cover_big/{cover_id}.jpg" if cover_id else None,
            "platforms": [platform.get("name", "") for platform in item.get("platforms", [])],
            "version_parent": item.get("version_parent"),
            "provider_url": item.get("url"),
        }
    title_field = "title" if media_type == "movie" else "name"
    date_field = "release_date" if media_type == "movie" else "first_air_date"
    released = item.get(date_field) or None
    poster_path = item.get("poster_path")
    return {
        "id": item["id"], "rank": rank, "title": item.get(title_field, "Untitled"),
        "type": media_type, "release_date": released, "year": probe.year(released),
        "description": item.get("overview", ""),
        "poster_url": f"https://image.tmdb.org/t/p/w342{poster_path}" if poster_path else None,
        "platforms": [], "version_parent": None,
        "provider_url": f"https://www.themoviedb.org/{media_type}/{item['id']}",
    }


def search_catalog(media_type: str, query: str) -> dict:
    if media_type not in MEDIA_TYPES:
        raise ValueError("Choose movie, TV, or game")
    query = query.strip()
    if not query or len(query) > 120:
        raise ValueError("Enter a search term of 1 to 120 characters")

    if media_type == "game":
        escaped = query.replace("\\", "\\\\").replace('"', '\\"')
        body = f'search "{escaped}"; fields id,name,first_release_date,summary,cover.image_id,platforms.name,url,version_parent; limit 20;'
        endpoint = "https://api.igdb.com/v4/games"
        response = probe.request_json(
            endpoint,
            headers={"Client-ID": os.environ.get("TWITCH_CLIENT_ID", ""), "Authorization": f"Bearer {TOKENS.get()}", "Accept": "application/json"},
            data=body.encode(),
        )
        request = {
            "method": "POST", "url": endpoint,
            "headers": {"Client-ID": "[redacted]", "Authorization": "Bearer [redacted]", "Accept": "application/json"},
            "body": body,
        }
        items = response
    else:
        token = os.environ.get("TMDB_READ_TOKEN")
        if not token:
            raise RuntimeError("TMDB_READ_TOKEN is required for movie/TV search")
        params = {"query": query, "include_adult": "false", "page": 1}
        endpoint = f"https://api.themoviedb.org/3/search/{media_type}"
        response = probe.request_json(
            f"{endpoint}?{urllib.parse.urlencode(params)}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        request = {
            "method": "GET", "url": endpoint,
            "headers": {"Authorization": "Bearer [redacted]", "Accept": "application/json"},
            "query": params, "body": None,
        }
        items = response.get("results", [])

    parsed = [parse_result(media_type, item, rank) for rank, item in enumerate(items, 1)]
    return {"provider": MEDIA_TYPES[media_type], "media_type": media_type, "request": request, "response": response, "parsed": parsed}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        url = urllib.parse.urlsplit(self.path)
        allowed_hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        if self.headers.get("Host") not in allowed_hosts:
            self.send_json({"error": "Local host only"}, 403)
            return
        if url.path == "/api/search" and self.headers.get("Sec-Fetch-Site", "same-origin") not in {"same-origin", "none"}:
            self.send_json({"error": "Same-origin requests only"}, 403)
            return
        if url.path in STATIC_FILES:
            filename, content_type = STATIC_FILES[url.path]
            self.send_payload((WEB / filename).read_bytes(), 200, content_type)
            return
        if url.path == "/api/search":
            params = urllib.parse.parse_qs(url.query)
            media_type = params.get("type", [""])[0]
            query = params.get("q", [""])[0]
            try:
                result = search_catalog(media_type, query)
            except ValueError as error:
                self.send_json({"error": str(error)}, 400)
                return
            except (RuntimeError, KeyError, OSError, TypeError) as error:
                self.send_json({"error": f"Provider request failed: {error}"}, 502)
                return
            self.send_json(result)
            return
        self.send_json({"error": "Not found"}, 404)

    def send_json(self, value: dict, status: int = 200) -> None:
        self.send_payload(json.dumps(value, ensure_ascii=False).encode("utf-8"), status, "application/json; charset=utf-8")

    def send_payload(self, payload: bytes, status: int, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' https://image.tmdb.org https://images.igdb.com; connect-src 'self'; script-src 'self'; style-src 'self'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(payload)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765, help="local port (default: 8765)")
    args = parser.parse_args()
    probe.load_local_env()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.daemon_threads = True
    print(f"Media Catalog API Lab: http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
