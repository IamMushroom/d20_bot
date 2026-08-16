import json
import secrets
from collections.abc import Mapping
from datetime import timedelta
from http import HTTPStatus

from auth import RateLimiter
from web.http import Request, ResponseTuple


class ApiEndpoint:
    def __init__(self, internal_token: str, rate_limiter: RateLimiter | None = None) -> None:
        self._internal_token = internal_token
        self._rate_limiter = rate_limiter

    def _authorized(self, headers: Mapping[str, str]) -> bool:
        authorization = headers.get('authorization', '')
        supplied = (
            authorization.removeprefix('Bearer ') if authorization.startswith('Bearer ') else ''
        )
        return bool(self._internal_token) and secrets.compare_digest(supplied, self._internal_token)

    def _require_authorization(self, request: Request) -> ResponseTuple | None:
        if self._authorized(request.headers):
            return None
        return self._error(
            HTTPStatus.UNAUTHORIZED, 'unauthorized', 'A valid Core bearer token is required.'
        )

    @staticmethod
    def _path_integer(request: Request, name: str) -> int | None:
        try:
            return int(request.path_parameters[name])
        except KeyError, ValueError:
            return None

    def _campaign_and_user(self, request: Request) -> tuple[int, int] | None:
        chat_id = self._path_integer(request, 'chat_id')
        try:
            user_id = int(request.form['user_id'][0])
        except KeyError, ValueError, IndexError:
            return None
        return (chat_id, user_id) if chat_id is not None else None

    async def _rate_limit(self, key: str, limit: int, window: timedelta) -> ResponseTuple | None:
        if self._rate_limiter is None:
            return None
        result = await self._rate_limiter.hit(key, limit=limit, window=window)
        if result.allowed:
            return None
        status, headers, body = self._json(
            HTTPStatus.TOO_MANY_REQUESTS,
            {'error': 'rate_limited', 'retry_after': result.retry_after},
        )
        return status, {**headers, 'Retry-After': str(result.retry_after)}, body

    @classmethod
    def _normalized_rate_limit(cls, response: ResponseTuple) -> ResponseTuple:
        status, headers, _body = response
        normalized = cls._error(status, 'rate_limited', 'Too many requests. Retry later.')
        return normalized[0], {**normalized[1], **headers}, normalized[2]

    @staticmethod
    def _json(status: HTTPStatus, payload: Mapping[str, object]) -> ResponseTuple:
        return (
            status,
            {'Content-Type': 'application/json; charset=utf-8'},
            json.dumps(payload, ensure_ascii=False).encode(),
        )

    @classmethod
    def _error(cls, status: HTTPStatus, code: str, message: str) -> ResponseTuple:
        return cls._json(status, {'error': {'code': code, 'message': message}})
