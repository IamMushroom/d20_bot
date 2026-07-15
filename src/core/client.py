import asyncio
import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class CoreClientError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class CoreClient:
    base_url: str
    token: str

    async def create_admin_link(self, chat_id: int, user_id: int, chat_title: str | None) -> str:
        return await asyncio.to_thread(self._create_admin_link, chat_id, user_id, chat_title)

    def _create_admin_link(self, chat_id: int, user_id: int, chat_title: str | None) -> str:
        body = urlencode(
            {'chat_id': chat_id, 'user_id': user_id, 'chat_title': chat_title or ''}
        ).encode()
        request = Request(
            f'{self.base_url.rstrip("/")}/api/admin-link',
            data=body,
            headers={
                'Authorization': f'Bearer {self.token}',
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            method='POST',
        )
        try:
            with urlopen(request, timeout=5) as response:
                payload = json.load(response)
        except HTTPError as error:
            raise CoreClientError(f'Core returned HTTP {error.code}') from error
        except (URLError, TimeoutError, json.JSONDecodeError) as error:
            raise CoreClientError('Core is unavailable') from error
        url = payload.get('url')
        if not isinstance(url, str) or not url:
            raise CoreClientError('Core returned an invalid response')
        return url
