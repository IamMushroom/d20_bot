from datetime import datetime
from http import HTTPStatus

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape

from domain import Campaign, Session
from game import ANNOUNCEMENT_TIMEZONES, game_message, game_timezone
from services.campaigns import CampaignRoster
from web.access import ActiveWebSession, AdminIdentity

TEMPLATES = Environment(
    loader=PackageLoader('web'),
    autoescape=select_autoescape(('html',)),
    undefined=StrictUndefined,
)


def _game_datetime(value: datetime) -> str:
    return value.astimezone(game_timezone()).strftime('%d.%m.%Y %H:%M')


TEMPLATES.filters['game_datetime'] = _game_datetime


def page_response(status: HTTPStatus, content: str) -> tuple[HTTPStatus, dict[str, str], bytes]:
    document = TEMPLATES.get_template('message.html').render(
        content=content,
        status_code=status.value,
        title=status.phrase,
        is_error=status.value >= 400,
    )
    return status, {}, document.encode()


def login_response(
    *, error: str = '', registration: bool = False, code: str = ''
) -> tuple[HTTPStatus, dict[str, str], bytes]:
    document = TEMPLATES.get_template('login.html').render(
        title='Регистрация' if registration else 'Вход',
        error=error,
        registration=registration,
        code=code,
    )
    return (HTTPStatus.BAD_REQUEST if error else HTTPStatus.OK), {}, document.encode()


def landing_response() -> tuple[HTTPStatus, dict[str, str], bytes]:
    document = TEMPLATES.get_template('landing.html').render(title='D20 Control')
    return HTTPStatus.OK, {}, document.encode()


def dashboard_response(
    identity: AdminIdentity,
    planned: Session | None,
    active: Session | None,
    roster: CampaignRoster | None,
    default_url: str,
    history: list[Session] | None = None,
    announcement_timezone: str = 'Europe/Moscow',
    csrf_token: str = '',
    role: str = 'master',
) -> tuple[HTTPStatus, dict[str, str], bytes]:
    document = TEMPLATES.get_template('dashboard.html').render(
        title=(roster.campaign.title if roster and roster.campaign.title else None)
        or identity.chat_title
        or str(identity.chat_id),
        planned_message=game_message(planned, announcement_timezone) if planned else None,
        active=active,
        roster=roster,
        default_url=default_url,
        history=history or [],
        csrf_token=csrf_token,
        role=role,
        campaign_chat_id=identity.chat_id,
    )
    return HTTPStatus.OK, {}, document.encode()


def settings_response(
    title: str,
    default_url: str,
    announcement_timezone: str,
    csrf_token: str = '',
    campaign_chat_id: int = 0,
) -> tuple[HTTPStatus, dict[str, str], bytes]:
    document = TEMPLATES.get_template('settings.html').render(
        title=title,
        default_url=default_url,
        announcement_timezone=announcement_timezone,
        timezones=ANNOUNCEMENT_TIMEZONES,
        csrf_token=csrf_token,
        campaign_chat_id=campaign_chat_id,
    )
    return HTTPStatus.OK, {}, document.encode()


def campaigns_response(
    campaigns: tuple[Campaign, ...], initial_chat_id: int, csrf_token: str = ''
) -> tuple[HTTPStatus, dict[str, str], bytes]:
    document = TEMPLATES.get_template('campaigns.html').render(
        campaigns=campaigns, initial_chat_id=initial_chat_id, csrf_token=csrf_token
    )
    return HTTPStatus.OK, {}, document.encode()


def sessions_response(
    sessions: tuple[ActiveWebSession, ...], csrf_token: str
) -> tuple[HTTPStatus, dict[str, str], bytes]:
    document = TEMPLATES.get_template('sessions.html').render(
        sessions=sessions, csrf_token=csrf_token
    )
    return HTTPStatus.OK, {}, document.encode()
