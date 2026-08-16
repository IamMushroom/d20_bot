from http import HTTPStatus

from services import OutboxService
from web.api.common import ApiEndpoint
from web.http import Request, ResponseTuple


class EventsApi(ApiEndpoint):
    def __init__(self, outbox: OutboxService, token: str) -> None:
        super().__init__(token)
        self._outbox = outbox

    async def list_events(self, request: Request) -> ResponseTuple:
        unauthorized = self._require_authorization(request)
        if unauthorized is not None:
            return unauthorized
        events = await self._outbox.pending()
        return self._json(
            HTTPStatus.OK,
            {
                'events': [
                    {'id': event.id, 'type': event.event_type, 'payload': event.payload}
                    for event in events
                ]
            },
        )

    async def acknowledge_event(self, request: Request) -> ResponseTuple:
        unauthorized = self._require_authorization(request)
        if unauthorized is not None:
            return unauthorized
        try:
            event_id = int(request.path_parameters['event_id'])
            if event_id <= 0:
                raise ValueError
        except KeyError, ValueError:
            return self._error(
                HTTPStatus.BAD_REQUEST, 'invalid_event_id', 'Event ID must be a positive integer.'
            )
        await self._outbox.acknowledge(event_id)
        return self._json(HTTPStatus.OK, {'ok': True})
