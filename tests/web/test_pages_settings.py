import asyncio
from http import HTTPStatus

from tests.web.support import AdminWebServer, csrf_body, setup
from web.access import AdminIdentity


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
