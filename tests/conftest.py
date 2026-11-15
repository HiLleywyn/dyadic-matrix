from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

import os
import uuid
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
import pytest


@pytest.fixture
async def db(request):
    dsn = os.environ.get('DM_TEST_DSN')
    if not dsn: pytest.skip('Set DM_TEST_DSN to an explicitly disposable PostgreSQL fixture.')
    import asyncpg
    from dm_engine.postgres import Database
    # Own only a new, uniquely named schema. Existing schemas/data are untouched.
    schema = 'dm_test_' + uuid.uuid4().hex
    admin = await asyncpg.connect(dsn)
    await admin.execute('CREATE SCHEMA ' + schema)
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=4, server_settings={'search_path': schema}, command_timeout=10)
    database = Database(pool)
    parsed = urlsplit(dsn)
    database.test_dsn = urlunsplit(parsed._replace(query=urlencode([*parse_qsl(parsed.query), ('search_path', schema)])))
    try:
        if getattr(request, 'param', True):
            await database.execute((Path(__file__).resolve().parents[1]/'src/dm_engine/schema.sql').read_text())
        yield database
    finally:
        await database.close()
        assert schema.startswith('dm_test_') and len(schema) == 40 and schema.isidentifier()
        await admin.execute('DROP SCHEMA ' + schema + ' CASCADE')
        await admin.close()
