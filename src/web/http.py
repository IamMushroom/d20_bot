import asyncio
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from http import HTTPStatus
from urllib.parse import parse_qs, urlsplit

MAX_REQUEST_SIZE = 16 * 1024
ResponseTuple = tuple[HTTPStatus, dict[str, str], bytes]


@dataclass(frozen=True, slots=True)
class Request:
    method: str
    target: str
    headers: Mapping[str, str]
    body: bytes
    remote_host: str | None = None
    path: str = field(init=False)
    query: Mapping[str, list[str]] = field(init=False)

    def __post_init__(self) -> None:
        url = urlsplit(self.target)
        object.__setattr__(self, 'path', url.path)
        object.__setattr__(self, 'query', parse_qs(url.query))

    @property
    def form(self) -> Mapping[str, list[str]]:
        return parse_qs(self.body.decode())

    def __iter__(self) -> Iterator[object]:
        """Keep compatibility with the legacy request tuple during migration."""
        yield self.method
        yield self.target
        yield self.headers
        yield self.body


@dataclass(frozen=True, slots=True)
class Response:
    status: HTTPStatus
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes = b''

    @classmethod
    def from_tuple(cls, response: ResponseTuple) -> Response:
        return cls(*response)

    def as_tuple(self) -> ResponseTuple:
        return self.status, dict(self.headers), self.body


async def read_request(reader: asyncio.StreamReader, remote_host: str | None = None) -> Request:
    raw_head = await reader.readuntil(b'\r\n\r\n')
    if len(raw_head) > MAX_REQUEST_SIZE:
        raise ValueError('request too large')
    lines = raw_head.decode('ascii').split('\r\n')
    method, target, _version = lines[0].split(' ', 2)
    headers = {
        name.lower(): value.strip()
        for line in lines[1:]
        if line
        for name, value in [line.split(':', 1)]
    }
    length = int(headers.get('content-length', '0'))
    if length < 0 or length > MAX_REQUEST_SIZE:
        raise ValueError('request too large')
    return Request(method, target, headers, await reader.readexactly(length), remote_host)


def serialize_response(response: Response) -> bytes:
    headers = {
        'Content-Type': 'text/html; charset=utf-8',
        'Content-Length': str(len(response.body)),
        'Connection': 'close',
        'X-Content-Type-Options': 'nosniff',
        'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; script-src 'self' 'unsafe-inline'; form-action 'self'",
        **response.headers,
    }
    head = f'HTTP/1.1 {response.status.value} {response.status.phrase}\r\n' + ''.join(
        f'{name}: {value}\r\n' for name, value in headers.items()
    )
    return head.encode() + b'\r\n' + response.body
