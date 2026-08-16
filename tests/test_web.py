import asyncio
import json
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram.error import BadRequest

from auth import RateLimitResult, SQLiteLocalIdentityProvider
from commands.admin_commands import CORE_CLIENT_KEY, admin, web_register, web_url
from core import CoreClientError
from database import SQLiteDatabase, apply_migrations
from database.repositories import (
    CampaignRepository,
    CharacterRepository,
    GameConfigRepository,
    MembershipRepository,
    SessionRepository,
)
from services import CampaignService, GameWorkflowService, SessionService
from web import AdminAccessService
from web import AdminWebServer as _AdminWebServer
from web.access import AdminIdentity
from web.session_store import SQLiteWebSessionStore

MIGRATIONS = Path(__file__).resolve().parent.parent / 'migrations'


def campaign_service(database):
    return CampaignService(
        database,
        CampaignRepository(database),
        CharacterRepository(database),
        MembershipRepository(database),
    )


def session_service(database):
    return SessionService(
        CampaignRepository(database),
        SessionRepository(database),
        GameConfigRepository(database),
        MembershipRepository(database),
    )


class AdminWebServer(_AdminWebServer):
    def __init__(self, database, access, campaigns, sessions, outbox, *args, **kwargs):
        workflows = GameWorkflowService(database, sessions, outbox)
        super().__init__(workflows, access, campaigns, sessions, outbox, *args, **kwargs)


async def setup(tmp_path):
    database = await SQLiteDatabase.connect(str(tmp_path / 'web.sqlite3'))
    await apply_migrations(database, MIGRATIONS)
    campaigns = campaign_service(database)
    sessions = session_service(database)
    await campaigns.assign_master(-100, 7, 'Campaign')
    access = AdminAccessService(SQLiteWebSessionStore(database))
    bot = SimpleNamespace(
        send_message=AsyncMock(return_value=SimpleNamespace(id=55)),
        pin_chat_message=AsyncMock(),
        unpin_chat_message=AsyncMock(),
        publish=AsyncMock(),
        pending=AsyncMock(return_value=[]),
        acknowledge=AsyncMock(),
    )
    return database, campaigns, sessions, access, bot


async def csrf_body(access, headers, body=b''):
    session_id = headers['cookie'].split('=', 1)[1]
    token = await access.csrf_token(session_id)
    assert token is not None
    return body + (b'&' if body else b'') + f'csrf_token={token}'.encode()


def test_admin_access_uses_one_time_logins_and_expiring_sessions(tmp_path):
    async def scenario():
        database = await SQLiteDatabase.connect(str(tmp_path / 'access.sqlite3'))
        await apply_migrations(database, MIGRATIONS)
        access = AdminAccessService(SQLiteWebSessionStore(database))
        identity = AdminIdentity(-100, 7, 'Campaign')
        token = await access.create_login(identity)
        issued_login_rows = await database.fetch_all('SELECT token_hash FROM web_login_tokens')
        session_id = await access.consume_login(token)
        assert session_id is not None
        repeated = await access.consume_login(token)
        authenticated = await access.authenticate(session_id)
        restored = await AdminAccessService(SQLiteWebSessionStore(database)).authenticate(
            session_id
        )
        empty = await access.authenticate(None)
        login_rows = await database.fetch_all('SELECT token_hash FROM web_login_tokens')
        session_rows = await database.fetch_all('SELECT session_hash FROM web_sessions')
        await database.execute(
            'UPDATE web_sessions SET expires_at = ?',
            ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(),),
        )
        expired = await access.authenticate(session_id)
        await database.close()
        return (
            repeated,
            authenticated,
            restored,
            empty,
            expired,
            identity,
            token,
            session_id,
            login_rows,
            issued_login_rows,
            session_rows,
        )

    (
        repeated,
        authenticated,
        restored,
        empty,
        expired,
        identity,
        token,
        session_id,
        login_rows,
        issued_login_rows,
        session_rows,
    ) = asyncio.run(scenario())
    assert repeated is None
    assert authenticated == identity
    assert restored == identity
    assert empty is None
    assert expired is None
    assert login_rows == []
    assert issued_login_rows[0]['token_hash'] != token
    assert session_rows[0]['session_hash'] not in {token, session_id}


def test_admin_commands_ignore_updates_without_chat():
    async def scenario():
        update = SimpleNamespace(effective_chat=None, effective_message=None, effective_user=None)
        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()))
        await admin(update, context)
        await web_url(update, context)
        return context.bot

    bot = asyncio.run(scenario())
    bot.send_message.assert_not_awaited()


def test_web_register_command_uses_core():
    async def scenario():
        bot = SimpleNamespace(send_message=AsyncMock())
        client = SimpleNamespace(create_registration_code=AsyncMock(return_value='ABCD-EFGH-JKLM'))
        update = SimpleNamespace(
            effective_message=SimpleNamespace(id=1, chat_id=-100),
            effective_user=SimpleNamespace(id=7),
        )
        context = SimpleNamespace(
            bot=bot, application=SimpleNamespace(bot_data={CORE_CLIENT_KEY: client})
        )
        await web_register(update, context)
        return bot, client

    bot, client = asyncio.run(scenario())
    client.create_registration_code.assert_awaited_once_with(7)
    assert bot.send_message.await_count == 2
    assert 'ABCD-EFGH-JKLM' in bot.send_message.await_args_list[0].kwargs['text']


def test_local_web_registration_and_login(tmp_path):
    async def scenario():
        database, campaigns, sessions, access, bot = await setup(tmp_path)
        identities = SQLiteLocalIdentityProvider(database)
        server = AdminWebServer(database, access, campaigns, sessions, bot, identities)
        code = await identities.issue_registration_code(7)
        registration = await server._route(
            'POST',
            '/register',
            {},
            f'code={code}&login=master&password=long-enough-password'.encode(),
        )
        cookie = registration[1]['Set-Cookie'].split(';', 1)[0]
        campaigns_page = await server._route('GET', '/campaigns', {'cookie': cookie}, b'')
        bad_login = await server._route(
            'POST', '/login', {}, b'login=master&password=wrong-password'
        )
        login = await server._route(
            'POST', '/login', {}, b'login=MASTER&password=long-enough-password'
        )
        await database.close()
        return registration, campaigns_page, bad_login, login

    registration, campaigns_page, bad_login, login = asyncio.run(scenario())
    assert registration[0] == HTTPStatus.SEE_OTHER
    assert campaigns_page[0] == HTTPStatus.OK
    assert b'Campaign' in campaigns_page[2]
    assert bad_login[0] == HTTPStatus.BAD_REQUEST
    assert login[0] == HTTPStatus.SEE_OTHER


