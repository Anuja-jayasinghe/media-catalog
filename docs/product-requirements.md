# Product requirements and build plan

Status: confirmed requirements through 2026-10-13. This document records decisions the user confirmed. Items under **Open or feasibility-dependent** are not decisions.

## Product goal

Build an open-source, noncommercial catalog that lets each user find movies, TV series, and games in one place, record what they watched or played, and look back through their history. It must serve multiple users, work well on phones and desktop, and be deployable as a hosted site or by a self-hoster. Catalog coverage and prompt inclusion of new releases are launch-critical. No metadata provider should be described as containing literally every title; missing titles need a fast recovery path.

The [catalog source decision](catalog-decision.md) is a conditional go to begin implementation with TMDB and IGDB. The [initial API results](live-api-results-2026-10-12.md) establish connectivity only; the broader [source validation plan](source-validation-plan.md) is deferred rather than treated as passed.

## Confirmed user-facing requirements

### Discovery and catalog

- One search bar searches movies, TV series, and games together, with suggestions as the user types. Media-type filters are optional.
- Users can browse without a query. The main page includes personalized recommendations based on their tracked titles, ratings, and favorites. Completed and dropped titles do not appear in recommendations; planned and in-progress titles may appear.
- Keep the main page uncluttered: compact new-release and upcoming rows alongside recommendations, with further exploration and filters in a separate Explore area.
- Show current titles, new releases, and upcoming titles when source data exists. New-release notifications are not needed.
- A shared title catalog serves all users. When the primary source misses a title, search supplemental sources and add a verified record quickly; background completion is acceptable.
- A missing title can be reported with minimal friction. If all metadata sources fail, track the unresolved title, create a GitHub issue, and notify an admin. An email address is optional and must not appear in a public issue. Notify that reporter only after the title is available in the public catalog, including when a contributor's PR resolves the issue. If a user dismisses the report prompt during import, still track and file the missing-title issue without interrupting them.
- Offer the same simple report path for incorrect catalog details, including wrong posters, years, and episode lists.

### Personal tracking

- Per-user catalog history is private by default. Each user has one tracking entry per title; separate rewatch or replay records are not required.
- Movies, shows, and games share statuses: planned, in progress, completed, and dropped.
- A completed movie or game may have an exact watched/completed date, a month-only date, or no date. The user can change the date later.
- TV tracking supports show, season, and episode progress. Marking a season watched on the dashboard covers episodes released by that dashboard action's timestamp. Episodes released afterward stay unwatched, even if the user enters an earlier watched date or no date. For a partially watched season, the user can specify the last watched episode.
- For games, users may track across platforms or by platform. An optional game-related acquisition/source response has a working label, **“I'd rather not say.”** Remasters/remakes are separate games; editions and DLC are grouped with the base game.
- Optional fields include a five-star rating in half-star steps, a note/review, favorite status, and custom lists. Empty fields do not create visible labels or gaps. Users can edit ratings and reviews at any time.
- Keep an internal history of user edits and import changes. This log is for operating the service, not a user-facing timeline.
- Statistics are a later phase, after the core product works.

### Import and sync

- First-release import scope includes movies, TV, and games, and all competitor sources under review: Letterboxd, IMDb, Trakt, saved TV Time exports, Steam, Backloggd, HowLongToBeat, and Plex. This is a coverage objective; each path must pass a feasibility and data-quality review before it can be promised as supported.
- Accept file uploads and account connections where the source permits them. Connected accounts import data into this catalog only. Users may run **Sync again** manually and disconnect an account after import. Edits made here are not pushed to a source service.
- Import immediately, then show a results summary. Users can revert a whole import batch or selected changes. Removal from a connected source does not delete or change the local entry and does not trigger a notification.
- Match and merge duplicate titles automatically. If any source says a movie was watched or a game completed, that takes priority over a planned status. Apply episode-level evidence to TV; do not mark an entire series completed merely because some episodes were watched.
- For conflicting watched dates, keep the earliest known date; an undated entry does not replace a known date. For conflicting ratings, keep the most recently updated rating; without comparable timestamps, keep the higher value. Normalize imported ratings onto the five-star scale.
- Combine distinct imported notes/reviews into one entry while preserving the original text and labeling each source.
- For ambiguous title matches, show the system's predicted match first with identifying details and allow quick approval or an alternative choice. If the user skips the choice, use the closest match. Users can review and correct matches later. This fallback can make a wrong match, so preserve source IDs and import provenance for correction and revert.
- If no shared-catalog match exists, try supplemental metadata sources. If still missing, keep a temporary personal entry with its imported status; link it to the public catalog record once that title becomes available.

