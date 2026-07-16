from http import HTTPStatus

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape

from commands.game_utils import game_message
from database.models import Session
from services.campaigns import CampaignRoster
from web.access import AdminIdentity

TEMPLATES = Environment(
    loader=PackageLoader('web'),
    autoescape=select_autoescape(('html',)),
    undefined=StrictUndefined,
)


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
) -> tuple[HTTPStatus, dict[str, str], bytes]:
    document = TEMPLATES.get_template('dashboard.html').render(
        title=identity.chat_title or str(identity.chat_id),
        planned_message=game_message(planned) if planned else None,
        active=active,
        roster=roster,
        default_url=default_url,
    )
    return HTTPStatus.OK, {}, document.encode()
