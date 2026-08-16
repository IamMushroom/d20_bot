from http import HTTPStatus

from services import SessionService, SessionStartStatus, SessionStopStatus
from web.api.common import ApiEndpoint
from web.http import Request, ResponseTuple


class SessionsApi(ApiEndpoint):
    def __init__(self, sessions: SessionService, token: str) -> None:
        super().__init__(token)
        self._sessions = sessions

    async def start(self, request: Request) -> ResponseTuple:
        unauthorized = self._require_authorization(request)
        if unauthorized is not None:
            return unauthorized
        identifiers = self._campaign_and_user(request)
        if identifiers is None:
            return self._error(
                HTTPStatus.BAD_REQUEST,
                'invalid_session_request',
                'Campaign ID and user ID must be integers.',
            )
        chat_id, user_id = identifiers
        title = request.form.get('title', [''])[0].strip() or None
        if title is not None and len(title) > 100:
            return self._error(
                HTTPStatus.BAD_REQUEST, 'title_too_long', 'Session title exceeds 100 characters.'
            )
        result = await self._sessions.start(chat_id, user_id, title)
        if result.status is SessionStartStatus.FORBIDDEN:
            return self._json(HTTPStatus.OK, {'status': 'forbidden'})
        if result.status is SessionStartStatus.ALREADY_ACTIVE:
            return self._json(HTTPStatus.OK, {'status': 'already_active'})
        session = result.session
        assert session is not None
        return self._json(
            HTTPStatus.OK,
            {
                'status': 'started',
                'number': session.number,
                'title': session.title,
                'announcement_message_id': result.announcement_message_id,
            },
        )

    async def stop(self, request: Request) -> ResponseTuple:
        unauthorized = self._require_authorization(request)
        if unauthorized is not None:
            return unauthorized
        identifiers = self._campaign_and_user(request)
        if identifiers is None:
            return self._error(
                HTTPStatus.BAD_REQUEST,
                'invalid_session_request',
                'Campaign ID and user ID must be integers.',
            )
        result = await self._sessions.stop(*identifiers)
        if result.status is SessionStopStatus.FORBIDDEN:
            return self._json(HTTPStatus.OK, {'status': 'forbidden'})
        if result.status is SessionStopStatus.NO_ACTIVE_SESSION:
            return self._json(HTTPStatus.OK, {'status': 'no_active_session'})
        session = result.session
        assert session is not None
        return self._json(HTTPStatus.OK, {'status': 'stopped', 'number': session.number})
