from datetime import UTC, datetime
from http import HTTPStatus

from domain import Campaign, Character, Session
from services.campaigns import CampaignRoster
from web.access import AdminIdentity
from web.views import dashboard_response, page_response, settings_response

NOW = datetime(2026, 7, 16, tzinfo=UTC)


def session(*, title=None, active=False, finished=False):
    return Session(
        id=1,
        campaign_id=1,
        number=2,
        title=title,
        scheduled_at=NOW,
        started_at=NOW if active else None,
        finished_at=NOW if finished else None,
        foundry_url='https://foundry.example',
        message_id=None,
        updated_at=NOW,
    )


def test_page_response_escapes_plain_content():
    status, headers, content = page_response(HTTPStatus.BAD_REQUEST, '<script>bad</script>')

    assert status is HTTPStatus.BAD_REQUEST
    assert headers == {}
    assert b'&lt;script&gt;bad&lt;/script&gt;' in content
    assert b'<script>bad</script>' not in content
    assert b'message--error' in content
    assert b'400' in content


def test_dashboard_response_escapes_campaign_and_character_data():
    campaign = Campaign(1, -100, '<Campaign>', NOW)
    character = Character(1, 1, 8, '<Tilly>', NOW, NOW)
    response = dashboard_response(
        AdminIdentity(-100, 7, '<Campaign>'),
        session(),
        None,
        CampaignRoster(campaign, (character,)),
        'https://foundry.example/?a=1&b=2',
    )

    assert response[0] is HTTPStatus.OK
    assert b'&lt;Campaign&gt;' in response[2]
    assert b'&lt;Tilly&gt;' in response[2]
    assert b'a=1&amp;b=2' in response[2]
    assert 'Начать сессию'.encode() in response[2]
    assert b'class="grid"' in response[2]
    assert b'class="card card--wide"' in response[2]


def test_dashboard_response_renders_active_and_empty_campaign_states():
    active = dashboard_response(
        AdminIdentity(-100, 7, None), None, session(title='<Tower>', active=True), None, ''
    )

    assert 'Активная сессия №2'.encode() in active[2]
    assert b'&lt;Tower&gt;' in active[2]
    assert 'Состав кампании не найден'.encode() in active[2]
    assert 'Игра пока не назначена'.encode() in active[2]
    assert b'badge--success' in active[2]
    assert 'Завершённых игр пока нет'.encode() in active[2]


def test_dashboard_response_renders_theme_controls_and_history():
    response = dashboard_response(
        AdminIdentity(-100, 7, 'Campaign'),
        None,
        None,
        None,
        '',
        [session(title='<Finale>', finished=True)],
    )

    assert b'data-theme-choice="auto"' in response[2]
    assert b'data-theme-choice="light"' in response[2]
    assert b'data-theme-choice="dark"' in response[2]
    assert b'src="/static/app.js"' in response[2]
    assert 'Прошлые игры'.encode() in response[2]
    assert b'&lt;Finale&gt;' in response[2]
    assert b'16.07.2026 03:00' in response[2]


def test_settings_response_renders_saved_values_safely():
    response = settings_response('<Campaign>', 'https://foundry.example', 'Asia/Yerevan')

    assert response[0] is HTTPStatus.OK
    assert b'&lt;Campaign&gt;' in response[2]
    assert b'value="Asia/Yerevan" selected' in response[2]
    assert 'Стандартный адрес Foundry'.encode() in response[2]
