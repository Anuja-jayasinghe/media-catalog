# Staging deployment

The first staging deployment uses two Vercel projects in the `anuja-jayasinghes-projects` scope:

| Service | Project | URL |
| --- | --- | --- |
| Web | `media-catalog-staging-web` | https://media-catalog-staging-web.vercel.app |
| API | `media-catalog-staging-api` | https://media-catalog-staging-api.vercel.app |

Both projects were linked and deployed from their respective `frontend/` and `backend/` directories with the Vercel CLI. The web project uses the Next.js preset; the API project uses the FastAPI preset. The API's `/health/ready` endpoint verifies its Neon connection. Staging uses Clerk development keys and is for testing only. Public sign-in needs a Clerk production instance before a public release.

The API project has its pooled `DATABASE_URL`, Clerk secret, TMDB token, and Twitch credentials in Vercel environment variables. It sets `FRONTEND_ORIGINS` and `CLERK_AUTHORIZED_PARTIES` to the staging web URL, `AUTO_CREATE_SCHEMA=0`, and `PUBLIC_CATALOG_URL` to the staging web URL. The web project has its Clerk keys and `NEXT_PUBLIC_API_BASE_URL` pointing to the staging API. Secret values are not stored in this repository.

Run the schema setup from `backend/` with the direct Neon URL before deploying API changes that add tables or columns:

```sh
uv run python -m catalog.database
```

Deploy each service after its environment is configured:

```sh
cd backend && npx --yes vercel@latest deploy --prod --yes
cd ../frontend && npx --yes vercel@latest deploy --prod --yes
```

These commands target the staging projects, where `--prod` updates the stable staging URLs. They do not create a public release project. Verify `/health/ready`, a fresh provider search, and the browser's browse and search views after a deployment. The projects are currently deployed through the CLI; Git based automatic deployment is not connected yet.

The following services still need launch configuration: Clerk production keys, a report issue credential, Resend sender domain and API key, and GitHub Actions secrets for the two-week refresh and missing-title reconciliation. Native imports over Vercel's request size limit also need a direct upload path.
