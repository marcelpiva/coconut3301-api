import os
from contextlib import asynccontextmanager

import asyncpg

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        database_url = os.environ["DATABASE_URL"]
        _pool = await asyncpg.create_pool(database_url, min_size=2, max_size=10)
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
