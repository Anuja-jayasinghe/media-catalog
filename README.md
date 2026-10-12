# Media Catalog

An open-source, personal catalog for movies, TV series, and video games. The intended product will let each user search and browse a shared title catalog, then track what they have watched or played.

This repository begins with source validation. No product implementation or API credentials are included yet. See [the source validation plan](docs/source-validation-plan.md) for the coverage, freshness, reliability, and load tests that must pass before choosing a product architecture.

## Candidate sources

| Media | Primary candidate | Documentation |
| --- | --- | --- |
| Movies and TV | TMDB | https://developer.themoviedb.org/docs/finding-data |
| Games | IGDB | https://api-docs.igdb.com/ |

TheTVDB and RAWG are possible supplemental sources if the primary candidates have measurable gaps. Provider terms, attribution, caching rules, and rate limits must be reviewed before integration. Each deployed instance should supply its own credentials; API keys and secrets must never be committed to this repository or sent to a browser.

## Status

Planning and source evaluation. The first milestone is a reproducible evidence report and a go/no-go decision for TMDB and IGDB.

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

The nine-title fixture is an initial connectivity check, not the 180-title coverage study. Search results with no verified provider ID require manual review. The soak command is deliberately capped at two requests per second and one hour; the future application load test will use local fixtures rather than public API traffic.

See the [initial live API results](docs/live-api-results-2026-10-12.md) for the first search, browse, and bounded soak findings.

## Local API explorer

Run the web UI with the same Git-ignored `.env` file:

```sh
python3 scripts/web_ui.py
```

Open `http://127.0.0.1:8765` to search movies, TV series, or games. Each search shows parsed result cards plus the redacted provider request, complete JSON response, and normalized JSON fields. TMDB and IGDB credentials stay on the local Python server. The server listens only on `127.0.0.1`; use `--port` to choose another local port. Stop it with Ctrl+C.

## License

The original code and documentation in this repository are MIT licensed. Third-party catalog data, artwork, and API responses retain their providers' terms and are not covered by this license.
