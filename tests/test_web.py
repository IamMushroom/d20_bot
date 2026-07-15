import asyncio
import json
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram.error import BadRequest

from commands.admin_commands import (
    ADMIN_ACCESS_KEY,
    CORE_CLIENT_KEY,
    WEB_BASE_URL_KEY,
    admin,
    web_url,
)
from commands.helpers import CAMPAIGN_SERVICE_KEY, SESSION_SERVICE_KEY
from core import CoreClientError
from database import SQLiteDatabase, apply_migrations
from services import CampaignService, SessionService
from web import AdminAccessService, AdminWebServer
from web.access import AdminIdentity

MIGRATIONS = Path(__file__).resolve().parent.parent / 'migrations'


async def setup(tmp_path):
    database = await SQLiteDatabase.connect(str(tmp_path / 'web.sqlite3'))
    await apply_migrations(database, MIGRATIONS)
    campaigns = CampaignService(database)
    sessions = SessionService(database)
    await campaigns.assign_master(-100, 7, 'Campaign')
    access = AdminAccessService()
    bot = SimpleNamespace(
        send_message=AsyncMock(return_value=SimpleNamespace(id=55)),
        pin_chat_message=AsyncMock(),
        unpin_chat_message=AsyncMock(),
    )
    return database, campaigns, sessions, access, bot


def test_admin_access_uses_one_time_logins_and_expiring_sessions():
    access = AdminAccessService()
    identity = AdminIdentity(-100, 7, 'Campaign')
    token = access.create_login(identity)
    session_id = access.consume_login(token)

    assert session_id is not None
    assert access.consume_login(token) is None
    assert access.authenticate(session_id) == identity
    assert access.authenticate(None) is None

    access._sessions[session_id] = (identity, datetime.now(UTC) - timedelta(seconds=1))
    assert access.authenticate(session_id) is None


def test_admin_commands_ignore_updates_without_chat():
    async def scenario():
        update = SimpleNamespace(effective_chat=None, effective_message=None, effective_user=None)
        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()))
        await admin(update, context)
        await web_url(update, context)
        return context.bot

    bot = asyncio.run(scenario())
    bot.send_message.assert_not_awaited()


def test_admin_command_validates_configuration_and_master(tmp_path):
    async def scenario():
        database, campaigns, _sessions, access, bot = await setup(tmp_path)
        update = SimpleNamespace(
            effective_chat=SimpleNamespace(id=-100, title='Campaign'),
            effective_message=SimpleNamespace(id=10),
            effective_user=SimpleNamespace(id=7),
        )
        data = {
            CAMPAIGN_SERVICE_KEY: campaigns,
            SESSION_SERVICE_KEY: _sessions,
            ADMIN_ACCESS_KEY: access,
        }
        context = SimpleNamespace(application=SimpleNamespace(bot_data=data), bot=bot)

        await admin(update, context)
        disabled = bot.send_message.await_args.kwargs['text']
        data[WEB_BASE_URL_KEY] = 'https://d20.example'
        update.effective_user.id = 8
        await admin(update, context)
        forbidden = bot.send_message.await_args.kwargs['text']
        update.effective_user.id = 7
        await admin(update, context)
        private_message = bot.send_message.await_args.kwargs

        await database.close()
        return disabled, forbidden, private_message

    disabled, forbidden, private_message = asyncio.run(scenario())
    assert '/web_url' in disabled
    assert 'только назначенному мастеру' in forbidden
    assert private_message['chat_id'] == 7
    assert 'https://d20.example/login?token=' in private_message['text']


def test_admin_command_reports_private_message_failure(tmp_path):
    async def scenario():
        database, campaigns, _sessions, access, bot = await setup(tmp_path)
        bot.send_message.side_effect = [BadRequest('blocked'), SimpleNamespace(id=1)]
        context = SimpleNamespace(
            application=SimpleNamespace(
                bot_data={
                    CAMPAIGN_SERVICE_KEY: campaigns,
                    SESSION_SERVICE_KEY: _sessions,
                    ADMIN_ACCESS_KEY: access,
                    WEB_BASE_URL_KEY: 'http://localhost:8190',
                }
            ),
            bot=bot,
        )
        update = SimpleNamespace(
            effective_chat=SimpleNamespace(id=-100, title='Campaign'),
            effective_message=SimpleNamespace(id=10),
            effective_user=SimpleNamespace(id=7),
        )
        await admin(update, context)
        await database.close()
        return bot.send_message.await_args.kwargs['text']

    assert 'личные сообщения' in asyncio.run(scenario())


