# Connect Neon Postgres

Each self-hosted deployment uses its own Neon Postgres project. The repository contains no shared credentials.

1. Create a Neon Postgres project and copy both connection strings from its **Connect** dialog: the pooled URL for application traffic and the direct URL for schema setup.
2. Set `DATABASE_URL` to the pooled URL and `DATABASE_URL_UNPOOLED` to the direct URL in `backend/.env` locally or in the backend hosting environment. Keep `AUTO_CREATE_SCHEMA=0` for PostgreSQL.
3. From `backend/`, run `uv run python -m catalog.database` before starting the API. This schema command uses the direct URL. Repeat it when deploying a schema change.
4. Start the API and request `/health/ready`. A 200 response with `{"status":"ready"}` confirms that the runtime pooled URL can query the database.

The local default remains SQLite when `DATABASE_URL` is unset. Database URLs contain credentials and belong only in ignored local files or your host's secret settings.
