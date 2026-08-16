import asyncio
from http import HTTPStatus

from tests.web.support import AdminWebServer, csrf_body, setup
from web.access import AdminIdentity


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
