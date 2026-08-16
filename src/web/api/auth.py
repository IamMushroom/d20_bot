from datetime import timedelta
from http import HTTPStatus

from auth import IdentityProvider, RateLimiter, UnknownTelegramUser
from web.api.common import ApiEndpoint
from web.http import Request, ResponseTuple


class AuthApi(ApiEndpoint):
    def __init__(
        self, identities: IdentityProvider | None, rate_limiter: RateLimiter | None, token: str
    ) -> None:
        super().__init__(token, rate_limiter)
        self._identities = identities

    async def create_registration_code(self, request: Request) -> ResponseTuple:
        unauthorized = self._require_authorization(request)
        if unauthorized is not None:
            return unauthorized
        if self._identities is None:
            return self._error(
                HTTPStatus.SERVICE_UNAVAILABLE, 'auth_disabled', 'Local authentication is disabled.'
            )
        try:
            user_id = int(request.form['user_id'][0])
        except KeyError, ValueError, IndexError:
            return self._error(
                HTTPStatus.BAD_REQUEST, 'invalid_user_id', 'User ID must be an integer.'
            )
        limited = await self._rate_limit(f'registration-code:{user_id}', 5, timedelta(minutes=15))
        if limited is not None:
            return self._normalized_rate_limit(limited)
        try:
            code = await self._identities.issue_registration_code(user_id)
        except UnknownTelegramUser:
            return self._error(
                HTTPStatus.NOT_FOUND, 'unknown_user', 'Telegram user is not known to Core.'
            )
        return self._json(HTTPStatus.OK, {'code': code})
