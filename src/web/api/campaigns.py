from datetime import UTC, datetime, timedelta
from http import HTTPStatus

from auth import RateLimiter
from game import valid_url
from services import CampaignService, PlayerRegistrationStatus, SessionService
from web.access import AdminAccessService, AdminIdentity
from web.api.common import ApiEndpoint
from web.http import Request, ResponseTuple


class CampaignsApi(ApiEndpoint):
    def __init__(
        self,
        access: AdminAccessService,
        campaigns: CampaignService,
        sessions: SessionService,
        rate_limiter: RateLimiter | None,
        token: str,
        web_base_url: str,
    ) -> None:
        super().__init__(token, rate_limiter)
        self._access = access
        self._campaigns = campaigns
        self._sessions = sessions
        self._web_base_url = web_base_url

    async def create_admin_link(self, request: Request) -> ResponseTuple:
        unauthorized = self._require_authorization(request)
        if unauthorized is not None:
            return unauthorized
        chat_id = self._path_integer(request, 'chat_id')
        try:
            user_id = int(request.form['user_id'][0])
            chat_title = request.form.get('chat_title', [None])[0] or None
            if chat_id is None:
                raise ValueError
        except KeyError, ValueError, IndexError:
            return self._error(
                HTTPStatus.BAD_REQUEST,
                'invalid_admin_link_request',
                'Campaign ID and user ID must be integers.',
            )
        if not await self._campaigns.is_master(chat_id, user_id):
            return self._error(
                HTTPStatus.FORBIDDEN,
                'campaign_master_required',
                'Only the campaign master may create an admin link.',
            )
        limited = await self._rate_limit(f'admin-link:{user_id}', 5, timedelta(minutes=10))
        if limited is not None:
            return self._normalized_rate_limit(limited)
        base_url = await self._sessions.get_web_base_url(chat_id) or self._web_base_url
        if not base_url:
            return self._error(
                HTTPStatus.CONFLICT, 'web_url_not_configured', 'Web panel URL is not configured.'
            )
        token = await self._access.create_login(AdminIdentity(chat_id, user_id, chat_title))
        return self._json(HTTPStatus.OK, {'url': f'{base_url.rstrip("/")}/login?token={token}'})

    async def assign_master(self, request: Request) -> ResponseTuple:
        unauthorized = self._require_authorization(request)
        if unauthorized is not None:
            return unauthorized
        identifiers = self._campaign_and_user(request)
        if identifiers is None:
            return self._error(
                HTTPStatus.BAD_REQUEST,
                'invalid_role_request',
                'Campaign ID and user ID must be integers.',
            )
        chat_id, user_id = identifiers
        await self._campaigns.assign_master(
            chat_id, user_id, request.form.get('chat_title', [''])[0] or None
        )
        return self._json(HTTPStatus.OK, {'ok': True})

    async def register_player(self, request: Request) -> ResponseTuple:
        unauthorized = self._require_authorization(request)
        if unauthorized is not None:
            return unauthorized
        identifiers = self._campaign_and_user(request)
        name = request.form.get('name', [''])[0].strip()
        if identifiers is None or not name or len(name) > 16:
            return self._error(
                HTTPStatus.BAD_REQUEST,
                'invalid_player',
                'User ID and a player name of 1 to 16 characters are required.',
            )
        result = await self._campaigns.register_player(
            *identifiers, name, request.form.get('chat_title', [''])[0] or None
        )
        if result.status is PlayerRegistrationStatus.MASTER_CONFLICT:
            return self._json(HTTPStatus.OK, {'status': 'master_conflict'})
        assert result.character is not None
        return self._json(HTTPStatus.OK, {'status': 'registered', 'name': result.character.name})

    async def get_web_url(self, request: Request) -> ResponseTuple:
        unauthorized = self._require_authorization(request)
        if unauthorized is not None:
            return unauthorized
        chat_id = self._path_integer(request, 'chat_id')
        if chat_id is None:
            return self._error(
                HTTPStatus.BAD_REQUEST, 'invalid_campaign_id', 'Campaign ID must be an integer.'
            )
        url = await self._sessions.get_web_base_url(chat_id) or self._web_base_url
        return self._json(HTTPStatus.OK, {'url': url or None})

    async def set_web_url(self, request: Request) -> ResponseTuple:
        unauthorized = self._require_authorization(request)
        if unauthorized is not None:
            return unauthorized
        chat_id = self._path_integer(request, 'chat_id')
        web_url = request.form.get('web_url', [''])[0].rstrip('/')
        if chat_id is None or not valid_url(web_url):
            return self._error(
                HTTPStatus.BAD_REQUEST,
                'invalid_web_url',
                'Campaign ID and a valid web URL are required.',
            )
        await self._sessions.set_web_base_url(chat_id, web_url, datetime.now(UTC))
        return self._json(HTTPStatus.OK, {'ok': True})
