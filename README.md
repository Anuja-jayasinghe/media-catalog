# Media Catalog

An open-source, personal catalog for movies, TV series, and video games. The intended product will let each user search and browse a shared title catalog, then track what they have watched or played.

The confirmed product requirements and phased build plan are in [docs/product-requirements.md](docs/product-requirements.md). The first-release [architecture](docs/architecture.md), [authentication](docs/authentication-decision.md), [hosting](docs/hosting-decision.md), and [email](docs/email-decision.md) choices are documented separately. See [Neon setup](docs/neon-setup.md) and [Clerk setup](docs/clerk-setup.md) to connect your own services.

This repository began with source validation. The [catalog source decision](docs/catalog-decision.md) records a conditional go for product implementation based on the initial API checks and the planned missing-title flow. The broader [source validation plan](docs/source-validation-plan.md) remains available for measuring coverage, freshness, and reliability.

## Candidate sources

| Media | Primary candidate | Documentation |
| --- | --- | --- |
| Movies and TV | TMDB | https://developer.themoviedb.org/docs/finding-data |
| TV fallback | TVmaze | https://www.tvmaze.com/api |
| Games | IGDB | https://api-docs.igdb.com/ |
| Game fallback, optional | RAWG | https://rawg.io/apidocs |

TVmaze is queried only when TMDB has no close series match. RAWG is queried only when IGDB has no close game match and `RAWG_API_KEY` is configured. TheTVDB remains a possible later integration. Provider terms, attribution, caching rules, and rate limits must be reviewed before public deployment. Each deployed instance should supply its own credentials; API keys and secrets must never be committed to this repository or sent to a browser.

## Status

The product slice includes a Next.js interface, separate movie, TV series, and game discovery pages, unified search with grouped results, a shared title table, and Clerk-protected personal library endpoints. Each discovery page loads additional provider results as the user scrolls. A title opens an available trailer; without one, it opens a verified provider or IMDb page. Search can use supplemental TVmaze or RAWG results when primary sources have no close match. Exact provider and external IDs identify titles; aliases help search but never merge two titles on name alone. Search includes a short missing-title form that checks sources first, offers choices when names are ambiguous, then queues a deduplicated report. The frontend supports public discovery without Clerk configuration; saving requires a Clerk application. Full catalog indexing, personalized recommendations, seasons, and imports remain planned. Catalog coverage and new-release freshness are still unmeasured beyond the initial smoke tests.

The current mobile and desktop [interface direction](docs/interface-design.md) is a design iteration for review.

## Run the product slice locally

The existing root `.env` supplies TMDB and Twitch credentials to the Python API. To configure sign-in, copy `frontend/.env.example` to `frontend/.env.local` and `backend/.env.example` to `backend/.env`. Put your Clerk publishable and secret keys in the frontend file. Put the Clerk secret key and allowed frontend origin in the backend file. `CLERK_JWT_KEY` is optional when the backend can fetch Clerk's public keys. Set the provider credentials in the backend file if they are not already in the root `.env`. Keep all secret keys out of Git.

In one terminal:

```sh
cd backend
uv sync --extra test
uv run python -m catalog.database
uv run uvicorn app:app --host 127.0.0.1 --port 8000
```

In a second terminal:

```sh
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`. The home page shows recent and upcoming titles in separate media sections. Movies, TV series, and Games each have Popular, New releases, and Coming soon collections that load more titles while scrolling. Search begins after two characters and groups results by media type. Use the plus control on a poster to track a title; opening the poster shows a trailer when available or sends you to its source page. Sign in to save a tracking status and see it in **My library**. SQLite is the local default; the hosted deployment uses PostgreSQL through the pooled `DATABASE_URL`. Set `DATABASE_URL_UNPOOLED` to Neon's direct URL before running `python -m catalog.database` for production schema setup. See the [architecture note](docs/architecture.md) for the API and data model.

`GET /health` checks the API process. `GET /health/ready` also checks the configured database and returns HTTP 503 if it cannot be queried.

The browse API accepts `section=popular|recent|upcoming`, `media_type=movie|tv|game`, and `page=1..500`; responses include `has_more`. `GET /api/titles/{title_id}/media` resolves a trailer and external title link on demand. Provider pagination limits still apply.

## Missing-title operations

`POST /api/missing-titles` accepts a title name, media type, and optional reporter email. The API checks the local catalog, refreshes current release pages for that media type, then searches providers before creating a report. If multiple exact names exist, it returns choices for the visitor to select; only “None of these” forces a report. Duplicate reports and subscriber addresses are stored once. Email addresses are stored in the database and are never included in public GitHub issues.

Configure `GITHUB_TOKEN` and `GITHUB_REPOSITORY` in the **backend** environment to create a public issue for each unresolved report. Configure `RESEND_API_KEY`, `REPORT_FROM_EMAIL`, `ADMIN_EMAIL`, and `PUBLIC_CATALOG_URL` to notify the administrator and email optional subscribers after a title is available through the public catalog endpoint. Configure `CATALOG_JOB_TOKEN` in the backend and set the same token plus `CATALOG_API_URL` as GitHub Actions secrets. The [reconciliation workflow](.github/workflows/reconcile-missing-titles.yml) runs hourly, after pushes to `main` (including merged PRs), and on manual dispatch. It retries unresolved reports and sends each subscriber one publication email. Without these settings, reports remain in the database for later processing; issue creation and email delivery are not active.

Run `python -m catalog.database` when upgrading an existing database. It creates the new identity/report tables, adds missing report metadata columns, and backfills existing title identities and aliases. Production PostgreSQL keeps automatic runtime schema changes disabled.

## First probes

Copy `.env.example` to `.env` and fill in the TMDB API read token and Twitch application credentials. `.env` is ignored by Git. Python 3.10+ is sufficient; the probe uses only the standard library.

```sh
python3 scripts/source_probe.py validate
python3 scripts/source_probe.py search
python3 scripts/source_probe.py browse --window-days 30
python3 scripts/source_probe.py soak --provider tmdb --duration 60 --rps 1
python3 scripts/source_probe.py soak --provider igdb --duration 60 --rps 1
python3 -m unittest discover -s tests
```

The nine-title fixture is an initial connectivity check, not the 180-title coverage study. Search results with no verified provider ID require manual review. Run `python3 scripts/coverage_report.py --results /path/to/search-results.jsonl` to grade a saved search run. The [catalog freshness guide](docs/catalog-freshness.md) explains the two-week release refresh, report-triggered freshness check, shared provider request budget, and remaining coverage work. The soak command is deliberately capped at two requests per second and one hour; the future application load test will use local fixtures rather than public API traffic.

See the [initial live API results](docs/live-api-results-2026-10-12.md) for the first search, browse, and bounded soak findings.

## Local API explorer

Run the web UI with the same Git-ignored `.env` file:

```sh
python3 scripts/web_ui.py
```

Open `http://127.0.0.1:8765` to search movies, TV series, or games. Each search shows parsed result cards plus the redacted provider request, complete JSON response, and normalized JSON fields. TMDB and IGDB credentials stay on the local Python server. The server listens only on `127.0.0.1`; use `--port` to choose another local port. Stop it with Ctrl+C.

## License

The original code and documentation in this repository are MIT licensed. Third-party catalog data, artwork, and API responses retain their providers' terms and are not covered by this license.
