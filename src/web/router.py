import re
from collections.abc import Awaitable, Callable

from web.http import Request, ResponseTuple

Handler = Callable[[Request], Awaitable[ResponseTuple]]


class Router:
    def __init__(self) -> None:
        self._routes: dict[tuple[str, str], Handler] = {}
        self._patterns: list[tuple[str, str, re.Pattern[str], Handler]] = []

    def add(self, method: str, path: str, handler: Handler) -> None:
        key = method.upper(), path
        if key in self._routes:
            raise ValueError(f'route already registered: {method} {path}')
        self._routes[key] = handler
        if '{' in path:
            expression = re.sub(
                r'\{([A-Za-z_][A-Za-z0-9_]*)\}',
                lambda match: f'(?P<{match.group(1)}>[^/]+)',
                re.escape(path).replace(r'\{', '{').replace(r'\}', '}'),
            )
            self._patterns.append((method.upper(), path, re.compile(f'^{expression}$'), handler))

    async def dispatch(self, request: Request) -> ResponseTuple | None:
        handler = self._routes.get((request.method.upper(), request.path))
        if handler is not None:
            return await handler(request)
        for method, _path, pattern, candidate in self._patterns:
            match = pattern.fullmatch(request.path)
            if method == request.method.upper() and match is not None:
                return await candidate(request.with_path_parameters(match.groupdict()))
        return None

    def supports_path(self, path: str) -> bool:
        return any(
            route_path == path or pattern.fullmatch(path) is not None
            for _method, route_path, pattern, _handler in self._patterns
        ) or any(route_path == path for _method, route_path in self._routes)
