import asyncio
from datetime import datetime
from pathlib import Path

import pytest

from database import SQLiteDatabase, apply_migrations, create_database
from database.repositories import (
    ActiveSessionExistsError,
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

    assert asyncio.run(scenario()) == [
        {'version': 1},
        {'version': 2},
        {'version': 3},
        {'version': 4},
        {'version': 5},
        {'version': 6},
        {'version': 7},
    ]


def test_schedule_migration_preserves_sessions_recaps_and_planned_game(tmp_path):
    async def scenario():
        migration_dir = tmp_path / 'migrations'
        migration_dir.mkdir()
        for version in range(1, 4):
            source = next(MIGRATIONS.glob(f'{version:03}_*.sql'))
            (migration_dir / source.name).write_text(source.read_text(encoding='utf-8'))

        database = await SQLiteDatabase.connect(str(tmp_path / 'upgrade.sqlite3'))
        await apply_migrations(database, migration_dir)
        campaign_row = await database.fetch_one(
            """INSERT INTO campaigns (chat_id, title, created_at)
            VALUES (?, ?, ?) RETURNING *""",
            (-100, 'Campaign', '2026-07-01T12:00:00+00:00'),
        )
        assert campaign_row is not None
        campaign_id = int(campaign_row['id'])
        character = await CharacterRepository(database).register(campaign_id, 42, 'Tilly')
        session = await database.fetch_one(
            """INSERT INTO sessions (campaign_id, number, title, started_at)
            VALUES (?, 1, ?, ?) RETURNING *""",
            (campaign_id, 'Old session', '2026-07-10T16:00:00+00:00'),
        )
        assert session is not None
        session_id = int(session['id'])
        await RecapRepository(database).add(session_id, character.id, 'Still here.')
        await database.execute(
            """INSERT INTO game_schedules
            (chat_id, scheduled_at, foundry_url, message_id, updated_at)
            VALUES (?, ?, ?, ?, ?)""",
            (
                -100,
                '2026-07-20T16:00:00+00:00',
                'https://foundry.example',
                123,
                '2026-07-15T12:00:00+00:00',
            ),
        )

        source = next(MIGRATIONS.glob('004_*.sql'))
        (migration_dir / source.name).write_text(source.read_text(encoding='utf-8'))
        await apply_migrations(database, migration_dir)

        sessions = await SessionRepository(database).list(campaign_id)
        recaps = await RecapRepository(database).list_by_session(session_id)
        old_table = await database.fetch_one(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'game_schedules'"
        )
        await database.close()
        return sessions, recaps, old_table

    sessions, recaps, old_table = asyncio.run(scenario())
    assert len(sessions) == 2
    assert sessions[0].started_at is not None
    assert sessions[1].scheduled_at == datetime.fromisoformat('2026-07-20T16:00:00+00:00')
    assert sessions[1].started_at is None
    assert sessions[1].foundry_url == 'https://foundry.example'
    assert sessions[1].message_id == 123
    assert recaps[0].text == 'Still here.'
    assert old_table is None


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

    with pytest.raises(ActiveSessionExistsError):
        asyncio.run(scenario())


def test_planned_session_is_rescheduled_then_started(tmp_path):
    async def scenario():
        database = await open_database(tmp_path)
        campaign = await CampaignRepository(database).get_or_create(1)
        sessions = SessionRepository(database)
        first = await sessions.schedule(
            campaign.id,
            datetime.fromisoformat('2026-07-20T16:00:00+00:00'),
            'https://foundry.example/first',
        )
        rescheduled = await sessions.schedule(
            campaign.id,
            datetime.fromisoformat('2026-07-27T16:00:00+00:00'),
            'https://foundry.example/second',
        )
        started = await sessions.start(campaign.id, 'Session title')
        result = (
            first,
            rescheduled,
            started,
            await sessions.get_planned(campaign.id),
            await sessions.get_active(campaign.id),
            await sessions.list(campaign.id),
        )
        await database.close()
        return result

    first, rescheduled, started, planned, active, all_sessions = asyncio.run(scenario())
    assert rescheduled.id == first.id == started.id
    assert rescheduled.number == 1
    assert rescheduled.foundry_url == 'https://foundry.example/second'
    assert started.title == 'Session title'
    assert started.started_at is not None
    assert planned is None
    assert active == started
    assert all_sessions == [started]
