from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from database import SQLiteDatabase, apply_migrations
from database.repositories import (
    CampaignRepository,
    CharacterRepository,
    GameConfigRepository,
    MembershipRepository,
    SessionRepository,
)
from services import CampaignService, GameWorkflowService, SessionService
from web import AdminAccessService
from web import AdminWebServer as _AdminWebServer
from web.session_store import SQLiteWebSessionStore

MIGRATIONS = Path(__file__).resolve().parents[2] / 'migrations'


def campaign_service(database):
    return CampaignService(
        database,
        CampaignRepository(database),
        CharacterRepository(database),
        MembershipRepository(database),
    )


def session_service(database):
    return SessionService(
        CampaignRepository(database),
        SessionRepository(database),
        GameConfigRepository(database),
        MembershipRepository(database),
    )


class AdminWebServer(_AdminWebServer):
    def __init__(self, database, access, campaigns, sessions, outbox, *args, **kwargs):
        workflows = GameWorkflowService(database, sessions, outbox)
        super().__init__(workflows, access, campaigns, sessions, outbox, *args, **kwargs)


async def setup(tmp_path):
    database = await SQLiteDatabase.connect(str(tmp_path / 'web.sqlite3'))
    await apply_migrations(database, MIGRATIONS)
    campaigns = campaign_service(database)
    sessions = session_service(database)
    await campaigns.assign_master(-100, 7, 'Campaign')
    access = AdminAccessService(SQLiteWebSessionStore(database))
    outbox = SimpleNamespace(
        send_message=AsyncMock(return_value=SimpleNamespace(id=55)),
        pin_chat_message=AsyncMock(),
        unpin_chat_message=AsyncMock(),
        publish=AsyncMock(),
        pending=AsyncMock(return_value=[]),
        acknowledge=AsyncMock(),
    )
    return database, campaigns, sessions, access, outbox


async def csrf_body(access, headers, body=b''):
    session_id = headers['cookie'].split('=', 1)[1]
    token = await access.csrf_token(session_id)
    assert token is not None
    return body + (b'&' if body else b'') + f'csrf_token={token}'.encode()
