import asyncio
from http import HTTPStatus

from tests.web.support import AdminWebServer, csrf_body, setup
from web.access import AdminIdentity


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
