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
        publish=AsyncMock(),
        pending=AsyncMock(return_value=[]),
        acknowledge=AsyncMock(),
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


def test_admin_command_reports_connected_core_error(caplog):
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

    with caplog.at_level('WARNING'):
        asyncio.run(admin(update, context))

    assert bot.send_message.await_args.kwargs['chat_id'] == -100
    assert 'Core недоступен' in bot.send_message.await_args.kwargs['text']
    record = caplog.records[-1]
    assert record.core_path == '/api/admin-link'
    assert record.error_type == 'CoreClientError'
    assert record.error_message == 'unavailable'


def test_admin_command_explains_private_chat_usage():
    client = SimpleNamespace(create_admin_link=AsyncMock())
    bot = SimpleNamespace(send_message=AsyncMock())
    context = SimpleNamespace(
        application=SimpleNamespace(bot_data={CORE_CLIENT_KEY: client}), bot=bot
    )
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=7, title=None, type='private'),
        effective_message=SimpleNamespace(id=10),
        effective_user=SimpleNamespace(id=7),
    )

    asyncio.run(admin(update, context))

    client.create_admin_link.assert_not_awaited()
    assert 'в группе кампании' in bot.send_message.await_args.kwargs['text']


def test_web_url_command_uses_connected_core():
    async def scenario():
        core = SimpleNamespace(
            get_web_url=AsyncMock(return_value='https://d20.example'),
            set_web_url=AsyncMock(),
        )
        bot = SimpleNamespace(
            send_message=AsyncMock(),
            get_chat_member=AsyncMock(return_value=SimpleNamespace(status='administrator')),
        )
        context = SimpleNamespace(
            args=[], bot=bot, application=SimpleNamespace(bot_data={CORE_CLIENT_KEY: core})
        )
        update = SimpleNamespace(
            effective_chat=SimpleNamespace(id=-100, type='group'),
            effective_message=SimpleNamespace(id=10),
            effective_user=SimpleNamespace(id=7),
        )
        await web_url(update, context)
        context.args = ['https://new.example/']
        await web_url(update, context)
        return core, bot

    core, bot = asyncio.run(scenario())
    core.get_web_url.assert_awaited_once_with(-100)
    core.set_web_url.assert_awaited_once_with(-100, 'https://new.example')
    assert 'сохранён' in bot.send_message.await_args.kwargs['text']


def test_web_url_command_reports_connected_core_error():
    async def scenario():
        core = SimpleNamespace(
            get_web_url=AsyncMock(side_effect=CoreClientError('offline')),
            set_web_url=AsyncMock(side_effect=CoreClientError('offline')),
        )
        bot = SimpleNamespace(send_message=AsyncMock())
        context = SimpleNamespace(
            args=[], bot=bot, application=SimpleNamespace(bot_data={CORE_CLIENT_KEY: core})
        )
        update = SimpleNamespace(
            effective_chat=SimpleNamespace(id=1, type='private'),
            effective_message=SimpleNamespace(id=10),
            effective_user=SimpleNamespace(id=7),
        )
        await web_url(update, context)
        missing = bot.send_message.await_args.kwargs['text']
        context.args = ['https://new.example']
        await web_url(update, context)
        failed = bot.send_message.await_args.kwargs['text']
        return missing, failed

    missing, failed = asyncio.run(scenario())
    assert 'не задан' in missing
    assert 'Core недоступен' in failed


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
    monkeypatch.setenv('D20_BOT_WEB_SECURE_COOKIE', 'auto')
    monkeypatch.setenv('D20_BOT_GAME_TIMEZONE', 'UTC')

    async def scenario():
        database, campaigns, sessions, access, bot = await setup(tmp_path)
        server = AdminWebServer(access, campaigns, sessions, bot)
        await campaigns.register_player(-100, 8, '<Tilly>')
        identity = AdminIdentity(-100, 7, 'Campaign')
        token = access.create_login(identity)

        health = await server._route('GET', '/health', {}, b'')
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
            health,
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
    assert results[0] == (
        HTTPStatus.OK,
        {'Content-Type': 'application/json; charset=utf-8'},
        b'{"status": "ok"}',
    )
    assert results[1][0] is HTTPStatus.UNAUTHORIZED
    assert results[2][0] is HTTPStatus.SEE_OTHER
    assert 'Secure' not in results[2][1]['Set-Cookie']
    assert 'Secure' in results[3][1]['Set-Cookie']
    assert results[4][0] is HTTPStatus.UNAUTHORIZED
    assert results[5][0] is HTTPStatus.OK
    assert b'&lt;Tilly&gt;' in results[5][2]
    assert results[6][0] is HTTPStatus.BAD_REQUEST
    assert results[7][0] is HTTPStatus.BAD_REQUEST
    assert results[8][0] is HTTPStatus.SEE_OTHER
    assert b'Foundry' in results[9][2]
    assert results[10][0] is HTTPStatus.NOT_FOUND
    assert results[11] is not None
    results[12].publish.assert_awaited_once()


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


