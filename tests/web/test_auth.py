import asyncio
import json
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import AsyncMock

from auth import RateLimitResult, SQLiteLocalIdentityProvider
from database import SQLiteDatabase, apply_migrations
from tests.web.support import MIGRATIONS, AdminWebServer, csrf_body, setup
from web import AdminAccessService
from web.access import AdminIdentity
from web.session_store import SQLiteWebSessionStore


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


def test_local_web_auth_errors(tmp_path):
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
        ]
        disabled = AdminWebServer(
            database, access, campaigns, sessions, bot, internal_token='secret'
        )
        pages.extend(
            [
                await disabled._route('POST', '/login', {}, b'login=x&password=y'),
                await disabled._route('POST', '/register', {}, b'code=x'),
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
    assert json.loads(responses[2][2])['error']['code'] == 'rate_limited'
    assert json.loads(responses[3][2])['error']['code'] == 'rate_limited'
    assert limiter.hit.await_count == 4


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