def test_admin_command_uses_connected_core_client():
    client = SimpleNamespace(create_admin_link=AsyncMock(return_value='https://d20.example/login'))
    bot = SimpleNamespace(send_message=AsyncMock())
    context = SimpleNamespace(
        application=SimpleNamespace(bot_data={CORE_CLIENT_KEY: client}), bot=bot
    )
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-100, title='Campaign'),
        effective_message=SimpleNamespace(id=10),
        effective_user=SimpleNamespace(id=7),
    )

    asyncio.run(admin(update, context))

    client.create_admin_link.assert_awaited_once_with(-100, 7, 'Campaign')
    assert bot.send_message.await_args.kwargs['chat_id'] == 7


def test_admin_command_reports_connected_core_error():
    client = SimpleNamespace(
        create_admin_link=AsyncMock(side_effect=CoreClientError('unavailable'))
    )
    bot = SimpleNamespace(send_message=AsyncMock())
    context = SimpleNamespace(
        application=SimpleNamespace(bot_data={CORE_CLIENT_KEY: client}), bot=bot
    )
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-100, title=None),
        effective_message=SimpleNamespace(id=10),
        effective_user=SimpleNamespace(id=7),
    )

    asyncio.run(admin(update, context))

    assert bot.send_message.await_args.kwargs['chat_id'] == -100
    assert 'Core недоступен' in bot.send_message.await_args.kwargs['text']


def test_web_url_command_sets_chat_address(tmp_path):
    async def scenario():
        database, campaigns, sessions, access, bot = await setup(tmp_path)
        bot.get_chat_member = AsyncMock(return_value=SimpleNamespace(status='member'))
        data = {
            CAMPAIGN_SERVICE_KEY: campaigns,
            SESSION_SERVICE_KEY: sessions,
            ADMIN_ACCESS_KEY: access,
            WEB_BASE_URL_KEY: '',
        }
        context = SimpleNamespace(args=[], application=SimpleNamespace(bot_data=data), bot=bot)
        update = SimpleNamespace(
            effective_chat=SimpleNamespace(id=-100, type='group', title='Campaign'),
            effective_message=SimpleNamespace(id=10),
            effective_user=SimpleNamespace(id=7),
        )
        await web_url(update, context)
        missing = bot.send_message.await_args.kwargs['text']
        context.args = ['https://d20.example/']
        await web_url(update, context)
        denied = bot.send_message.await_args.kwargs['text']
        bot.get_chat_member.return_value.status = 'administrator'
        context.args = ['bad']
        await web_url(update, context)
        invalid = bot.send_message.await_args.kwargs['text']
        context.args = ['https://d20.example/']
        await web_url(update, context)
        saved = await sessions.get_web_base_url(-100)
        context.args = []
        await web_url(update, context)
        shown = bot.send_message.await_args.kwargs['text']
        await admin(update, context)
        link = bot.send_message.await_args.kwargs['text']
        await database.close()
        return missing, denied, invalid, saved, shown, link

    missing, denied, invalid, saved, shown, link = asyncio.run(scenario())
    assert 'не задан' in missing
    assert 'только администраторы' in denied
    assert 'Формат' in invalid
    assert saved == 'https://d20.example'
    assert 'https://d20.example' in shown
    assert 'https://d20.example/login?token=' in link


