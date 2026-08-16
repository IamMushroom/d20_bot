from datetime import UTC, datetime
from http import HTTPStatus
from os import getenv

from game import game_message, valid_url
from services import SessionService
from web.api.common import ApiEndpoint
from web.http import Request, ResponseTuple


class GamesApi(ApiEndpoint):
    def __init__(self, sessions: SessionService, token: str) -> None:
        super().__init__(token)
        self._sessions = sessions

    async def get_game(self, request: Request) -> ResponseTuple:
        unauthorized = self._require_authorization(request)
        if unauthorized is not None:
            return unauthorized
        chat_id = self._path_integer(request, 'chat_id')
        if chat_id is None:
            return self._error(
                HTTPStatus.BAD_REQUEST, 'invalid_campaign_id', 'Campaign ID must be an integer.'
            )
        session = await self._sessions.get_planned(chat_id)
        timezone_name = await self._sessions.get_announcement_timezone(chat_id)
        message = (
            game_message(session, timezone_name)
            if session
            else '📅 Следующая игра пока не назначена.'
        )
        return self._json(HTTPStatus.OK, {'message': message})

    async def schedule_game(self, request: Request) -> ResponseTuple:
        unauthorized = self._require_authorization(request)
        if unauthorized is not None:
            return unauthorized
        chat_id = self._path_integer(request, 'chat_id')
        if chat_id is None:
            return self._error(
                HTTPStatus.BAD_REQUEST, 'invalid_campaign_id', 'Campaign ID must be an integer.'
            )
        form = request.form
        try:
            scheduled_at = datetime.fromisoformat(form['scheduled_at'][0])
            chat_title = form.get('chat_title', [''])[0] or None
            foundry_url = form.get('foundry_url', [''])[0]
            if not foundry_url:
                foundry_url = await self._sessions.get_default_url(chat_id) or getenv(
                    'D20_BOT_FOUNDRY_URL', ''
                )
            if scheduled_at.tzinfo is None or not valid_url(foundry_url):
                raise ValueError
        except KeyError, ValueError, IndexError:
            return self._error(
                HTTPStatus.BAD_REQUEST,
                'invalid_game_schedule',
                'A timezone-aware date and valid Foundry URL are required.',
            )
        result = await self._sessions.schedule(
            chat_id, chat_title, scheduled_at.astimezone(UTC), foundry_url
        )
        return self._json(
            HTTPStatus.OK,
            {
                'session_id': result.session.id,
                'message': game_message(
                    result.session, await self._sessions.get_announcement_timezone(chat_id)
                ),
                'previous_message_id': result.previous_message_id,
            },
        )

    async def set_announcement(self, request: Request) -> ResponseTuple:
        unauthorized = self._require_authorization(request)
        if unauthorized is not None:
            return unauthorized
        session_id = self._path_integer(request, 'session_id')
        try:
            message_id = int(request.form['message_id'][0])
            if session_id is None or session_id <= 0 or message_id <= 0:
                raise ValueError
        except KeyError, ValueError, IndexError:
            return self._error(
                HTTPStatus.BAD_REQUEST,
                'invalid_announcement',
                'Session ID and message ID must be positive integers.',
            )
        await self._sessions.set_announcement(session_id, message_id)
        return self._json(HTTPStatus.OK, {'ok': True})

    async def get_foundry_url(self, request: Request) -> ResponseTuple:
        unauthorized = self._require_authorization(request)
        if unauthorized is not None:
            return unauthorized
        chat_id = self._path_integer(request, 'chat_id')
        if chat_id is None:
            return self._error(
                HTTPStatus.BAD_REQUEST, 'invalid_campaign_id', 'Campaign ID must be an integer.'
            )
        url = await self._sessions.get_default_url(chat_id) or getenv('D20_BOT_FOUNDRY_URL', '')
        return self._json(HTTPStatus.OK, {'url': url if valid_url(url) else None})

    async def set_foundry_url(self, request: Request) -> ResponseTuple:
        unauthorized = self._require_authorization(request)
        if unauthorized is not None:
            return unauthorized
        chat_id = self._path_integer(request, 'chat_id')
        foundry_url = request.form.get('foundry_url', [''])[0]
        if chat_id is None or not valid_url(foundry_url):
            return self._error(
                HTTPStatus.BAD_REQUEST,
                'invalid_foundry_url',
                'Campaign ID and a valid Foundry URL are required.',
            )
        await self._sessions.set_default_url(chat_id, foundry_url, datetime.now(UTC))
        return self._json(HTTPStatus.OK, {'ok': True})
