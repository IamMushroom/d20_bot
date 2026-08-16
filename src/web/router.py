from collections.abc import Awaitable, Callable

from web.http import Request, ResponseTuple

Handler = Callable[[Request], Awaitable[ResponseTuple]]


class Router:
    def __init__(self) -> None:
        self._routes: dict[tuple[str, str], Handler] = {}

    def add(self, method: str, path: str, handler: Handler) -> None:
        key = method.upper(), path
        if key in self._routes:
            raise ValueError(f'route already registered: {method} {path}')
        self._routes[key] = handler

    async def dispatch(self, request: Request) -> ResponseTuple | None:
        handler = self._routes.get((request.method.upper(), request.path))
        return await handler(request) if handler is not None else None

    def supports_path(self, path: str) -> bool:
        return any(route_path == path for _method, route_path in self._routes)
