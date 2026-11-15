"""Optional PostgreSQL facade for the portable durable engine."""
from contextlib import asynccontextmanager


class Database:
    def __init__(self, pool): self.pool = pool

    @classmethod
    async def connect(cls, dsn):
        try: import asyncpg
        except ImportError:
            from .errors import Invalid
            raise Invalid('Install dm-engine[postgres] or use the native package for PostgreSQL execution.') from None
        return cls(await asyncpg.create_pool(dsn, min_size=1, max_size=4, command_timeout=30))

    async def close(self): await self.pool.close()
    async def execute(self, query, *args): return await self.pool.execute(query, *args)
    async def fetch_one(self, query, *args):
        row = await self.pool.fetchrow(query, *args)
        return dict(row) if row is not None else None
    async def fetch_all(self, query, *args): return [dict(row) for row in await self.pool.fetch(query, *args)]
    async def fetch_val(self, query, *args): return await self.pool.fetchval(query, *args)

    @asynccontextmanager
    async def atomic(self):
        async with self.pool.acquire() as connection:
            async with connection.transaction(): yield connection
