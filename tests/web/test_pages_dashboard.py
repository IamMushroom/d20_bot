import asyncio
from http import HTTPStatus

from tests.web.support import AdminWebServer, csrf_body, setup
from web.access import AdminIdentity


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
