import asyncio
import json
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import core.events as event_module
from core import CoreClient, CoreClientError, CoreEvent
from core.events import poll_events, process_event
from database import SQLiteDatabase, apply_migrations
from services import CampaignService, OutboxService, SessionService
from web import AdminAccessService, AdminWebServer
from web.session_store import SQLiteWebSessionStore

MIGRATIONS = Path(__file__).resolve().parent.parent / 'migrations'


def test_outbox_persists_until_acknowledged(tmp_path):
    async def scenario():
        database = await SQLiteDatabase.connect(str(tmp_path / 'outbox.sqlite3'))
        await apply_migrations(database, MIGRATIONS)
        outbox = OutboxService(database)
        event_id = await outbox.publish('session_stopped', {'chat_id': -100, 'number': 3})
        pending = await outbox.pending()
        await outbox.acknowledge(event_id)
        delivered = await outbox.pending()
        await database.close()
        return event_id, pending, delivered

    event_id, pending, delivered = asyncio.run(scenario())
    assert pending[0].id == event_id
    assert pending[0].payload == {'chat_id': -100, 'number': 3}
    assert delivered == []


def test_processes_all_outbox_event_types():
    async def scenario():
        bot = SimpleNamespace(
            send_message=AsyncMock(return_value=SimpleNamespace(id=50)),
            pin_chat_message=AsyncMock(),
            unpin_chat_message=AsyncMock(),
        )
        client = SimpleNamespace(set_game_announcement=AsyncMock(), acknowledge_event=AsyncMock())
        events = [
            CoreEvent(
                1,
                'game_scheduled',
                {
                    'chat_id': -100,
                    'session_id': 4,
                    'message': 'Game',
                    'previous_message_id': 40,
                },
            ),
            CoreEvent(
                2,
                'session_started',
                {'chat_id': -100, 'number': 4, 'title': 'Tower', 'announcement_message_id': 50},
            ),
            CoreEvent(3, 'session_stopped', {'chat_id': -100, 'number': 4}),
        ]
        for event in events:
            await process_event(bot, client, event)
        return bot, client

    bot, client = asyncio.run(scenario())
    client.set_game_announcement.assert_awaited_once_with(4, 50)
    bot.pin_chat_message.assert_awaited_once()
    assert bot.unpin_chat_message.await_count == 2
    assert client.acknowledge_event.await_count == 3


def test_rejects_invalid_or_unknown_outbox_event():
    bot = SimpleNamespace(send_message=AsyncMock())
    client = SimpleNamespace(acknowledge_event=AsyncMock())
    with pytest.raises(ValueError, match='chat_id'):
        asyncio.run(process_event(bot, client, CoreEvent(1, 'session_stopped', {})))
    with pytest.raises(ValueError, match='Unknown'):
        asyncio.run(process_event(bot, client, CoreEvent(2, 'unknown', {'chat_id': 1})))
    client.acknowledge_event.assert_not_awaited()


def test_core_client_reads_and_acknowledges_events(monkeypatch):
    request = AsyncMock(
        side_effect=[
            {'events': [{'id': 1, 'type': 'session_stopped', 'payload': {'chat_id': 1}}]},
            {'ok': True},
        ]
    )
    monkeypatch.setattr(CoreClient, '_request', request)

    async def scenario():
        client = CoreClient('http://core', 'secret')
        events = await client.get_events()
        await client.acknowledge_event(events[0].id)
        return events

    events = asyncio.run(scenario())
    assert events[0].event_type == 'session_stopped'
    assert request.await_count == 2


def test_core_client_rejects_invalid_events(monkeypatch):
    monkeypatch.setattr(CoreClient, '_request', AsyncMock(return_value={'events': [None]}))
    with pytest.raises(CoreClientError):
        asyncio.run(CoreClient('http://core', 'secret').get_events())


def test_internal_events_api(tmp_path):
    async def scenario():
        database = await SQLiteDatabase.connect(str(tmp_path / 'events-api.sqlite3'))
        await apply_migrations(database, MIGRATIONS)
        outbox = OutboxService(database)
        server = AdminWebServer(
            AdminAccessService(SQLiteWebSessionStore(database)),
            CampaignService(database),
            SessionService(database),
            outbox,
            internal_token='secret',
        )
        event_id = await outbox.publish('session_stopped', {'chat_id': 1, 'number': 2})
        headers = {'authorization': 'Bearer secret'}
        unauthorized = await server._route('POST', '/api/events', {}, b'action=get')
        pending = await server._route('POST', '/api/events', headers, b'action=get')
        invalid = await server._route('POST', '/api/events', headers, b'action=ack&event_id=x')
        acknowledged = await server._route(
            'POST', '/api/events', headers, f'action=ack&event_id={event_id}'.encode()
        )
        empty = await server._route('POST', '/api/events', headers, b'action=get')
        bad_action = await server._route('POST', '/api/events', headers, b'action=nope')
        await database.close()
        return unauthorized, pending, invalid, acknowledged, empty, bad_action

    results = asyncio.run(scenario())
    assert results[0][0] is HTTPStatus.UNAUTHORIZED
    assert json.loads(results[1][2])['events'][0]['type'] == 'session_stopped'
    assert results[2][0] is HTTPStatus.BAD_REQUEST
    assert results[3][0] is HTTPStatus.OK
    assert json.loads(results[4][2])['events'] == []
    assert results[5][0] is HTTPStatus.BAD_REQUEST


def test_event_poller_processes_batch(monkeypatch):
    event = CoreEvent(1, 'session_stopped', {'chat_id': 1, 'number': 2})
    client = SimpleNamespace(
        get_events=AsyncMock(return_value=(event,)), acknowledge_event=AsyncMock()
    )
    bot = SimpleNamespace(send_message=AsyncMock())
    application = SimpleNamespace(bot_data={'core_client': client}, bot=bot)
    monkeypatch.setattr(
        event_module.asyncio, 'sleep', AsyncMock(side_effect=asyncio.CancelledError)
    )
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(poll_events(application))
    client.acknowledge_event.assert_awaited_once_with(1)