def test_web_login_dashboard_and_schedule(tmp_path, monkeypatch):
    monkeypatch.setenv('WEB_SECURE_COOKIE', 'auto')
    monkeypatch.setenv('GAME_TIMEZONE', 'UTC')

    async def scenario():
        database, campaigns, sessions, access, bot = await setup(tmp_path)
        server = AdminWebServer(access, campaigns, sessions, bot)
        await campaigns.register_player(-100, 8, '<Tilly>')
        identity = AdminIdentity(-100, 7, 'Campaign')
        token = access.create_login(identity)

        unauthorized = await server._route('GET', '/', {}, b'')
        login = await server._route('GET', f'/login?token={token}', {}, b'')
        secure_token = access.create_login(identity)
        secure_login = await server._route(
            'GET',
            f'/login?token={secure_token}',
            {'x-forwarded-proto': 'https'},
            b'',
        )
        repeated = await server._route('GET', f'/login?token={token}', {}, b'')
        cookie = login[1]['Set-Cookie'].split(';', 1)[0]
        headers = {'cookie': cookie}
        dashboard = await server._route('GET', '/', headers, b'')
        bad_date = await server._route(
            'POST', '/schedule', headers, b'scheduled_at=nope&foundry_url=https%3A%2F%2Fx.test'
        )
        bad_url = await server._route(
            'POST', '/schedule', headers, b'scheduled_at=2026-07-20T19%3A00&foundry_url=nope'
        )
        scheduled = await server._route(
            'POST',
            '/schedule',
            headers,
            b'scheduled_at=2026-07-20T19%3A00&foundry_url=https%3A%2F%2Ffoundry.test',
        )
        updated = await server._route('GET', '/', headers, b'')
        missing = await server._route('GET', '/missing', headers, b'')
        planned = await sessions.get_planned(-100)
        await database.close()
        return (
            unauthorized,
            login,
            secure_login,
            repeated,
            dashboard,
            bad_date,
            bad_url,
            scheduled,
            updated,
            missing,
            planned,
            bot,
        )

    results = asyncio.run(scenario())
    assert results[0][0] is HTTPStatus.UNAUTHORIZED
    assert results[1][0] is HTTPStatus.SEE_OTHER
    assert 'Secure' not in results[1][1]['Set-Cookie']
    assert 'Secure' in results[2][1]['Set-Cookie']
    assert results[3][0] is HTTPStatus.UNAUTHORIZED
    assert results[4][0] is HTTPStatus.OK
    assert b'&lt;Tilly&gt;' in results[4][2]
    assert results[5][0] is HTTPStatus.BAD_REQUEST
    assert results[6][0] is HTTPStatus.BAD_REQUEST
    assert results[7][0] is HTTPStatus.SEE_OTHER
    assert b'Foundry' in results[8][2]
    assert results[9][0] is HTTPStatus.NOT_FOUND
    assert results[10] is not None
    results[11].pin_chat_message.assert_awaited_once()


def test_internal_api_issues_admin_link_for_master(tmp_path):
    async def scenario():
        database, campaigns, sessions, access, bot = await setup(tmp_path)
        server = AdminWebServer(
            access,
            campaigns,
            sessions,
            bot,
            internal_token='core-secret',
            web_base_url='https://d20.example',
        )
        unauthorized = await server._route('POST', '/api/admin-link', {}, b'chat_id=-100&user_id=7')
        headers = {'authorization': 'Bearer core-secret'}
        invalid = await server._route('POST', '/api/admin-link', headers, b'chat_id=nope')
        forbidden = await server._route(
            'POST', '/api/admin-link', headers, b'chat_id=-100&user_id=8'
        )
        allowed = await server._route(
            'POST',
            '/api/admin-link',
            headers,
            'chat_id=-100&user_id=7&chat_title=Кампания'.encode(),
        )
        url = json.loads(allowed[2])['url']
        login = await server._route('GET', url.removeprefix('https://d20.example'), {}, b'')
        await database.close()
        return unauthorized, invalid, forbidden, allowed, login

    unauthorized, invalid, forbidden, allowed, login = asyncio.run(scenario())
    assert unauthorized[0] is HTTPStatus.UNAUTHORIZED
    assert invalid[0] is HTTPStatus.BAD_REQUEST
    assert forbidden[0] is HTTPStatus.FORBIDDEN
    assert allowed[0] is HTTPStatus.OK
    assert allowed[1]['Content-Type'].startswith('application/json')
    assert login[0] is HTTPStatus.SEE_OTHER


