# Hosted deployment decision

Decision date: 2026-10-13
Status: staging deployment created; public release remains pending

Use Vercel Hobby for the project's public, noncommercial hosted release. Keep the application self-hostable. The initial user count is expected to fit the selected providers' free tiers. If usage grows beyond them, migrate the affected service or hosting arrangement at that time.

## Proposed hosted components

| Component | Initial choice | Cost boundary |
| --- | --- | --- |
| Web app | Next.js on Vercel Hobby | Free for personal, noncommercial use within Vercel's resource limits. A `vercel.app` address avoids buying a website domain. |
| Python API | FastAPI on Vercel Functions | Supported as a single function; design endpoints for stateless, bounded execution. |
| Database | Neon Postgres free plan | Separate provider plan, currently 1 GB storage and 100 CU-hours per project per month. Measure catalog growth before promising it fits. |
| Authentication | Clerk free plan | The [authentication decision](authentication-decision.md) applies; monitor its separate limits. |
| Source updates | GitHub Actions invoking a bounded API endpoint | The release refresh runs every two weeks. Search-time fallback and explicit missing-title reconciliation handle titles discovered between runs. |
| Large import files | Direct upload to temporary object storage, if needed | Vercel Functions limit request and response bodies to 4.5 MB. Vercel Blob has a Hobby allowance, but a cleanup policy and usage checks are required. |
| Report email | Resend free plan | Currently includes 3,000 transactional emails per month and 100 per day. The owner can verify a subdomain of an existing domain; [email decision](email-decision.md) has the workflow. |

## Architecture implications

- Do not depend on an always-running Python worker for the Vercel deployment. Keep refresh and import work resumable and idempotent, with short batches that fit function duration and API rate limits.
- A two-week scheduled catalog check can discover releases automatically. It cannot prove that every new release is public immediately; measure provider freshness and end-to-end update lag before launch.
- Search missing titles against the configured providers on demand, then use the missing-title workflow already specified in the [product requirements](product-requirements.md).
- Track Vercel function, transfer, and storage usage, plus Neon database size and compute. Stay on free tiers for the initial release; plan a migration when sustained usage approaches a limit. A reached limit may pause an affected feature until its allowance resets or migration is complete.
- Keep deployment settings, credentials, and provider integrations in environment variables. Self-hosted installations supply their own accounts and keys.

## References checked on 2026-10-13

- [Vercel Hobby plan and limits](https://vercel.com/docs/plans/hobby)
- [Vercel FastAPI deployment](https://vercel.com/docs/frameworks/backend/fastapi)
- [Vercel Functions payload limit](https://vercel.com/docs/functions/limitations)
- [Vercel Blob Hobby allowance](https://vercel.com/docs/vercel-blob/usage-and-pricing)
- [Neon free plan](https://neon.com/blog/neon-free-plan-1-gb-per-project)
- [Vercel default domain](https://vercel.com/docs/domains/working-with-domains)
- [Resend free email tier](https://resend.com/pricing) and [verified-domain requirement](https://resend.com/docs/dashboard/domains/introduction)