### Export and backup

- Export is file-based only; there is no account-based push or sync to other services.
- First release offers a simple bulk export. Detailed selection of media types, statuses, dates, or fields is a later improvement.
- Offer generic portable formats with hints about destinations that have been verified to import them. Do not label a service as compatible until its import path has been tested.
- Offer a prominently labeled, full-fidelity native backup that can be reimported and preserves fields that competitor formats may omit.

### Identity, sharing, and deletion

- Use Clerk for the first release. Offer Google, GitHub, email/password, and one-time email-code sign-in. A self-hoster provides their own Clerk application and credentials; [authentication decision](authentication-decision.md) has details. Pluggable authentication is a later improvement.
- An email address serves as the private sign-in identifier; no public username is required at registration. Generate a public display name when sharing is enabled, and let the user change it later. Do not expose the user's email in a shared profile.
- Sharing is off by default. A share link shows the entire personal catalog's titles, statuses, ratings, and lists; notes and reviews remain private. Anyone with the link can view it until the user-set expiration, at most 14 days. The user can revoke the link early.
- Users can delete their account and catalog themselves from settings.

## Open or feasibility-dependent

- The first working slice uses Next.js, FastAPI, Clerk, and a SQLAlchemy data model designed for PostgreSQL. The hosted target is Vercel Hobby with Neon Postgres; the [architecture note](architecture.md) records the current boundaries. The original Python API explorer remains a source-testing tool.
- For Backloggd, HowLongToBeat, and Plex, verify a supported and permitted way to obtain a user's records. Steam's owned/played API data must not be treated as proof of game completion. A saved TV Time export can be imported, but the closed service cannot supply a fresh account connection.
- Exact behavior for conflicting **completed versus dropped** or **in progress versus dropped** statuses has not been agreed. Preserve source evidence until a rule is confirmed.
- The exact optional game acquisition/source field and its choices beyond “I'd rather not say” need specification.
- The visual design, recommendation algorithm, sharing presentation, internal log retention, and admin notification destination remain to be specified. Use Resend for report email delivery as recorded in the [email decision](email-decision.md).
- A self-hosted first-release installation depends on Clerk. Fully offline or Clerk-free authentication requires the future pluggable-auth work.

## Build and verification sequence

1. **Proceed from the conditional catalog decision.** Begin implementation with TMDB and IGDB, preserving the missing-title and supplemental-source paths. The 180-title coverage study, 14-day freshness sample, and longer soak in the [source validation plan](source-validation-plan.md) are deferred. Revisit them if real users find gaps or before claiming comprehensive catalog coverage.
2. **Test import sources.** For each competitor, capture representative user-export fixtures or documented account API responses, permitted access route, fields available, identifiers, dates, episode/game-progress fidelity, rate limits, and a reversible test import. Mark unsupported routes explicitly rather than silently dropping titles. Test cross-source matching against remakes, same-name works, DLC, and TV episodes.
3. **Build the shared catalog and identity foundation.** Implement provider adapters, canonical title IDs and aliases, deduplication, freshness reconciliation, search suggestions, browse pages, Clerk sign-in, and per-user data isolation. Verify new releases arrive without manual title entry.
4. **Build tracking and import.** Add the status/date/episode/game models; import provenance; conflict rules; temporary entries; ambiguity review; manual sync; disconnect; summary; and batch or selective revert. Test correction of a wrong match and later resolution of a temporary title.
5. **Build export, sharing, and operations.** Add generic bulk exports and native backup/reimport; expiring/revocable share links; account deletion; missing/incorrect-title reporting; private reporter email storage; GitHub issue linkage; and email only after public title availability.
6. **Run an end-to-end release gate.** Test phone and desktop flows, private-by-default access, search-to-track, season cutoff with newly released episodes, source outage recovery, import and revert, backup round trip, share expiry/revocation, account deletion, and issue-to-publication notification. Load-test our own service using local fixtures, not public metadata APIs.

Later improvements: statistics, selective exports, pluggable authentication, and any source integration that lacks a permitted first-release import path.
