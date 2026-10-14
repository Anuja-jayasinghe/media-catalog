# MTGL

**A personal catalog for movies, TV series, and games.** Discover titles, keep a private library, and look back on what you watched or played.

[Open the live site](https://mtgl.anujajay.com) · [Report a repository issue](https://github.com/Anuja-jayasinghe/media-catalog/issues/new) · [Contributing](CONTRIBUTING.md)

MTGL is an open-source project. The public catalog is shared; each signed-in user's statuses, ratings, reviews, notes, lists, and import history are private.

## What works today

- Browse Movies, TV series, and Games in separate discovery areas, with paginated results and search.
- Open available trailers or follow a title's external information link.
- Keep a personal library with statuses, ratings, reviews, notes, custom lists, and edit history.
- Track TV progress by season/episode or by a watched-through date; episodes released later remain unwatched.
- Import an MTGL JSON backup, review changes, and revert the full import or individual changes.
- Export a full JSON backup or a portable CSV file.
- Share a read-only library link with an expiry, and revoke it at any time.
- Delete an account and its personal library.
- Report missing titles; the service checks the catalog and metadata providers before recording an unresolved report.

External imports from services such as IMDb, Letterboxd, Trakt, Steam, Backloggd, HowLongToBeat, and Plex are **not implemented yet**. The requirements and source feasibility work are tracked in [product requirements](docs/product-requirements.md).

## Catalog sources

| Media | Primary source | Fallback |
| --- | --- | --- |
| Movies and TV | [TMDB](https://developer.themoviedb.org/docs/finding-data) | [TVmaze](https://www.tvmaze.com/api) for TV |
| Games | [IGDB](https://api-docs.igdb.com/) | [RAWG](https://rawg.io/apidocs), when configured |

Provider terms, attribution, caching rules, and rate limits apply. Each deployment needs its own provider credentials. Never commit API keys or send them to the browser.

Catalog release data refreshes every two weeks and can be refreshed during a missing-title report. The scheduled GitHub Action requires its configured repository secrets and backend job token. See the [freshness guide](docs/catalog-freshness.md) and [source validation plan](docs/source-validation-plan.md) for current coverage and known limits.

## Technology

- **Web:** Next.js 16, React 19, Clerk
- **API:** Python 3.11+, FastAPI, SQLAlchemy
- **Database:** SQLite locally; PostgreSQL in the hosted deployment
- **Hosting:** Vercel for the web app and API

Architecture and service decisions are documented in [docs](docs/architecture.md), [authentication](docs/authentication-decision.md), [hosting](docs/hosting-decision.md), and [email](docs/email-decision.md).

## Run locally

### Requirements

- Python 3.11 or newer and [uv](https://docs.astral.sh/uv/)
- Node.js and npm
- API credentials for TMDB and IGDB/Twitch to search live provider data
- Clerk keys to test sign-in and personal-library features; public browsing can run without Clerk

Copy `.env.example` to `.env` and add provider credentials. Copy `frontend/.env.example` to `frontend/.env.local` for Clerk. If running the backend with Clerk, copy `backend/.env.example` to `backend/.env` and set the API's Clerk configuration and allowed frontend origin. Keep all secrets in ignored local environment files.

Start the API:

```sh
cd backend
uv sync --extra test
uv run python -m catalog.database
uv run uvicorn app:app --host 127.0.0.1 --port 8000
```

In another terminal, start the web app:

```sh
cd frontend
npm install
npm run dev
```

Visit [http://localhost:3000](http://localhost:3000). The API listens on port 8000. SQLite is the local default; use `DATABASE_URL_UNPOOLED` for direct PostgreSQL schema setup. `GET /health` checks the process and `GET /health/ready` checks the database.

### Checks

```sh
cd backend
uv run pytest
```

```sh
cd frontend
npm run typecheck
npm run build
```

CI runs backend tests and the frontend typecheck/build on pull requests. See [CONTRIBUTING.md](CONTRIBUTING.md) before opening a PR.

## Missing-title reports and scheduled jobs

`POST /api/missing-titles` accepts a title, media type, and optional reporter email. The API checks the local catalog, refreshes current releases, searches configured providers, and only then records an unresolved report. Email addresses are not included in public GitHub issues.

Issue creation and email notifications require backend configuration for GitHub and Resend. Reporter notifications are sent once a title is publicly available. Catalog refresh and missing-title reconciliation workflows also require GitHub Actions secrets; without them, the related automation will not run. See [staging deployment](docs/staging-deployment.md) and the workflow files under `.github/workflows/` for configuration.

## Source research tools

The repository includes scripts for testing provider connectivity, search coverage, freshness, and bounded API load. Copy `.env.example` to `.env`, then run:

```sh
python3 scripts/source_probe.py validate
python3 scripts/source_probe.py search
python3 scripts/source_probe.py browse --window-days 30
python3 scripts/source_probe.py soak --provider tmdb --duration 60 --rps 1
python3 -m unittest discover -s tests
```

Soak tests are intentionally limited to two requests per second and one hour. For app load testing, use local fixtures rather than placing load on public metadata APIs. The [catalog decision](docs/catalog-decision.md) and [initial live results](docs/live-api-results-2026-10-12.md) explain the current evidence and limits.

The local API explorer can be started with `python3 scripts/web_ui.py`; it listens only on `127.0.0.1:8765` and displays parsed results and JSON requests/responses.

## License and data

Repository code is MIT licensed. Provider data, artwork, and API responses remain subject to their respective providers' terms and are not covered by this repository's license. See [LICENSE](LICENSE).
