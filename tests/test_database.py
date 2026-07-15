import asyncio
import sqlite3
from pathlib import Path

import pytest

from database import SQLiteDatabase, apply_migrations, create_database
from database.repositories import (
    CampaignRepository,
    CharacterRepository,
    RecapRepository,
    SessionRepository,
)

MIGRATIONS = Path(__file__).resolve().parent.parent / 'migrations'


async def open_database(tmp_path):
    database = await SQLiteDatabase.connect(str(tmp_path / 'test.sqlite3'))
    await apply_migrations(database, MIGRATIONS)
    return database


def test_database_factory_rejects_unsupported_scheme():
    with pytest.raises(ValueError, match='Unsupported database scheme: postgresql'):
        asyncio.run(create_database('postgresql://localhost/d20'))


def test_database_factory_rejects_empty_path():
    with pytest.raises(ValueError, match='path is empty'):
        asyncio.run(create_database('sqlite:///'))


def test_migrations_are_idempotent(tmp_path):
    async def scenario():
        database = await open_database(tmp_path)
        await apply_migrations(database, MIGRATIONS)
        rows = await database.fetch_all('SELECT version FROM schema_migrations')
        await database.close()
        return rows

    assert asyncio.run(scenario()) == [{'version': 1}, {'version': 2}]


def test_invalid_migration_filename_is_rejected(tmp_path):
    (tmp_path / 'invalid.sql').write_text('SELECT 1;', encoding='utf-8')

    async def scenario():
        database = await SQLiteDatabase.connect(':memory:')
        try:
            await apply_migrations(database, tmp_path)
        finally:
            await database.close()

    with pytest.raises(ValueError, match='Invalid migration filename'):
        asyncio.run(scenario())


def test_repositories_cover_recap_lifecycle(tmp_path):
    async def scenario():
        database = await open_database(tmp_path)
        campaigns = CampaignRepository(database)
        characters = CharacterRepository(database)
        sessions = SessionRepository(database)
        recaps = RecapRepository(database)
        campaign = await campaigns.get_or_create(-100, 'Campaign')
        same_campaign = await campaigns.get_or_create(-100)
        character = await characters.register(campaign.id, 42, 'Tilly')
        renamed = await characters.register(campaign.id, 42, 'Tilly Fang')
        session = await sessions.start(campaign.id, 'The tower')
        first = await recaps.add(session.id, character.id, 'We reached the tower.')
        second = await recaps.add(session.id, character.id, 'The door was sealed.')
        entries = await recaps.list_by_session(session.id)
        deleted = await recaps.delete_last(session.id, character.id)
        finished = await sessions.finish(session.id)
        result = {
            'campaign': campaign,
            'same_campaign': same_campaign,
            'renamed': renamed,
            'character': await characters.get_by_user(campaign.id, 42),
            'session': session,
            'active': await sessions.get_active(campaign.id),
            'latest': await sessions.get_latest(campaign.id),
            'sessions': await sessions.list(campaign.id),
            'first': first,
            'second': second,
            'entries': entries,
            'deleted': deleted,
            'finished': finished,
            'remaining': await recaps.list_by_session(session.id),
        }
        await database.close()
        return result

    result = asyncio.run(scenario())
    assert result['campaign'].id == result['same_campaign'].id
    assert result['renamed'].name == 'Tilly Fang'
    assert result['character'].name == 'Tilly Fang'
    assert result['session'].number == 1
    assert result['active'] is None
    assert result['latest'].finished_at is not None
    assert result['sessions'] == [result['latest']]
    assert [entry.position for entry in result['entries']] == [1, 2]
    assert result['first'].text == 'We reached the tower.'
    assert result['second'].text == 'The door was sealed.'
    assert result['deleted'] is True
    assert result['finished'].finished_at is not None
    assert result['remaining'] == [result['first']]


def test_only_one_active_session_is_allowed(tmp_path):
    async def scenario():
        database = await open_database(tmp_path)
        campaign = await CampaignRepository(database).get_or_create(1)
        sessions = SessionRepository(database)
        await sessions.start(campaign.id)
        try:
            await sessions.start(campaign.id)
        finally:
            await database.close()

    with pytest.raises(sqlite3.IntegrityError):
        asyncio.run(scenario())