def test_local_web_auth_errors_and_registration_api(tmp_path):
    async def scenario():
        database, campaigns, sessions, access, bot = await setup(tmp_path)
        identities = SQLiteLocalIdentityProvider(database)
        server = AdminWebServer(
            database, access, campaigns, sessions, bot, identities, internal_token='secret'
        )
        headers = {'authorization': 'Bearer secret'}
        pages = [
            await server._route('GET', '/login', {}, b''),
            await server._route('GET', '/register?code=TEST', {}, b''),
            await server._route(
                'POST', '/register', {}, b'code=bad&login=user&password=long-password'
            ),
            await server._route(
                'POST', '/register', {}, b'code=bad&login=not+valid&password=long-password'
            ),
            await server._route('POST', '/api/auth/registration', {}, b'user_id=7'),
            await server._route('POST', '/api/auth/registration', headers, b'user_id=bad'),
            await server._route('POST', '/api/auth/registration', headers, b'user_id=404'),
            await server._route('POST', '/api/auth/registration', headers, b'user_id=7'),
        ]
        disabled = AdminWebServer(
            database, access, campaigns, sessions, bot, internal_token='secret'
        )
        pages.extend(
            [
                await disabled._route('POST', '/login', {}, b'login=x&password=y'),
                await disabled._route('POST', '/register', {}, b'code=x'),
                await disabled._route('POST', '/api/auth/registration', headers, b'user_id=7'),
                await disabled._route(
                    'POST', '/internal/auth/registration-codes', headers, b'user_id=7'
                ),
            ]
        )
        await database.close()
        return pages

    pages = asyncio.run(scenario())
    assert [page[0] for page in pages] == [
        HTTPStatus.OK,
        HTTPStatus.OK,
        HTTPStatus.BAD_REQUEST,
        HTTPStatus.BAD_REQUEST,
        HTTPStatus.UNAUTHORIZED,
        HTTPStatus.BAD_REQUEST,
        HTTPStatus.NOT_FOUND,
        HTTPStatus.OK,
        HTTPStatus.SERVICE_UNAVAILABLE,
        HTTPStatus.SERVICE_UNAVAILABLE,
        HTTPStatus.SERVICE_UNAVAILABLE,
        HTTPStatus.SERVICE_UNAVAILABLE,
    ]


def test_auth_endpoints_return_rate_limit_response(tmp_path):
    async def scenario():
        database, campaigns, sessions, access, bot = await setup(tmp_path)
        identities = SQLiteLocalIdentityProvider(database)
        limiter = SimpleNamespace(hit=AsyncMock(return_value=RateLimitResult(False, 42)))
        server = AdminWebServer(
            database,
            access,
            campaigns,
            sessions,
            bot,
            identities,
            limiter,
            internal_token='secret',
            web_base_url='https://d20.example',
        )
        headers = {'authorization': 'Bearer secret'}
        responses = [
            await server._route(
                'POST', '/login', {}, b'login=user&password=long-password', '192.0.2.1'
            ),
            await server._route(
                'POST',
                '/register',
                {},
                b'code=ABCD&login=user&password=long-password',
                '192.0.2.1',
            ),
            await server._route('POST', '/api/auth/registration', headers, b'user_id=7'),
            await server._route('POST', '/api/admin-link', headers, b'chat_id=-100&user_id=7'),
            await server._route('POST', '/internal/auth/registration-codes', headers, b'user_id=7'),
            await server._route(
                'POST', '/internal/campaigns/-100/admin-links', headers, b'user_id=7'
            ),
        ]
        await database.close()
        return responses, limiter

    responses, limiter = asyncio.run(scenario())
    assert all(response[0] is HTTPStatus.TOO_MANY_REQUESTS for response in responses)
    assert all(response[1]['Retry-After'] == '42' for response in responses)
    assert b'rate_limited' in responses[2][2] and b'rate_limited' in responses[3][2]
    assert json.loads(responses[4][2])['error']['code'] == 'rate_limited'
    assert json.loads(responses[5][2])['error']['code'] == 'rate_limited'
    assert limiter.hit.await_count == 6


def test_rate_limit_only_trusts_forwarded_ip_from_configured_proxy(tmp_path, monkeypatch):
    async def scenario():
        database, campaigns, sessions, access, bot = await setup(tmp_path)
        identities = SQLiteLocalIdentityProvider(database)
        limiter = SimpleNamespace(hit=AsyncMock(return_value=RateLimitResult(False, 1)))
        server = AdminWebServer(database, access, campaigns, sessions, bot, identities, limiter)
        headers = {'x-forwarded-for': '198.51.100.10, 127.0.0.1'}
        await server._route('POST', '/login', headers, b'login=x&password=y', '127.0.0.1')
        trusted_key = limiter.hit.await_args.kwargs if limiter.hit.await_args.kwargs else None
        trusted_call = limiter.hit.await_args.args[0]
        limiter.hit.reset_mock()
        await server._route('POST', '/login', headers, b'login=x&password=y', '203.0.113.5')
        untrusted_call = limiter.hit.await_args.args[0]
        await database.close()
        return trusted_call, trusted_key, untrusted_call

    monkeypatch.setenv('D20_BOT_WEB_TRUSTED_PROXIES', '127.0.0.0/8')
    trusted, kwargs, untrusted = asyncio.run(scenario())
    assert trusted == 'login:198.51.100.10'
    assert kwargs == {'limit': 10, 'window': timedelta(minutes=10)}
    assert untrusted == 'login:203.0.113.5'


def test_web_register_command_handles_missing_context_and_core_error():
    async def scenario():
        bot = SimpleNamespace(send_message=AsyncMock())
        empty = SimpleNamespace(effective_message=None, effective_user=None)
        context = SimpleNamespace(bot=bot, application=SimpleNamespace(bot_data={}))
        await web_register(empty, context)
        update = SimpleNamespace(
            effective_message=SimpleNamespace(id=1, chat_id=7),
            effective_user=SimpleNamespace(id=7),
        )
        context.application.bot_data[CORE_CLIENT_KEY] = SimpleNamespace(
            create_registration_code=AsyncMock(side_effect=CoreClientError('offline'))
        )
        await web_register(update, context)
        return bot

    bot = asyncio.run(scenario())
    bot.send_message.assert_awaited_once()