def test_web_server_start_read_request_and_close(tmp_path):
    async def scenario():
        database, campaigns, sessions, access, bot = await setup(tmp_path)
        server = AdminWebServer(access, campaigns, sessions, bot)
        reader = asyncio.StreamReader()
        reader.feed_data(b'POST /schedule HTTP/1.1\r\nContent-Length: 3\r\n\r\na=1')
        reader.feed_eof()
        request = await server._read_request(reader)
        await server.start('127.0.0.1', 0)
        assert server._server is not None
        await server.close()
        await server.close()
        await database.close()
        return request

    method, target, headers, body = asyncio.run(scenario())
    assert (method, target, headers['content-length'], body) == ('POST', '/schedule', '3', b'a=1')


def test_web_session_lifecycle(tmp_path):
    async def scenario():
        database, campaigns, sessions, access, bot = await setup(tmp_path)
        server = AdminWebServer(access, campaigns, sessions, bot)
        identity = AdminIdentity(-100, 7, 'Campaign')
        token = access.create_login(identity)
        login = await server._route('GET', f'/login?token={token}', {}, b'')
        headers = {'cookie': login[1]['Set-Cookie'].split(';', 1)[0]}

        too_long = await server._route(
            'POST', '/session/start', headers, f'title={"x" * 101}'.encode()
        )
        started = await server._route('POST', '/session/start', headers, 'title=Башня'.encode())
        active_page = await server._route('GET', '/', headers, b'')
        duplicate = await server._route('POST', '/session/start', headers, b'')
        stopped = await server._route('POST', '/session/stop', headers, b'')
        second_stop = await server._route('POST', '/session/stop', headers, b'')
        active = await sessions.get_active(-100)
        await campaigns.assign_master(-100, 8, 'Campaign')
        forbidden_start = await server._route('POST', '/session/start', headers, b'')
        forbidden_stop = await server._route('POST', '/session/stop', headers, b'')
        await database.close()
        return (
            too_long,
            started,
            active_page,
            duplicate,
            stopped,
            second_stop,
            forbidden_start,
            forbidden_stop,
            active,
            bot,
        )

    (
        too_long,
        started,
        active_page,
        duplicate,
        stopped,
        second_stop,
        forbidden_start,
        forbidden_stop,
        active,
        bot,
    ) = asyncio.run(scenario())
    assert too_long[0] is HTTPStatus.BAD_REQUEST
    assert started[0] is HTTPStatus.SEE_OTHER
    assert 'Активная сессия'.encode() in active_page[2]
    assert duplicate[0] is HTTPStatus.CONFLICT
    assert stopped[0] is HTTPStatus.SEE_OTHER
    assert second_stop[0] is HTTPStatus.CONFLICT
    assert forbidden_start[0] is HTTPStatus.FORBIDDEN
    assert forbidden_stop[0] is HTTPStatus.FORBIDDEN
    assert active is None
    assert any('началась' in call.kwargs['text'] for call in bot.send_message.await_args_list)
    assert any('завершена' in call.kwargs['text'] for call in bot.send_message.await_args_list)


def test_web_server_handles_http_response(tmp_path):
    class Writer:
        def __init__(self):
            self.data = b''
            self.closed = False

        def write(self, data):
            self.data += data

        async def drain(self):
            pass

        def close(self):
            self.closed = True

        async def wait_closed(self):
            pass

    async def scenario():
        database, campaigns, sessions, access, bot = await setup(tmp_path)
        server = AdminWebServer(access, campaigns, sessions, bot)
        reader = asyncio.StreamReader()
        reader.feed_data(b'GET / HTTP/1.1\r\nHost: localhost\r\n\r\n')
        reader.feed_eof()
        writer = Writer()
        await server._handle(reader, writer)
        await database.close()
        return writer

    writer = asyncio.run(scenario())
    assert writer.data.startswith(b'HTTP/1.1 401 Unauthorized')
    assert b'Content-Security-Policy' in writer.data
    assert writer.closed
