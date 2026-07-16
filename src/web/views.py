from datetime import datetime
from http import HTTPStatus

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape

from commands.game_utils import ANNOUNCEMENT_TIMEZONES, game_message, game_timezone
from database.models import Session
from services.campaigns import CampaignRoster
from web.access import AdminIdentity

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


def dashboard_response(
    identity: AdminIdentity,
    planned: Session | None,
    active: Session | None,
    roster: CampaignRoster | None,
    default_url: str,
    history: list[Session] | None = None,
    announcement_timezone: str = 'Europe/Moscow',
    csrf_token: str = '',
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
    )
    return HTTPStatus.OK, {}, document.encode()


def settings_response(
    title: str, default_url: str, announcement_timezone: str, csrf_token: str = ''
) -> tuple[HTTPStatus, dict[str, str], bytes]:
    document = TEMPLATES.get_template('settings.html').render(
        title=title,
        default_url=default_url,
        announcement_timezone=announcement_timezone,
        timezones=ANNOUNCEMENT_TIMEZONES,
        csrf_token=csrf_token,
    )
    return HTTPStatus.OK, {}, document.encode()
