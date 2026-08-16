import asyncio
from datetime import UTC, datetime
from pathlib import Path

from database import SQLiteDatabase, apply_migrations
from database.repositories import SessionRepository
from services import (
    CampaignService,
    PlayerRegistrationStatus,
    SessionService,
    SessionStartStatus,
    SessionStopStatus,
)

MIGRATIONS = Path(__file__).resolve().parent.parent / 'migrations'


async def open_database(tmp_path, name: str):
    database = await SQLiteDatabase.connect(str(tmp_path / name))
    await apply_migrations(database, MIGRATIONS)
    return database


def test_campaign_service_assigns_roles_and_updates_character(tmp_path):
    async def scenario():
        database = await open_database(tmp_path, 'campaign-service.sqlite3')
        service = CampaignService(database)

        campaign = await service.assign_master(-100, 7, 'Campaign')
        master_registration = await service.register_player(-100, 7, 'Мастер')
        first = await service.register_player(-100, 8, 'Тилли')
        updated = await service.register_player(-100, 8, 'Ада')

        await database.close()
        return campaign, master_registration, first, updated

    campaign, master_registration, first, updated = asyncio.run(scenario())
    assert campaign.master_user_id == 7
    assert master_registration.status is PlayerRegistrationStatus.MASTER_CONFLICT
    assert master_registration.character is None
    assert first.character is not None
    assert updated.character is not None
    assert updated.character.id == first.character.id
    assert updated.character.name == 'Ада'


def test_campaign_roles_are_scoped_to_each_campaign(tmp_path):
    async def scenario():
        database = await open_database(tmp_path, 'campaign-memberships.sqlite3')
        service = CampaignService(database)
        await service.assign_master(-100, 7, 'First')
        await service.register_player(-100, 8, 'Bob')
        await service.assign_master(-200, 8, 'Second')
        await service.register_player(-200, 7, 'Alice')

        first = await service.get_roster(-100)
        second = await service.get_roster(-200)
        alice_campaigns = await service.list_for_user(7)
        bob_campaigns = await service.list_for_user(8)
        roles = (
            await service.is_master(-100, 7),
            await service.is_master(-200, 7),
            await service.is_master(-100, 8),
            await service.is_master(-200, 8),
        )
        await database.close()
        return first, second, alice_campaigns, bob_campaigns, roles

    first, second, alice_campaigns, bob_campaigns, roles = asyncio.run(scenario())
    assert first is not None and [
        (member.telegram_user_id, member.role) for member in first.memberships
    ] == [
        (7, 'master'),
        (8, 'player'),
    ]
    assert second is not None and [
        (member.telegram_user_id, member.role) for member in second.memberships
    ] == [(8, 'master'), (7, 'player')]
    assert [campaign.title for campaign in alice_campaigns] == ['First', 'Second']
    assert [campaign.title for campaign in bob_campaigns] == ['First', 'Second']
    assert roles == (True, False, False, True)


def test_campaign_service_renames_and_removes_player_without_deleting_character(tmp_path):
    async def scenario():
        database = await open_database(tmp_path, 'campaign-player-management.sqlite3')
        service = CampaignService(database)
        await service.assign_master(-100, 7, 'Campaign')
        await service.register_player(-100, 8, 'Tilly')
        renamed = await service.rename_player(-100, 8, 'Tilly Fang')
        removed = await service.remove_player(-100, 8)
        roster = await service.get_roster(-100)
        retained = await database.fetch_one(
            'SELECT name FROM characters WHERE telegram_user_id = 8'
        )
        missing_rename = await service.rename_player(-100, 8, 'Hidden')
        repeated_remove = await service.remove_player(-100, 8)
        await database.close()
        return renamed, removed, roster, retained, missing_rename, repeated_remove

    renamed, removed, roster, retained, missing_rename, repeated_remove = asyncio.run(scenario())
    assert renamed is not None and renamed.name == 'Tilly Fang'
    assert removed
    assert roster is not None and roster.characters == ()
    assert retained == {'name': 'Tilly Fang'}
    assert missing_rename is None
    assert not repeated_remove


def test_campaign_service_transfers_master_and_keeps_previous_master_as_player(tmp_path):
    async def scenario():
        database = await open_database(tmp_path, 'campaign-master-transfer.sqlite3')
        service = CampaignService(database)
        await service.assign_master(-100, 7, 'Campaign')
        await service.register_player(-100, 8, 'Tilly')
        transferred = await service.transfer_master(-100, 7, 8)
        roster = await service.get_roster(-100)
        roles = await service.get_role(-100, 7), await service.get_role(-100, 8)
        repeated = await service.transfer_master(-100, 7, 8)
        outsider = await service.transfer_master(-100, 8, 9)
        await database.close()
        return transferred, roster, roles, repeated, outsider

    transferred, roster, roles, repeated, outsider = asyncio.run(scenario())
    assert transferred
    assert roster is not None and roster.campaign.master_user_id == 8
    assert roles == ('player', 'master')
    assert not repeated and not outsider


