import asyncio
import json
from datetime import UTC, datetime
from http import HTTPStatus

from auth import SQLiteLocalIdentityProvider
from tests.web.support import AdminWebServer, setup


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


def test_deprecated_api_routes_are_not_registered(tmp_path):
    async def scenario():
        database, campaigns, sessions, access, outbox = await setup(tmp_path)
        server = AdminWebServer(
            database, access, campaigns, sessions, outbox, internal_token='secret'
        )
        paths = {path for _method, path in server._router._routes}
        await database.close()
        return paths

    assert not any(path == '/api' or path.startswith('/api/') for path in asyncio.run(scenario()))