def test_internal_game_api(tmp_path, monkeypatch):
    monkeypatch.setenv('D20_BOT_GAME_TIMEZONE', 'UTC')
    monkeypatch.setenv('D20_BOT_FOUNDRY_URL', 'https://foundry.example/default')

    async def scenario():
        database, campaigns, sessions, access, bot = await setup(tmp_path)
        server = AdminWebServer(access, campaigns, sessions, bot, internal_token='secret')
        headers = {'authorization': 'Bearer secret'}
        unauthorized = await server._route('POST', '/api/game', {}, b'action=get&chat_id=-100')
        empty = await server._route('POST', '/api/game', headers, b'action=get&chat_id=-100')
        invalid = await server._route('POST', '/api/game', headers, b'action=schedule&chat_id=x')
        scheduled = await server._route(
            'POST',
            '/api/game',
            headers,
            b'action=schedule&chat_id=-100&scheduled_at=2026-07-20T19%3A00%3A00%2B00%3A00',
        )
        payload = json.loads(scheduled[2])
        saved = await server._route(
            'POST',
            '/api/game',
            headers,
            f'action=set_announcement&session_id={payload["session_id"]}&message_id=99'.encode(),
        )
        shown = await server._route('POST', '/api/game', headers, b'action=get&chat_id=-100')
        no_url = await server._route('POST', '/api/game-url', headers, b'action=get&chat_id=-1')
        unauthorized_url = await server._route(
            'POST', '/api/game-url', {}, b'action=get&chat_id=-1'
        )
        invalid_url = await server._route(
            'POST', '/api/game-url', headers, b'action=set&chat_id=-100&foundry_url=bad'
        )
        invalid_game_action = await server._route('POST', '/api/game', headers, b'action=nope')
        set_url = await server._route(
            'POST',
            '/api/game-url',
            headers,
            b'action=set&chat_id=-100&foundry_url=https%3A%2F%2Fchat.example',
        )
        got_url = await server._route('POST', '/api/game-url', headers, b'action=get&chat_id=-100')
        bad_action = await server._route(
            'POST', '/api/game-url', headers, b'action=nope&chat_id=-100'
        )
        planned = await sessions.get_planned(-100)
        await database.close()
        return (
            unauthorized,
            empty,
            invalid,
            scheduled,
            saved,
            shown,
            no_url,
            unauthorized_url,
            invalid_url,
            invalid_game_action,
            set_url,
            got_url,
            bad_action,
            planned,
        )

    results = asyncio.run(scenario())
    assert results[0][0] is HTTPStatus.UNAUTHORIZED
    assert results[1][0] is HTTPStatus.OK
    assert results[2][0] is HTTPStatus.BAD_REQUEST
    assert results[3][0] is HTTPStatus.OK
    assert results[4][0] is HTTPStatus.OK
    assert b'Foundry' in results[5][2]
    assert json.loads(results[6][2])['url'] == 'https://foundry.example/default'
    assert results[7][0] is HTTPStatus.UNAUTHORIZED
    assert results[8][0] is HTTPStatus.BAD_REQUEST
    assert results[9][0] is HTTPStatus.BAD_REQUEST
    assert results[10][0] is HTTPStatus.OK
    assert json.loads(results[11][2])['url'] == 'https://chat.example'
    assert results[12][0] is HTTPStatus.BAD_REQUEST
    assert results[13].message_id == 99


