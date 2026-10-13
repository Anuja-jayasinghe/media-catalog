# Catalog source decision

Decision date: 2026-10-13
Decision: **Conditional go for product implementation**

The product will proceed with TMDB as the primary movie/TV candidate and IGDB as the primary game candidate. The user chose to begin architecture and implementation now, relying on supplemental sources, temporary personal entries, and the missing-title report workflow to handle gaps rather than waiting for the full planned source study.

## Evidence available

- The [initial live API results](live-api-results-2026-10-12.md) found all nine smoke-test titles within the first five search results.
- Search, browse, and dated-release endpoints responded during initial checks, including current-day release examples.
- One-minute bounded checks at one request per second returned no errors or rate limits.

## What this decision does not establish

- Coverage beyond the nine familiar test titles, especially obscure or regional works.
- How quickly every new movie, episode, or game appears, or how reliably release-date corrections propagate. New releases are a stated product requirement and this remains an implementation and launch risk.
- Production-scale reliability, provider-term suitability for every deployment, and competitor import feasibility.

The deferred [source validation plan](source-validation-plan.md) remains available if observed gaps or launch-readiness reviews call for it. The missing-title workflow is a mitigation, not a measurement of source completeness.

## Next work

Select the production stack and data model, then build a thin vertical slice: Clerk sign-in, a shared search across TMDB/IGDB, one personal tracking entry, and the missing-title fallback. Add scheduled catalog freshness and source reconciliation before treating new releases as dependable.