def test_admin_command_reports_private_message_failure():
    async def scenario():
        core = SimpleNamespace(
            create_admin_link=AsyncMock(return_value='https://d20.example/login')
        )
        bot = SimpleNamespace(send_message=AsyncMock())
        bot.send_message.side_effect = [BadRequest('blocked'), SimpleNamespace(id=1)]
        context = SimpleNamespace(
            application=SimpleNamespace(bot_data={CORE_CLIENT_KEY: core}),
            bot=bot,
        )
        update = SimpleNamespace(
            effective_chat=SimpleNamespace(id=-100, title='Campaign'),
            effective_message=SimpleNamespace(id=10),
            effective_user=SimpleNamespace(id=7),
        )
        await admin(update, context)
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


def test_web_url_command_validates_admin_and_url():
    async def scenario():
        core = SimpleNamespace(set_web_url=AsyncMock())
        bot = SimpleNamespace(
            send_message=AsyncMock(),
            get_chat_member=AsyncMock(return_value=SimpleNamespace(status='member')),
        )
        context = SimpleNamespace(
            args=['https://new.example'],
            bot=bot,
            application=SimpleNamespace(bot_data={CORE_CLIENT_KEY: core}),
        )
        update = SimpleNamespace(
            effective_chat=SimpleNamespace(id=-100, type='group'),
            effective_message=SimpleNamespace(id=10),
            effective_user=SimpleNamespace(id=7),
        )
        await web_url(update, context)
        denied = bot.send_message.await_args.kwargs['text']
        bot.get_chat_member.return_value.status = 'administrator'
        context.args = ['not-a-url']
        await web_url(update, context)
        return core, denied, bot.send_message.await_args.kwargs['text']

    core, denied, invalid = asyncio.run(scenario())
    assert denied != invalid
    assert '/web_url' in invalid
    core.set_web_url.assert_not_awaited()


