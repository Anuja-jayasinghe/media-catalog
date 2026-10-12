# Initial live API results — 2026-10-12

These are connectivity and behavior checks for TMDB and IGDB using local, Git-ignored credentials. They are not a coverage or freshness verdict. Only provider IDs and small result summaries were retained here; no credentials or raw responses are stored in the repository.

## Search smoke test

`python3 scripts/source_probe.py search` searched three movies, three TV series, and three games. All nine expected works appeared in the top five; six appeared first. There were no request errors.

| Media | Expected title | Provider ID | Rank |
| --- | --- | ---: | ---: |
| Movie | The Super Mario Bros. Movie (2023) | 502356 | 1 |
| Movie | Dune (2021) | 438631 | 1 |
| Movie | Parasite (2019) | 496243 | 1 |
| TV | Breaking Bad (2008) | 1396 | 1 |
| TV | The Office (2005) | 2316 | 1 |
| TV | Dark (2017) | 70523 | 2 |
| Game | Hades (2020) | 113112 | 2 |
| Game | Prey (2017) | 19531 | 1 |
| Game | The Legend of Zelda: Breath of the Wild (2017) | 7346 | 4 |

The first result would select the wrong work for *Dark* and *Hades*. For *Breath of the Wild*, a bundle, a multiplayer variant, and DLC preceded the base game. The product must show year, media type, and game edition/platform where available and let the user choose the exact work. Provider rank alone is unsafe for automatic matching.

## Browse and upcoming endpoints

`python3 scripts/source_probe.py browse --window-days 30` checked first pages on 2026-10-12, using a 30-day window. TMDB movie and TV popular discovery each returned 20 records. TMDB's dated movie and TV discovery each returned 20 records on the first page and reported 83 and 12 pages respectively. IGDB's release-date query returned 20 platform-specific release records representing 10 distinct games on its first page. Examples included current-day releases in all three media types.

This shows that browse and dated-release queries are accessible. It does not prove every title is present, that dates are accurate, that later pages are complete, or that a new record arrives promptly. IGDB release records need deduplication by game, with platform and region retained. TMDB date windows need region-specific checks before production use. The probe uses [TMDB discover movie](https://developer.themoviedb.org/reference/discover-movie), [TMDB discover TV](https://developer.themoviedb.org/reference/discover-tv), and [IGDB release dates](https://api-docs.igdb.com/).

## Bounded API checks

Each provider was queried for about one minute at one request per second, using the search fixtures in rotation:

| Provider | Requests | Errors / 429s | p50 | p95 | p99 |
| --- | ---: | ---: | ---: | ---: | ---: |
| TMDB | 61 | 0 | 459 ms | 617 ms | 970 ms |
| IGDB | 61 | 0 | 701 ms | 883 ms | 981 ms |

Commands:

```sh
python3 scripts/source_probe.py search
python3 scripts/source_probe.py browse --window-days 30
python3 scripts/source_probe.py soak --provider tmdb --duration 60 --rps 1
python3 scripts/source_probe.py soak --provider igdb --duration 60 --rps 1
```

## Decision and next evidence

**Provisional finding:** both APIs are usable for a combined search and browse experience. No go/no-go decision is justified yet. Nine familiar titles and a one-minute check cannot establish the complete catalog or dependable updates required by this product.

The next checks in the [source validation plan](source-validation-plan.md) are the independently verified 180-title fixture, pagination and detail-field coverage, a 14-day new-release freshness sample, update-feed/webhook recovery, and a 60-minute provider soak. The eventual application load test should exercise our own cache and database with local fixtures, not stress the public APIs.
