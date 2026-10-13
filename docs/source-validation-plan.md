# Source validation plan

Current product cadence: a shared-catalog refresh every two weeks, with live browse/search and a targeted freshness check before a missing-title report. The daily sync described in Phase 3 is an earlier test proposal, not the configured schedule. Its 48-hour target therefore measures live provider discoverability and on-demand availability rather than scheduled preloading alone.

## Decision to make

Can TMDB and IGDB support one searchable, browsable catalog for movies, TV series, and games, including new and upcoming releases, without manual entry of each title?

The result is a written **go / conditional go / no-go** decision. The test must measure coverage and freshness rather than assume that any provider contains every title. A missing-title submission path is required even if the primary sources pass.

## Sources and boundaries

- **TMDB:** movie and TV text search, detail lookup, discover filters, daily ID exports, and movie/TV change lists. Review its current noncommercial license, required attribution, and six-month cache limit before testing or storing responses.
- **IGDB:** game search, details, platform and regional release dates, and create/update/delete webhooks. Use server-side Twitch application credentials. Respect the documented four-request-per-second limit and maximum eight open requests.
- **Supplemental candidates:** assess TheTVDB for film/TV and RAWG for games only after identifying a specific coverage gap. Do not combine their records merely by matching names.
- The MIT license in this repository applies only to our work. It does not grant rights to redistribute provider metadata or artwork.

Record the provider terms URL, date reviewed, API plan, attribution requirement, data retention rule, and allowed use in the final report. Recheck these before public deployment.

## Phase 1 — Build a ground-truth title set

Create a versioned, manually checked fixture of **180 titles: 60 movies, 60 TV series, and 60 games**. For each media type include ten titles in each bucket:

1. Popular recent releases.
2. Older catalog titles.
3. Non-English or regionally popular titles.
4. Obscure, independent, or low-popularity titles.
5. Announced upcoming titles, including some without an exact release date.
6. Ambiguous titles: remakes, same-name works, alternate titles, punctuation, or different years.

For every fixture record, save the expected title, media type, year (if known), country/language or game platform where relevant, an independent reference URL, and a note explaining the expected match. Do not copy provider descriptions or artwork into fixtures. Include TV series with multiple seasons and games with remasters, ports, DLC, and editions. Keep the fixture representative of the regions and languages the product intends to support.

## Phase 2 — Search and browse coverage

Build a small repeatable test harness, using credentials from local environment variables. Query each primary provider with the fixture's natural search term, then with alternate or localized titles where applicable. Save request parameters, timestamp, response status, provider IDs, ranks, and a *minimal* result summary allowed by provider terms. Review uncertain matches manually.

Measure:

- Exact-work recall at ranks 1 and 5, overall and by bucket/media type.
- Wrong-work matches among the first five results, especially same-name remakes.
- Presence of title, type, year, synopsis, artwork reference, and release date; for games, platform-specific dates.
- Search behavior for aliases, accents, non-Latin scripts, punctuation, and misspellings.
- Discover/browse coverage across genre, year, region, popularity, and release window; pagination depth and duplicate frequency.
- TV season/episode coverage and whether new episodes appear under an existing series rather than as separate series.

**Initial acceptance targets:** at least 95% correct-work recall in the top five overall; at least 90% in each media-type and fixture bucket; no automatic selection of an incorrect work during catalog search. These are product targets, not claims about the providers. Review any failed bucket before lowering a target or adding a second source. The separate import flow may use its predicted closest match after presenting an ambiguity prompt that the user skips; it must preserve provenance so the user can correct that match later.

## Phase 3 — New-release and update freshness

For 14 consecutive days, sample newly released and newly announced titles in each media type. Compare independent announcement/release timestamps with when the provider first exposes the correct record and date. Recheck a rotating set of upcoming titles for postponements, region/platform date changes, cancellations, and title renames.

Test a proposed daily sync:

- TMDB: reconcile daily ID exports, consume movie/TV change lists, and query rolling past/future release windows. The ID export is an ID list, not a full metadata dump.
- IGDB: receive and authenticate create/update/delete webhooks, replay missed events safely, and reconcile release-date windows daily.
- Verify idempotency, retries, pagination, missed-day recovery, deletion handling, and corrected release dates.

**Initial acceptance targets:** at least 95% of sampled new releases discoverable within 48 hours of release, and at least 99% within seven days. Record separate figures for each media type and region. If the provider record is late, report provider lag separately from our sync lag.

## Phase 4 — Reliability and stress tests

There are two distinct tests:

1. **Provider integration soak test:** run bounded search/detail/discover traffic at a realistic expected rate for 60 minutes, then a low-volume scheduled check for seven days. Record latency percentiles, timeouts, 429s, 5xx responses, credential refreshes, and recovery. Use exponential backoff and obey `Retry-After`. Keep IGDB below its four-request-per-second limit; start lower and do not intentionally overwhelm either service.
2. **Our own service load test:** once a search adapter exists, use recorded or synthetic fixtures to simulate 100, then 1,000 concurrent users searching and scrolling. This tests our cache, database, pagination, deduplication, and per-user state without turning public APIs into load-test targets. Measure p50/p95/p99 latency, error rate, throughput, memory, and cache hit rate. Set final performance thresholds after a baseline run and expected hosting capacity are known.

Also test provider outage behavior: stale-but-allowed cached results, clear retry behavior, and preserving each user's tracked titles if a provider is temporarily unavailable. Never commit credentials, raw response dumps, or personal user data.

## Phase 5 — Report and decision

Publish a dated report containing the fixture definition, coverage table, missing-title list, freshness distribution, load-test graphs, request volume, provider errors, current terms review, and recommended architecture. Keep reproducible scripts and redacted outputs in the repo.

- **Go:** targets pass and the providers' terms support the intended free, open-source deployment.
- **Conditional go:** a limited bucket fails but has a lawful supplemental source or a practical user-submission path; record the exact gap and mitigation.
- **No-go:** major title groups cannot be found, new releases are routinely late, or provider terms prevent the intended product.

Do not implement the full tracking product until this decision is reviewed.

## Primary references

- TMDB finding data: https://developer.themoviedb.org/docs/finding-data
- TMDB daily ID exports: https://developer.themoviedb.org/docs/daily-id-exports
- TMDB change tracking: https://developer.themoviedb.org/docs/tracking-content-changes
- TMDB FAQ and attribution: https://developer.themoviedb.org/docs/faq
- TMDB API terms: https://www.themoviedb.org/api-terms-of-use
- IGDB API, limits, webhooks, and usage FAQ: https://api-docs.igdb.com/
- TheTVDB API licensing: https://thetvdb.com/api-information
- RAWG API plans and terms: https://rawg.io/apidocs and https://rawg.io/tos_api