def test_web_login_dashboard_and_schedule(tmp_path, monkeypatch):
    monkeypatch.setenv('D20_BOT_WEB_SECURE_COOKIE', 'auto')
    monkeypatch.setenv('D20_BOT_WEB_TRUSTED_PROXIES', '127.0.0.0/8')
    monkeypatch.setenv('D20_BOT_GAME_TIMEZONE', 'UTC')

    async def scenario():
        database, campaigns, sessions, access, bot = await setup(tmp_path)
        server = AdminWebServer(database, access, campaigns, sessions, bot)
        await campaigns.register_player(-100, 8, '<Tilly>')
        identity = AdminIdentity(-100, 7, 'Campaign')
        token = await access.create_login(identity)

        health = await server._route('GET', '/health', {}, b'')
        javascript = await server._route('GET', '/static/app.js', {}, b'')
        landing = await server._route('GET', '/', {}, b'')
        login = await server._route('GET', f'/login?token={token}', {}, b'')
        secure_token = await access.create_login(identity)
        secure_login = await server._route(
            'GET',
            f'/login?token={secure_token}',
            {'x-forwarded-proto': 'https'},
            b'',
            '127.0.0.1',
        )
        repeated = await server._route('GET', f'/login?token={token}', {}, b'')
        cookie = login[1]['Set-Cookie'].split(';', 1)[0]
        headers = {'cookie': cookie}
        dashboard = await server._route('GET', '/', headers, b'')
        bad_date = await server._route(
            'POST',
            '/schedule',
            headers,
            await csrf_body(access, headers, b'scheduled_at=nope&foundry_url=https%3A%2F%2Fx.test'),
        )
        bad_url = await server._route(
            'POST',
            '/schedule',
            headers,
            await csrf_body(
                access,
                headers,
                b'scheduled_at=2026-07-20T19%3A00%2B00%3A00&foundry_url=nope',
            ),
        )
        scheduled = await server._route(
            'POST',
            '/schedule',
            headers,
            await csrf_body(
                access,
                headers,
                b'scheduled_at=2026-07-20T19%3A00%2B00%3A00&foundry_url=https%3A%2F%2Ffoundry.test',
            ),
        )
        updated = await server._route('GET', '/', headers, b'')
        missing = await server._route('GET', '/missing', headers, b'')
        planned = await sessions.get_planned(-100)
        await database.close()
        return (
            health,
            javascript,
            landing,
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
    assert results[1][0] is HTTPStatus.OK
    assert results[1][1]['Content-Type'] == 'text/javascript; charset=utf-8'
    assert b'applyTheme' in results[1][2]
    assert results[2][0] is HTTPStatus.OK
    assert b'/login' in results[2][2] and b'/register' in results[2][2]
    assert results[3][0] is HTTPStatus.SEE_OTHER
    assert 'Secure' not in results[3][1]['Set-Cookie']
    assert 'Secure' in results[4][1]['Set-Cookie']
    assert results[5][0] is HTTPStatus.UNAUTHORIZED
    assert results[6][0] is HTTPStatus.OK
    assert b'&lt;Tilly&gt;' in results[6][2]
    assert results[7][0] is HTTPStatus.BAD_REQUEST
    assert results[8][0] is HTTPStatus.BAD_REQUEST
    assert results[9][0] is HTTPStatus.SEE_OTHER
    assert b'Foundry' in results[10][2]
    assert results[11][0] is HTTPStatus.NOT_FOUND
    assert results[12] is not None
    results[13].publish.assert_awaited_once()


def test_web_known_route_rejects_unsupported_method(tmp_path):
    async def scenario():
        database, campaigns, sessions, access, bot = await setup(tmp_path)
        server = AdminWebServer(database, access, campaigns, sessions, bot)
        response = await server._route('DELETE', '/health', {}, b'')
        await database.close()
        return response

    response = asyncio.run(scenario())
    assert response[0] is HTTPStatus.METHOD_NOT_ALLOWED


def test_web_campaign_settings(tmp_path):
    async def scenario():
        database, campaigns, sessions, access, bot = await setup(tmp_path)
        server = AdminWebServer(database, access, campaigns, sessions, bot)
        token = await access.create_login(AdminIdentity(-100, 7, 'Campaign'))
        login = await server._route('GET', f'/login?token={token}', {}, b'')
        headers = {'cookie': login[1]['Set-Cookie'].split(';', 1)[0]}

        shown = await server._route('GET', '/settings', headers, b'')
        invalid = await server._route(
            'POST',
            '/settings',
            headers,
            await csrf_body(
                access,
                headers,
                b'title=New&foundry_url=nope&announcement_timezone=Moon%2FBase',
            ),
        )
        saved = await server._route(
            'POST',
            '/settings',
            headers,
            await csrf_body(
                access,
                headers,
                b'title=New+Campaign&foundry_url=https%3A%2F%2Fvtt.example&announcement_timezone=Asia%2FYerevan',
            ),
        )
        dashboard = await server._route('GET', '/', headers, b'')
        roster = await campaigns.get_roster(-100)
        config = (
            await sessions.get_default_url(-100),
            await sessions.get_announcement_timezone(-100),
        )
        await database.close()
        return shown, invalid, saved, dashboard, roster, config

    shown, invalid, saved, dashboard, roster, config = asyncio.run(scenario())
    assert shown[0] is HTTPStatus.OK
    assert b'Europe/Moscow' in shown[2]
    assert invalid[0] is HTTPStatus.BAD_REQUEST
    assert saved == (HTTPStatus.SEE_OTHER, {'Location': '/settings?campaign=-100'}, b'')
    assert roster is not None and roster.campaign.title == 'New Campaign'
    assert config == ('https://vtt.example', 'Asia/Yerevan')
    assert b'New Campaign' in dashboard[2]


def test_web_rejects_invalid_csrf_and_logs_out(tmp_path):
    async def scenario():
        database, campaigns, sessions, access, bot = await setup(tmp_path)
        server = AdminWebServer(database, access, campaigns, sessions, bot)
        token = await access.create_login(AdminIdentity(-100, 7, 'Campaign'))
        login = await server._route('GET', f'/login?token={token}', {}, b'')
        headers = {'cookie': login[1]['Set-Cookie'].split(';', 1)[0]}

        rejected = await server._route('POST', '/session/start', headers, b'csrf_token=forged')
        logout = await server._route('POST', '/logout', headers, await csrf_body(access, headers))
        after = await server._route('GET', '/campaigns', headers, b'')
        await database.close()
        return rejected, logout, after

    rejected, logout, after = asyncio.run(scenario())
    assert rejected[0] is HTTPStatus.FORBIDDEN
    assert logout[0] is HTTPStatus.SEE_OTHER
    assert 'Max-Age=0' in logout[1]['Set-Cookie']
    assert after[0] is HTTPStatus.UNAUTHORIZED


def test_web_lists_and_revokes_active_sessions(tmp_path):
    async def scenario():
        database, campaigns, sessions, access, bot = await setup(tmp_path)
        server = AdminWebServer(database, access, campaigns, sessions, bot)
        identity = AdminIdentity(-100, 7, 'Campaign')

        first_token = await access.create_login(identity)
        first_login = await server._route('GET', f'/login?token={first_token}', {}, b'')
        first_headers = {'cookie': first_login[1]['Set-Cookie'].split(';', 1)[0]}
        second_token = await access.create_login(identity)
        await server._route('GET', f'/login?token={second_token}', {}, b'')

        listed = await access.list_sessions(identity, first_headers['cookie'].split('=', 1)[1])
        other = next(session for session in listed if not session.current)
        page = await server._route('GET', '/sessions', first_headers, b'')
        revoked = await server._route(
            'POST',
            '/sessions/revoke',
            first_headers,
            await csrf_body(access, first_headers, f'revocation_id={other.revocation_id}'.encode()),
        )
        remaining = await access.list_sessions(identity, first_headers['cookie'].split('=', 1)[1])
        foreign = await access.revoke_by_id(
            AdminIdentity(-200, 7, None), remaining[0].revocation_id
        )
        await database.close()
        return listed, page, revoked, remaining, foreign

    listed, page, revoked, remaining, foreign = asyncio.run(scenario())
    assert len(listed) == 2
    assert page[0] is HTTPStatus.OK
    assert 'Активные сессии'.encode() in page[2]
    assert 'Текущая'.encode() in page[2]
    assert revoked == (HTTPStatus.SEE_OTHER, {'Location': '/sessions'}, b'')
    assert len(remaining) == 1 and remaining[0].current
    assert foreign


def test_expired_login_and_revoked_session_cannot_be_used(tmp_path):
    async def scenario():
        database, campaigns, sessions, access, bot = await setup(tmp_path)
        server = AdminWebServer(database, access, campaigns, sessions, bot)
        identity = AdminIdentity(-100, 7, 'Campaign')

        expired_token = await access.create_login(identity)
        await database.execute(
            'UPDATE web_login_tokens SET expires_at = ?',
            ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(),),
        )
        expired_login = await server._route('GET', f'/login?token={expired_token}', {}, b'')

        token = await access.create_login(identity)
        login = await server._route('GET', f'/login?token={token}', {}, b'')
        cookie = login[1]['Set-Cookie'].split(';', 1)[0]
        session_id = cookie.split('=', 1)[1]
        await access.revoke(session_id)
        after_revoke = await server._route('GET', '/campaigns', {'cookie': cookie}, b'')
        await database.close()
        return expired_login, after_revoke

    expired_login, after_revoke = asyncio.run(scenario())
    assert expired_login[0] is HTTPStatus.UNAUTHORIZED
    assert after_revoke[0] is HTTPStatus.UNAUTHORIZED