def test_internal_session_api(tmp_path):
    async def scenario():
        database, campaigns, sessions, access, bot = await setup(tmp_path)
        server = AdminWebServer(access, campaigns, sessions, bot, internal_token='secret')
        headers = {'authorization': 'Bearer secret'}

        async def call(body: bytes, authorized: bool = True):
            return await server._route('POST', '/api/session', headers if authorized else {}, body)

        results = [
            await call(b'action=start&chat_id=-100&user_id=7', False),
            await call(b'action=start&chat_id=x'),
            await call(f'action=start&chat_id=-100&user_id=7&title={"x" * 101}'.encode()),
            await call(b'action=start&chat_id=-100&user_id=8'),
            await call(b'action=start&chat_id=-100&user_id=7&title=Tower'),
            await call(b'action=start&chat_id=-100&user_id=7'),
            await call(b'action=stop&chat_id=-100&user_id=8'),
            await call(b'action=stop&chat_id=-100&user_id=7'),
            await call(b'action=stop&chat_id=-100&user_id=7'),
            await call(b'action=nope&chat_id=-100&user_id=7'),
        ]
        await database.close()
        return results

    results = asyncio.run(scenario())
    assert [result[0] for result in results] == [
        HTTPStatus.UNAUTHORIZED,
        HTTPStatus.BAD_REQUEST,
        HTTPStatus.BAD_REQUEST,
        HTTPStatus.OK,
        HTTPStatus.OK,
        HTTPStatus.OK,
        HTTPStatus.OK,
        HTTPStatus.OK,
        HTTPStatus.OK,
        HTTPStatus.BAD_REQUEST,
    ]
    assert [json.loads(result[2]).get('status') for result in results[3:9]] == [
        'forbidden',
        'started',
        'already_active',
        'forbidden',
        'stopped',
        'no_active_session',
    ]


def test_internal_role_api(tmp_path):
    async def scenario():
        database, campaigns, sessions, access, bot = await setup(tmp_path)
        server = AdminWebServer(access, campaigns, sessions, bot, internal_token='secret')
        headers = {'authorization': 'Bearer secret'}

        async def call(body: bytes, authorized: bool = True):
            return await server._route('POST', '/api/role', headers if authorized else {}, body)

        results = [
            await call(b'action=assign_master&chat_id=-200&user_id=20', False),
            await call(b'action=assign_master&chat_id=x'),
            await call(b'action=assign_master&chat_id=-200&user_id=20&chat_title=New'),
            await call(b'action=register_player&chat_id=-200&user_id=20&name=Hero'),
            await call(b'action=register_player&chat_id=-200&user_id=21&name='),
            await call(b'action=register_player&chat_id=-200&user_id=21&name=Hero'),
            await call(b'action=nope&chat_id=-200&user_id=21'),
        ]
        roster = await campaigns.get_roster(-200)
        await database.close()
        return results, roster

    results, roster = asyncio.run(scenario())
    assert [result[0] for result in results] == [
        HTTPStatus.UNAUTHORIZED,
        HTTPStatus.BAD_REQUEST,
        HTTPStatus.OK,
        HTTPStatus.OK,
        HTTPStatus.BAD_REQUEST,
        HTTPStatus.OK,
        HTTPStatus.BAD_REQUEST,
    ]
    assert json.loads(results[3][2])['status'] == 'master_conflict'
    assert json.loads(results[5][2]) == {'status': 'registered', 'name': 'Hero'}
    assert roster is not None and roster.campaign.master_user_id == 20


def test_internal_web_url_api(tmp_path):
    async def scenario():
        database, campaigns, sessions, access, bot = await setup(tmp_path)
        server = AdminWebServer(
            access,
            campaigns,
            sessions,
            bot,
            internal_token='secret',
            web_base_url='https://default',
        )
        headers = {'authorization': 'Bearer secret'}
        results = [
            await server._route('POST', '/api/web-url', {}, b'action=get&chat_id=-100'),
            await server._route('POST', '/api/web-url', headers, b'action=get&chat_id=x'),
            await server._route('POST', '/api/web-url', headers, b'action=get&chat_id=-100'),
            await server._route(
                'POST', '/api/web-url', headers, b'action=set&chat_id=-100&web_url=bad'
            ),
            await server._route(
                'POST',
                '/api/web-url',
                headers,
                b'action=set&chat_id=-100&web_url=https%3A%2F%2Fd20.example%2F',
            ),
            await server._route('POST', '/api/web-url', headers, b'action=get&chat_id=-100'),
            await server._route('POST', '/api/web-url', headers, b'action=nope&chat_id=-100'),
        ]
        await database.close()
        return results

    results = asyncio.run(scenario())
    assert results[0][0] is HTTPStatus.UNAUTHORIZED
    assert results[1][0] is HTTPStatus.BAD_REQUEST
    assert json.loads(results[2][2])['url'] == 'https://default'
    assert results[3][0] is HTTPStatus.BAD_REQUEST
    assert results[4][0] is HTTPStatus.OK
    assert json.loads(results[5][2])['url'] == 'https://d20.example'
    assert results[6][0] is HTTPStatus.BAD_REQUEST


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
    assert [call.args[0] for call in bot.publish.await_args_list] == [
        'session_started',
        'session_stopped',
    ]


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
