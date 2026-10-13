# First product slice architecture

Status: implemented locally on 2026-10-13. This is a foundation for the full [product requirements](product-requirements.md), not a launch-complete catalog.

## Request path

1. The Next.js page searches as the user types, after a 250 ms pause. With no query, it shows recent and upcoming releases. The optional filter narrows movies, TV series, or games.
2. FastAPI calls TMDB and IGDB from the server, normalizes the results, and stores shared title records. TVmaze, and optionally RAWG, are queried when the corresponding primary source has no close match. A ten-minute database snapshot reuses repeated search results; release rows refresh after six hours and use date-based provider discovery. If all sources fail, an older snapshot or saved local matches can still be shown.
3. Clerk signs users in on the frontend. The browser attaches a session token to library requests. FastAPI verifies the token with Clerk's Python SDK and allowed frontend origins before reading or changing private data.
4. Each Clerk user maps to an internal catalog user ID. Each user has at most one library entry per shared title.

## Current data model

| Table | Purpose | Key invariant |
| --- | --- | --- |
| `titles` | Shared records from TMDB or IGDB | Unique provider, media type, and provider ID |
| `catalog_users` | Internal user identity | Unique Clerk user ID; internal ID is used by personal data |
| `library_entries` | Personal status and optional completion date | Unique user and title; never returned across users |
| `search_snapshots` | Short-term search and release results | One snapshot per normalized query or dated browse section and media filter |
| `title_identities` | Verified provider and external IDs | One media-specific external ID maps to one canonical title |
| `title_aliases` | Searchable alternate names | Names aid retrieval but never establish identity |
| `missing_title_reports` | Deduplicated unresolved requests | One report per normalized title name and media type |
| `report_subscribers` | Optional private email contacts | One subscriber address per report |

Current status values are planned, in progress, completed, and dropped. The API accepts exact, month-only, or unknown completion dates; the current interface exposes status changes first. TV episode progress, ratings, reviews, lists, import provenance, and release updates remain for later slices.

## API surface

- `GET /api/search?q=...&media_type=all|movie|tv|game` — public normalized search.
- `POST /api/missing-titles` — check sources, return a single match or ambiguous choices, or create a deduplicated report.
- `POST /api/internal/reconcile` — bearer-token-protected report reconciliation and publication notifications.
- `GET /api/titles/{title_id}` — public canonical title details.
- `GET /api/discover?section=recent|upcoming&media_type=all|movie|tv|game` — public release browsing.
- `GET /api/library` — current signed-in user's entries.
- `PUT /api/library/{title_id}` — save or update one entry with a status and optional completion date.
- `DELETE /api/library/{title_id}` — remove one personal entry.
- `GET /health` — process health.

## Configuration and deployment

- The API runs on SQLite locally and supports PostgreSQL through `DATABASE_URL`. Initialize the schema with `python -m catalog.database` before starting a production deployment; runtime schema creation is disabled by default on PostgreSQL.
- Deploy `frontend/` and `backend/` as separate Vercel projects initially. Set `NEXT_PUBLIC_API_BASE_URL` to the backend URL. Configure `FRONTEND_ORIGINS` and `CLERK_AUTHORIZED_PARTIES` to the actual frontend origin; do not use `*` for either.
- The frontend works in search-only mode before Clerk keys are configured. Library endpoints return a configuration error until the backend has Clerk credentials.
- Public search and browse endpoints have no distributed rate limiter yet. Provider quota protection and abuse controls are required before a public launch. Debounce and database snapshots only reduce ordinary repeated requests.
- Release browsing fetches the first provider page for a fixed date window; it is not yet a comprehensive release index. A scheduled reconciliation job and coverage/freshness measurement remain necessary before making broader catalog claims.
- Source attribution and media artwork use must be checked against each provider's current terms before public deployment.