def test_web_user_can_switch_between_campaign_roles(tmp_path):
    async def scenario():
        database, campaigns, sessions, access, bot = await setup(tmp_path)
        await campaigns.assign_master(-200, 8, 'Second')
        await campaigns.register_player(-200, 7, 'Alice')
        server = AdminWebServer(database, access, campaigns, sessions, bot)
        token = await access.create_login(AdminIdentity(-100, 7, 'First'))
        login = await server._route('GET', f'/login?token={token}', {}, b'')
        headers = {'cookie': login[1]['Set-Cookie'].split(';', 1)[0]}

        selector = await server._route('GET', '/campaigns', headers, b'')
        player_page = await server._route('GET', '/?campaign=-200', headers, b'')
        player_settings = await server._route('GET', '/settings?campaign=-200', headers, b'')
        player_action = await server._route(
            'POST',
            '/session/start',
            headers,
            await csrf_body(access, headers, b'chat_id=-200'),
        )
        foreign = await server._route('GET', '/?campaign=-300', headers, b'')
        invalid_query = await server._route('GET', '/?campaign=nope', headers, b'')
        invalid_form = await server._route(
            'POST',
            '/session/start',
            headers,
            await csrf_body(access, headers, b'chat_id=nope'),
        )
        await database.close()
        return (
            login,
            selector,
            player_page,
            player_settings,
            player_action,
            foreign,
            invalid_query,
            invalid_form,
        )

    (
        login,
        selector,
        player_page,
        player_settings,
        player_action,
        foreign,
        invalid_query,
        invalid_form,
    ) = asyncio.run(scenario())
    assert login[1]['Location'] == '/campaigns'
    assert b'Campaign' in selector[2] and b'Second' in selector[2]
    assert 'Режим игрока'.encode() in player_page[2]
    assert b'data-local-schedule' not in player_page[2]
    assert player_settings[0] is HTTPStatus.FORBIDDEN
    assert player_action[0] is HTTPStatus.FORBIDDEN
    assert foreign[0] is HTTPStatus.FORBIDDEN
    assert invalid_query[0] is HTTPStatus.BAD_REQUEST
    assert invalid_form[0] is HTTPStatus.BAD_REQUEST


def test_master_manages_campaign_players_from_web(tmp_path):
    async def scenario():
        database, campaigns, sessions, access, bot = await setup(tmp_path)
        await campaigns.register_player(-100, 8, 'Tilly')
        server = AdminWebServer(database, access, campaigns, sessions, bot)
        token = await access.create_login(AdminIdentity(-100, 7, 'Campaign'))
        login = await server._route('GET', f'/login?token={token}', {}, b'')
        headers = {'cookie': login[1]['Set-Cookie'].split(';', 1)[0]}
        dashboard = await server._route('GET', '/', headers, b'')
        added = await server._route(
            'POST',
            '/player/invite',
            headers,
            await csrf_body(access, headers, b'chat_id=-100&user_id=9&name=Alice'),
        )
        renamed = await server._route(
            'POST',
            '/player/rename',
            headers,
            await csrf_body(access, headers, b'chat_id=-100&user_id=8&name=Tilly+Fang'),
        )
        renamed_dashboard = await server._route('GET', '/', headers, b'')
        removed = await server._route(
            'POST',
            '/player/remove',
            headers,
            await csrf_body(access, headers, b'chat_id=-100&user_id=8'),
        )
        removed_dashboard = await server._route('GET', '/', headers, b'')
        retained = await database.fetch_one(
            'SELECT name FROM characters WHERE telegram_user_id = 8'
        )
        await database.close()
        return (
            dashboard,
            added,
            renamed,
            renamed_dashboard,
            removed,
            removed_dashboard,
            retained,
            bot,
        )

    dashboard, added, renamed, renamed_dashboard, removed, removed_dashboard, retained, bot = (
        asyncio.run(scenario())
    )
    assert b'/player/invite' in dashboard[2]
    assert b'/player/rename' in dashboard[2] and b'/player/remove' in dashboard[2]
    assert added[0] is HTTPStatus.SEE_OTHER and b'Alice' not in renamed_dashboard[2]
    assert bot.publish.await_args.args == (
        'player_invited',
        {
            'chat_id': -100,
            'requester_user_id': 7,
            'target_user_id': 9,
            'character_name': 'Alice',
        },
    )
    assert renamed[0] is HTTPStatus.SEE_OTHER and b'Tilly Fang' in renamed_dashboard[2]
    assert removed[0] is HTTPStatus.SEE_OTHER and b'Tilly Fang' not in removed_dashboard[2]
    assert retained == {'name': 'Tilly Fang'}


def test_web_player_invite_validates_input_and_membership_conflict(tmp_path):
    async def scenario():
        database, campaigns, sessions, access, bot = await setup(tmp_path)
        server = AdminWebServer(database, access, campaigns, sessions, bot)
        token = await access.create_login(AdminIdentity(-100, 7, 'Campaign'))
        login = await server._route('GET', f'/login?token={token}', {}, b'')
        headers = {'cookie': login[1]['Set-Cookie'].split(';', 1)[0]}
        malformed = await server._route(
            'POST',
            '/player/invite',
            headers,
            await csrf_body(access, headers, b'chat_id=-100&user_id=nope&name=Alice'),
        )
        invalid = await server._route(
            'POST',
            '/player/invite',
            headers,
            await csrf_body(access, headers, b'chat_id=-100&user_id=0&name='),
        )
        self_conflict = await server._route(
            'POST',
            '/player/invite',
            headers,
            await csrf_body(access, headers, b'chat_id=-100&user_id=7&name=Master'),
        )
        await campaigns.register_player(-100, 8, 'Tilly')
        member_conflict = await server._route(
            'POST',
            '/player/invite',
            headers,
            await csrf_body(access, headers, b'chat_id=-100&user_id=8&name=Tilly'),
        )
        await database.close()
        return malformed, invalid, self_conflict, member_conflict

    malformed, invalid, self_conflict, member_conflict = asyncio.run(scenario())
    assert malformed[0] is HTTPStatus.BAD_REQUEST
    assert invalid[0] is HTTPStatus.BAD_REQUEST
    assert self_conflict[0] is HTTPStatus.CONFLICT
    assert member_conflict[0] is HTTPStatus.CONFLICT


def test_web_player_management_reports_invalid_and_missing_players(tmp_path):
    async def scenario():
        database, campaigns, sessions, access, bot = await setup(tmp_path)
        await campaigns.register_player(-100, 8, 'Tilly')
        server = AdminWebServer(database, access, campaigns, sessions, bot)
        token = await access.create_login(AdminIdentity(-100, 7, 'Campaign'))
        login = await server._route('GET', f'/login?token={token}', {}, b'')
        headers = {'cookie': login[1]['Set-Cookie'].split(';', 1)[0]}

        async def post(path, body):
            return await server._route(
                'POST', path, headers, await csrf_body(access, headers, body)
            )

        responses = [
            await post('/player/rename', b'chat_id=-100&user_id=nope&name=Alice'),
            await post('/player/rename', b'chat_id=-100&user_id=8&name='),
            await post('/player/rename', b'chat_id=-100&user_id=9&name=Missing'),
            await post('/player/remove', b'chat_id=-100&user_id=nope'),
            await post('/player/remove', b'chat_id=-100&user_id=9'),
        ]
        await database.close()
        return responses

    responses = asyncio.run(scenario())
    assert [response[0] for response in responses] == [
        HTTPStatus.BAD_REQUEST,
        HTTPStatus.BAD_REQUEST,
        HTTPStatus.NOT_FOUND,
        HTTPStatus.BAD_REQUEST,
        HTTPStatus.NOT_FOUND,
    ]


