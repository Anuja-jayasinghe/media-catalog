# Catalog release refresh

The shared catalog grows when a visitor searches or browses. A GitHub Actions job runs every two weeks, starting Sunday 2026-10-18 at 04:37 UTC. It calls `POST /api/internal/refresh` once for each of the six recent/upcoming movie, TV, and game lanes. Each call refreshes page one and one deeper page. Deep-page cursors are stored in PostgreSQL; a lane is visited again at the next scheduled run. A failed deeper page is retried on that visit. A failed first page returns HTTP 503 for that lane while the job continues with the others and reports failure at the end.

When someone reports a missing title, the API first checks local exact matches. If none can be selected, it refreshes the first recent and upcoming pages for that media type, then checks again. A successful per-title refresh is cached for one hour to avoid repeatedly calling providers for duplicate reports. If the title is still missing, the existing provider search, ambiguity choices, and deduplicated report flow run. A “None of these” report records the rejected title IDs so later reconciliation cannot resolve it to one of those works. The manual `workflow_dispatch` path refreshes all six lanes regardless of the two-week schedule.

Recent and upcoming pages are ordered by release date. The moving date windows currently cover roughly 90 days back and 180 days ahead. Popular pages continue to use provider popularity. Changed dates, names, and artwork update existing titles when their provider ID matches. Exact external IDs connect titles across providers. Missing-title reconciliation remains a separate hourly job.

## Enable the job

1. Run `cd backend && uv run python -m catalog.database` against the target database using `DATABASE_URL_UNPOOLED` for schema setup. This adds `provider_rate_windows` and `catalog_refresh_cursors` and the report's rejected-ID field.
2. Set `CATALOG_JOB_TOKEN` on the backend. Store the same value as a GitHub Actions secret.
3. Set `CATALOG_API_URL` as a GitHub Actions secret to the backend's public HTTPS origin, with no path or trailing slash.
4. Merge [the workflow](../.github/workflows/refresh-catalog.yml) into the default branch. GitHub runs schedules from that branch. Use `workflow_dispatch` for the first run and check its output. GitHub cron checks weekly; the workflow skips alternate weeks for a two-week cadence.

If either Actions secret is absent, the workflow logs a skip and does not refresh. The endpoint returns HTTP 503 when its token is absent. Keep the token server side.

Every provider request reserves a per-second slot in the shared database before calling TMDB, IGDB, TVmaze, or RAWG. This limits IGDB to two calls per second across API instances and caps other providers conservatively. A request waits for one new budget window before failing. Each scheduled refresh removes counter rows older than one day. This is an admission budget, not a guarantee about provider uptime, daily quotas, or IGDB's simultaneous-request limit. Watch job failures and provider 429s before increasing traffic.

## Coverage measurement

`source_probe.py search` emits minimal JSONL results. `coverage_report.py` grades exact provider IDs at ranks one and five by media type and fixture bucket. It only reports the planned target as met when the fixture has 180 independently checked works, ten per bucket and media type, and every result is graded without an error. For example:

```sh
python3 scripts/source_probe.py search --fixture fixtures/smoke.json --delay 1 > /tmp/catalog-search.jsonl
python3 scripts/coverage_report.py --fixture fixtures/smoke.json --results /tmp/catalog-search.jsonl
```

The 2026-10-13 smoke run found nine of nine titles within the first five primary-provider results, six at rank one, with no query errors. The fixture has no upcoming title, only one independent/obscure game, and no independent reference URLs. It is a connectivity check. It cannot validate the 95% top-five coverage target or the new-release freshness targets in [the source validation plan](source-validation-plan.md).

The remaining launch evidence is the independently checked 180-title fixture, a 14-day new-release sample, and a bounded provider and service load study. The refresh job does not yet consume TMDB change lists or IGDB webhooks. It also does not reconcile deletions or platform-specific game release dates. These need measured coverage and a follow-up design before the catalog can be described as comprehensive.
