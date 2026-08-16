import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

import core.runtime as runtime_module
from core import CoreRuntime
from database import SQLiteDatabase

MIGRATIONS = Path(__file__).resolve().parents[2] / 'migrations'


def test_core_runtime_owns_database_services_and_web_server(tmp_path):
    async def scenario():
        runtime = await CoreRuntime.start(
            database_url=f'sqlite:///{tmp_path / "core.sqlite3"}',
            migrations_directory=MIGRATIONS,
            web_host='127.0.0.1',
            web_port=0,
            web_base_url='https://d20.example',
            internal_token='secret',
        )
        assert runtime.web_server._server is not None
        assert runtime.web_base_url == 'https://d20.example'
        await runtime.campaigns.assign_master(-100, 7, 'Campaign')
        assert await runtime.campaigns.is_master(-100, 7)
        assert runtime.web_server._pages._workflows is runtime.workflows
        database = runtime.database
        await runtime.close()
        return database

    database = asyncio.run(scenario())
    assert isinstance(database, SQLiteDatabase)


def test_core_runtime_closes_database_when_start_fails(monkeypatch, tmp_path):
    async def scenario():
        database = AsyncMock()
        monkeypatch.setattr(runtime_module, 'create_database', AsyncMock(return_value=database))
        monkeypatch.setattr(
            runtime_module, 'apply_migrations', AsyncMock(side_effect=RuntimeError('broken'))
        )
        with pytest.raises(RuntimeError, match='broken'):
            await CoreRuntime.start(
                database_url='sqlite:///:memory:',
                migrations_directory=tmp_path,
                web_host='127.0.0.1',
                web_port=0,
                web_base_url='',
                internal_token='secret',
            )
        return database

    database = asyncio.run(scenario())
    database.close.assert_awaited_once_with()