def test_web_transfers_master_role_to_existing_player(tmp_path):
    async def scenario():
        database, campaigns, sessions, access, bot = await setup(tmp_path)
        await campaigns.register_player(-100, 8, 'Tilly')
        server = AdminWebServer(database, access, campaigns, sessions, bot)
        old_token = await access.create_login(AdminIdentity(-100, 7, 'Campaign'))
        old_login = await server._route('GET', f'/login?token={old_token}', {}, b'')
        old_headers = {'cookie': old_login[1]['Set-Cookie'].split(';', 1)[0]}
        before = await server._route('GET', '/', old_headers, b'')
        transferred = await server._route(
            'POST',
            '/master/transfer',
            old_headers,
            await csrf_body(access, old_headers, b'chat_id=-100&user_id=8'),
        )
        old_dashboard = await server._route('GET', '/', old_headers, b'')
        denied = await server._route(
            'POST',
            '/session/start',
            old_headers,
            await csrf_body(access, old_headers, b'chat_id=-100'),
        )
        new_token = await access.create_login(AdminIdentity(-100, 8, 'Campaign'))
        new_login = await server._route('GET', f'/login?token={new_token}', {}, b'')
        new_headers = {'cookie': new_login[1]['Set-Cookie'].split(';', 1)[0]}
        new_dashboard = await server._route('GET', '/', new_headers, b'')
        await database.close()
        return before, transferred, old_dashboard, denied, new_dashboard

    before, transferred, old_dashboard, denied, new_dashboard = asyncio.run(scenario())
    assert b'/master/transfer' in before[2]
    assert transferred[0] is HTTPStatus.SEE_OTHER
    assert 'Режим игрока'.encode() in old_dashboard[2]
    assert denied[0] is HTTPStatus.FORBIDDEN
    assert b'/session/start' in new_dashboard[2]


def test_web_master_transfer_rejects_invalid_or_unregistered_target(tmp_path):
    async def scenario():
        database, campaigns, sessions, access, bot = await setup(tmp_path)
        server = AdminWebServer(database, access, campaigns, sessions, bot)
        token = await access.create_login(AdminIdentity(-100, 7, 'Campaign'))
        login = await server._route('GET', f'/login?token={token}', {}, b'')
        headers = {'cookie': login[1]['Set-Cookie'].split(';', 1)[0]}
        invalid = await server._route(
            'POST',
            '/master/transfer',
            headers,
            await csrf_body(access, headers, b'chat_id=-100&user_id=nope'),
        )
        missing = await server._route(
            'POST',
            '/master/transfer',
            headers,
            await csrf_body(access, headers, b'chat_id=-100&user_id=9'),
        )
        await database.close()
        return invalid, missing

    invalid, missing = asyncio.run(scenario())
    assert invalid[0] is HTTPStatus.BAD_REQUEST
    assert missing[0] is HTTPStatus.CONFLICT