def test_session_service_schedules_and_replaces_announcement(tmp_path):
    async def scenario():
        database = await open_database(tmp_path, 'schedule-service.sqlite3')
        service = SessionService(database)
        scheduled_at = datetime(2026, 7, 20, 16, tzinfo=UTC)

        missing = await service.get_planned(-100)
        first = await service.schedule(-100, 'Campaign', scheduled_at, 'https://first.example')
        await service.set_announcement(first.session.id, 42)
        moved = await service.schedule(
            -100,
            'Campaign',
            datetime(2026, 7, 21, 17, tzinfo=UTC),
            'https://second.example',
        )
        planned = await service.get_planned(-100)

        await database.close()
        return missing, first, moved, planned

    missing, first, moved, planned = asyncio.run(scenario())
    assert missing is None
    assert first.previous_message_id is None
    assert moved.session.id == first.session.id
    assert moved.previous_message_id == 42
    assert planned == moved.session


def test_session_service_stores_default_url(tmp_path):
    async def scenario():
        database = await open_database(tmp_path, 'config-service.sqlite3')
        service = SessionService(database)
        before = await service.get_default_url(-100)
        await service.set_default_url(
            -100, 'https://foundry.example', datetime(2026, 7, 15, 12, tzinfo=UTC)
        )
        after = await service.get_default_url(-100)
        await database.close()
        return before, after

    assert asyncio.run(scenario()) == (None, 'https://foundry.example')


def test_session_service_validates_master_and_lifecycle(tmp_path):
    async def scenario():
        database = await open_database(tmp_path, 'lifecycle-service.sqlite3')
        campaigns = CampaignService(database)
        sessions = SessionService(database)

        forbidden_start = await sessions.start(-100, 8, None)
        forbidden_stop = await sessions.stop(-100, 8)
        await campaigns.assign_master(-100, 7, 'Campaign')
        empty_stop = await sessions.stop(-100, 7)
        planned = await sessions.schedule(
            -100,
            'Campaign',
            datetime(2026, 7, 20, 16, tzinfo=UTC),
            'https://foundry.example',
        )
        await sessions.set_announcement(planned.session.id, 99)

        starts = await asyncio.gather(
            sessions.start(-100, 7, 'Башня'),
            sessions.start(-100, 7, 'Дубль'),
        )
        active = await SessionRepository(database).get_active(planned.session.campaign_id)
        stopped = await sessions.stop(-100, 7)
        second_stop = await sessions.stop(-100, 7)

        await database.close()
        return forbidden_start, forbidden_stop, empty_stop, starts, active, stopped, second_stop

    forbidden_start, forbidden_stop, empty_stop, starts, active, stopped, second_stop = asyncio.run(
        scenario()
    )
    assert forbidden_start.status is SessionStartStatus.FORBIDDEN
    assert forbidden_stop.status is SessionStopStatus.FORBIDDEN
    assert empty_stop.status is SessionStopStatus.NO_ACTIVE_SESSION
    assert sum(result.session is not None for result in starts) == 1
    assert sum(result.status is SessionStartStatus.ALREADY_ACTIVE for result in starts) == 1
    successful = next(result for result in starts if result.session is not None)
    assert successful.announcement_message_id == 99
    assert active is not None
    assert stopped.session is not None
    assert stopped.session.finished_at is not None
    assert second_stop.status is SessionStopStatus.NO_ACTIVE_SESSION


def test_session_start_is_safe_across_database_connections(tmp_path):
    async def scenario():
        path = tmp_path / 'concurrent-service.sqlite3'
        first_database = await SQLiteDatabase.connect(str(path))
        await apply_migrations(first_database, MIGRATIONS)
        second_database = await SQLiteDatabase.connect(str(path))
        await CampaignService(first_database).assign_master(-100, 7, 'Campaign')

        results = await asyncio.gather(
            SessionService(first_database).start(-100, 7, 'First'),
            SessionService(second_database).start(-100, 7, 'Second'),
        )
        rows = await first_database.fetch_all(
            'SELECT * FROM sessions WHERE started_at IS NOT NULL AND finished_at IS NULL'
        )
        await first_database.close()
        await second_database.close()
        return results, rows

    results, rows = asyncio.run(scenario())
    assert {result.status for result in results} == {
        SessionStartStatus.STARTED,
        SessionStartStatus.ALREADY_ACTIVE,
    }
    assert len(rows) == 1
