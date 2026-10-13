"""Database-backed provider request budgets shared by all API instances."""

from __future__ import annotations

import time

from .database import ProviderRateWindow, SessionLocal, engine


# Below IGDB's documented four calls per second. These are admission limits,
# not retries; search can serve snapshots when a provider budget is exhausted.
CALLS_PER_SECOND = {"igdb": 2, "tmdb": 8, "tvmaze": 2, "rawg": 2}


class ProviderRateLimited(Exception):
    pass


def reserve_provider_call(provider: str, *, second: int | None = None) -> None:
    """Atomically reserve one call for the current UTC second."""
    limit = CALLS_PER_SECOND[provider]
    bucket = int(time.time()) if second is None else second
    if engine.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    statement = insert(ProviderRateWindow).values(provider=provider, second=bucket, used=1)
    statement = statement.on_conflict_do_update(
        index_elements=["provider", "second"],
        set_={"used": ProviderRateWindow.used + 1},
        where=ProviderRateWindow.used < limit,
    ).returning(ProviderRateWindow.used)
    with SessionLocal.begin() as session:
        if session.scalar(statement) is None:
            raise ProviderRateLimited(f"{provider} request budget exhausted")