def test_internal_api_issues_admin_link_for_master(tmp_path):
    async def scenario():
        database, campaigns, sessions, access, bot = await setup(tmp_path)
        server = AdminWebServer(
            database,
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
        server = AdminWebServer(database, access, campaigns, sessions, bot, internal_token='secret')
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
        server = AdminWebServer(database, access, campaigns, sessions, bot, internal_token='secret')
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


def test_operation_oriented_game_and_session_api(tmp_path):
    async def scenario():
        database, campaigns, sessions, access, bot = await setup(tmp_path)
        server = AdminWebServer(database, access, campaigns, sessions, bot, internal_token='secret')
        headers = {'authorization': 'Bearer secret'}
        unauthorized = await server._route('GET', '/internal/campaigns/-100/game', {}, b'')
        invalid_campaign = await server._route('GET', '/internal/campaigns/nope/game', headers, b'')
        invalid_schedule = await server._route(
            'PUT', '/internal/campaigns/-100/game', headers, b'scheduled_at=nope'
        )
        unauthorized_schedule = await server._route(
            'PUT', '/internal/campaigns/-100/game', {}, b'scheduled_at=nope'
        )
        invalid_schedule_campaign = await server._route(
            'PUT', '/internal/campaigns/nope/game', headers, b'scheduled_at=nope'
        )
        await sessions.set_default_url(-100, 'https://foundry.example', datetime.now(UTC))
        scheduled = await server._route(
            'PUT',
            '/internal/campaigns/-100/game',
            headers,
            b'scheduled_at=2026-07-20T19%3A00%3A00%2B00%3A00',
        )
        session_id = json.loads(scheduled[2])['session_id']
        shown = await server._route('GET', '/internal/campaigns/-100/game', headers, b'')
        invalid_announcement = await server._route(
            'POST',
            f'/internal/sessions/{session_id}/announcement',
            headers,
            b'message_id=nope',
        )
        unauthorized_announcement = await server._route(
            'POST', f'/internal/sessions/{session_id}/announcement', {}, b'message_id=99'
        )
        negative_announcement = await server._route(
            'POST', '/internal/sessions/-1/announcement', headers, b'message_id=99'
        )
        announcement = await server._route(
            'POST',
            f'/internal/sessions/{session_id}/announcement',
            headers,
            b'message_id=99',
        )
        invalid_start = await server._route(
            'POST', '/internal/campaigns/-100/sessions/start', headers, b'user_id=nope'
        )
        unauthorized_start = await server._route(
            'POST', '/internal/campaigns/-100/sessions/start', {}, b'user_id=7'
        )
        long_title = await server._route(
            'POST',
            '/internal/campaigns/-100/sessions/start',
            headers,
            f'user_id=7&title={"x" * 101}'.encode(),
        )
        forbidden_start = await server._route(
            'POST', '/internal/campaigns/-100/sessions/start', headers, b'user_id=8'
        )
        started = await server._route(
            'POST',
            '/internal/campaigns/-100/sessions/start',
            headers,
            b'user_id=7&title=Tower',
        )
        duplicate_start = await server._route(
            'POST', '/internal/campaigns/-100/sessions/start', headers, b'user_id=7'
        )
        forbidden_stop = await server._route(
            'POST', '/internal/campaigns/-100/sessions/stop', headers, b'user_id=8'
        )
        unauthorized_stop = await server._route(
            'POST', '/internal/campaigns/-100/sessions/stop', {}, b'user_id=7'
        )
        invalid_stop = await server._route(
            'POST', '/internal/campaigns/nope/sessions/stop', headers, b'user_id=7'
        )
        stopped = await server._route(
            'POST', '/internal/campaigns/-100/sessions/stop', headers, b'user_id=7'
        )
        second_stop = await server._route(
            'POST', '/internal/campaigns/-100/sessions/stop', headers, b'user_id=7'
        )
        planned = await sessions.get_planned(-100)
        await database.close()
        return (
            unauthorized,
            invalid_campaign,
            invalid_schedule,
            unauthorized_schedule,
            invalid_schedule_campaign,
            scheduled,
            shown,
            invalid_announcement,
            unauthorized_announcement,
            negative_announcement,
            announcement,
            invalid_start,
            unauthorized_start,
            long_title,
            forbidden_start,
            started,
            duplicate_start,
            forbidden_stop,
            unauthorized_stop,
            invalid_stop,
            stopped,
            second_stop,
            planned,
        )

    results = asyncio.run(scenario())
    assert json.loads(results[0][2])['error']['code'] == 'unauthorized'
    assert json.loads(results[1][2])['error']['code'] == 'invalid_campaign_id'
    assert json.loads(results[2][2])['error']['code'] == 'invalid_game_schedule'
    assert json.loads(results[3][2])['error']['code'] == 'unauthorized'
    assert json.loads(results[4][2])['error']['code'] == 'invalid_campaign_id'
    assert results[5][0] is HTTPStatus.OK
    assert b'Foundry' in results[6][2]
    assert json.loads(results[7][2])['error']['code'] == 'invalid_announcement'
    assert json.loads(results[8][2])['error']['code'] == 'unauthorized'
    assert json.loads(results[9][2])['error']['code'] == 'invalid_announcement'
    assert results[10][0] is HTTPStatus.OK
    assert json.loads(results[11][2])['error']['code'] == 'invalid_session_request'
    assert json.loads(results[12][2])['error']['code'] == 'unauthorized'
    assert json.loads(results[13][2])['error']['code'] == 'title_too_long'
    assert json.loads(results[14][2])['status'] == 'forbidden'
    assert json.loads(results[15][2])['status'] == 'started'
    assert json.loads(results[16][2])['status'] == 'already_active'
    assert json.loads(results[17][2])['status'] == 'forbidden'
    assert json.loads(results[18][2])['error']['code'] == 'unauthorized'
    assert json.loads(results[19][2])['error']['code'] == 'invalid_session_request'
    assert json.loads(results[20][2])['status'] == 'stopped'
    assert json.loads(results[21][2])['status'] == 'no_active_session'
    assert results[22] is None


def test_internal_role_api(tmp_path):
    async def scenario():
        database, campaigns, sessions, access, bot = await setup(tmp_path)
        server = AdminWebServer(database, access, campaigns, sessions, bot, internal_token='secret')
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
    assert roster is not None
    assert [(member.telegram_user_id, member.role) for member in roster.memberships] == [
        (20, 'master'),
        (21, 'player'),
    ]


def test_internal_web_url_api(tmp_path):
    async def scenario():
        database, campaigns, sessions, access, bot = await setup(tmp_path)
        server = AdminWebServer(
            database,
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


def test_operation_oriented_auth_role_and_config_api(tmp_path):
    async def scenario():
        database, campaigns, sessions, access, bot = await setup(tmp_path)
        identities = SQLiteLocalIdentityProvider(database)
        server = AdminWebServer(
            database,
            access,
            campaigns,
            sessions,
            bot,
            identities,
            internal_token='secret',
            web_base_url='https://default.example',
        )
        headers = {'authorization': 'Bearer secret'}
        results = [
            await server._route('POST', '/internal/auth/registration-codes', {}, b'user_id=7'),
            await server._route(
                'POST', '/internal/auth/registration-codes', headers, b'user_id=nope'
            ),
            await server._route('POST', '/internal/auth/registration-codes', headers, b'user_id=7'),
            await server._route(
                'POST', '/internal/campaigns/-100/admin-links', headers, b'user_id=8'
            ),
            await server._route(
                'POST',
                '/internal/campaigns/-100/admin-links',
                headers,
                b'user_id=7&chat_title=Campaign',
            ),
            await server._route('PUT', '/internal/campaigns/nope/master', headers, b'user_id=20'),
            await server._route(
                'PUT',
                '/internal/campaigns/-200/master',
                headers,
                b'user_id=20&chat_title=New',
            ),
            await server._route(
                'POST',
                '/internal/campaigns/-200/players',
                headers,
                b'user_id=20&name=Hero',
            ),
            await server._route(
                'POST',
                '/internal/campaigns/-200/players',
                headers,
                b'user_id=21&name=',
            ),
            await server._route(
                'POST',
                '/internal/campaigns/-200/players',
                headers,
                b'user_id=21&name=Hero',
            ),
            await server._route('GET', '/internal/campaigns/-100/foundry-url', headers, b''),
            await server._route(
                'PUT',
                '/internal/campaigns/-100/foundry-url',
                headers,
                b'foundry_url=bad',
            ),
            await server._route(
                'PUT',
                '/internal/campaigns/-100/foundry-url',
                headers,
                b'foundry_url=https%3A%2F%2Ffoundry.example',
            ),
            await server._route('GET', '/internal/campaigns/-100/foundry-url', headers, b''),
            await server._route('GET', '/internal/campaigns/-100/web-url', headers, b''),
            await server._route('PUT', '/internal/campaigns/-100/web-url', headers, b'web_url=bad'),
            await server._route(
                'PUT',
                '/internal/campaigns/-100/web-url',
                headers,
                b'web_url=https%3A%2F%2Fpanel.example%2F',
            ),
            await server._route('GET', '/internal/campaigns/-100/web-url', headers, b''),
        ]
        await campaigns.assign_master(-300, 30, 'No URL')
        no_url_server = AdminWebServer(
            database,
            access,
            campaigns,
            sessions,
            bot,
            identities,
            internal_token='secret',
        )
        extras = [
            await server._route(
                'POST', '/internal/auth/registration-codes', headers, b'user_id=404'
            ),
            await server._route(
                'POST', '/internal/campaigns/nope/admin-links', headers, b'user_id=7'
            ),
            await no_url_server._route(
                'POST', '/internal/campaigns/-300/admin-links', headers, b'user_id=30'
            ),
            await server._route('PUT', '/internal/campaigns/-200/master', {}, b'user_id=20'),
            await server._route(
                'POST', '/internal/campaigns/-200/players', {}, b'user_id=21&name=Hero'
            ),
            await server._route('GET', '/internal/campaigns/-100/foundry-url', {}, b''),
            await server._route(
                'PUT', '/internal/campaigns/-100/foundry-url', {}, b'foundry_url=https://x.test'
            ),
            await server._route('GET', '/internal/campaigns/-100/web-url', {}, b''),
            await server._route(
                'PUT', '/internal/campaigns/-100/web-url', {}, b'web_url=https://x.test'
            ),
            await server._route('GET', '/internal/campaigns/nope/foundry-url', headers, b''),
            await server._route('GET', '/internal/campaigns/nope/web-url', headers, b''),
        ]
        await database.close()
        return results, extras

    results, extras = asyncio.run(scenario())
    assert json.loads(results[0][2])['error']['code'] == 'unauthorized'
    assert json.loads(results[1][2])['error']['code'] == 'invalid_user_id'
    assert json.loads(results[2][2])['code']
    assert json.loads(results[3][2])['error']['code'] == 'campaign_master_required'
    assert json.loads(results[4][2])['url'].startswith('https://default.example/login')
    assert json.loads(results[5][2])['error']['code'] == 'invalid_role_request'
    assert results[6][0] is HTTPStatus.OK
    assert json.loads(results[7][2])['status'] == 'master_conflict'
    assert json.loads(results[8][2])['error']['code'] == 'invalid_player'
    assert json.loads(results[9][2]) == {'status': 'registered', 'name': 'Hero'}
    assert json.loads(results[10][2])['url'] is None
    assert json.loads(results[11][2])['error']['code'] == 'invalid_foundry_url'
    assert results[12][0] is HTTPStatus.OK
    assert json.loads(results[13][2])['url'] == 'https://foundry.example'
    assert json.loads(results[14][2])['url'] == 'https://default.example'
    assert json.loads(results[15][2])['error']['code'] == 'invalid_web_url'
    assert results[16][0] is HTTPStatus.OK
    assert json.loads(results[17][2])['url'] == 'https://panel.example'
    assert json.loads(extras[0][2])['error']['code'] == 'unknown_user'
    assert json.loads(extras[1][2])['error']['code'] == 'invalid_admin_link_request'
    assert json.loads(extras[2][2])['error']['code'] == 'web_url_not_configured'
    assert all(
        json.loads(response[2])['error']['code'] == 'unauthorized' for response in extras[3:9]
    )
    assert json.loads(extras[9][2])['error']['code'] == 'invalid_campaign_id'
    assert json.loads(extras[10][2])['error']['code'] == 'invalid_campaign_id'


def test_web_server_start_read_request_and_close(tmp_path):
    async def scenario():
        database, campaigns, sessions, access, bot = await setup(tmp_path)
        server = AdminWebServer(database, access, campaigns, sessions, bot)
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
        server = AdminWebServer(database, access, campaigns, sessions, bot)
        identity = AdminIdentity(-100, 7, 'Campaign')
        token = await access.create_login(identity)
        login = await server._route('GET', f'/login?token={token}', {}, b'')
        headers = {'cookie': login[1]['Set-Cookie'].split(';', 1)[0]}

        too_long = await server._route(
            'POST',
            '/session/start',
            headers,
            await csrf_body(access, headers, f'title={"x" * 101}'.encode()),
        )
        started = await server._route(
            'POST',
            '/session/start',
            headers,
            await csrf_body(access, headers, 'title=Башня'.encode()),
        )
        active_page = await server._route('GET', '/', headers, b'')
        duplicate = await server._route(
            'POST', '/session/start', headers, await csrf_body(access, headers)
        )
        stopped = await server._route(
            'POST', '/session/stop', headers, await csrf_body(access, headers)
        )
        second_stop = await server._route(
            'POST', '/session/stop', headers, await csrf_body(access, headers)
        )
        active = await sessions.get_active(-100)
        await campaigns.assign_master(-100, 8, 'Campaign')
        forbidden_start = await server._route(
            'POST', '/session/start', headers, await csrf_body(access, headers)
        )
        forbidden_stop = await server._route(
            'POST', '/session/stop', headers, await csrf_body(access, headers)
        )
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

        def get_extra_info(self, name):
            return ('127.0.0.1', 12345) if name == 'peername' else None

    async def scenario():
        database, campaigns, sessions, access, bot = await setup(tmp_path)
        server = AdminWebServer(database, access, campaigns, sessions, bot)
        reader = asyncio.StreamReader()
        reader.feed_data(b'GET / HTTP/1.1\r\nHost: localhost\r\n\r\n')
        reader.feed_eof()
        writer = Writer()
        await server._handle(reader, writer)
        await database.close()
        return writer

    writer = asyncio.run(scenario())
    assert writer.data.startswith(b'HTTP/1.1 200 OK')
    assert b'/login' in writer.data and b'/register' in writer.data
    assert b'Content-Security-Policy' in writer.data
    assert writer.closed


def test_web_trusts_forwarded_headers_only_from_configured_proxy(monkeypatch, caplog):
    monkeypatch.setenv('D20_BOT_WEB_TRUSTED_PROXIES', '10.0.0.0/8, 2001:db8::/32, invalid-network')

    assert AdminWebServer._trusted_proxy('10.2.3.4')
    assert AdminWebServer._trusted_proxy('2001:db8::1')
    assert not AdminWebServer._trusted_proxy('192.0.2.1')
    assert not AdminWebServer._trusted_proxy('not-an-address')
    assert not AdminWebServer._trusted_proxy(None)
    assert 'Invalid trusted proxy network' in caplog.messages
