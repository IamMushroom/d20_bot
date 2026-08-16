import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from os import getenv
from urllib.parse import parse_qs, urlsplit

from auth import (
    AuthenticationError,
    IdentityProvider,
    InvalidRegistrationCode,
    LoginAlreadyExists,
    RateLimiter,
)
from game import ANNOUNCEMENT_TIMEZONES, valid_url
from services import (
    CampaignService,
    GameWorkflowService,
    SessionService,
    SessionStartStatus,
    SessionStopStatus,
)
from web.access import AdminAccessService, AdminIdentity
from web.http import Request, ResponseTuple
from web.middleware import client_ip, cookie, session_cookie
from web.views import (
    campaigns_response,
    dashboard_response,
    landing_response,
    login_response,
    page_response,
    sessions_response,
    settings_response,
)


@dataclass(frozen=True, slots=True)
class _PageContext:
    identity: AdminIdentity
    session_id: str
    form: Mapping[str, list[str]]


class PageHandlers:
    def __init__(
        self,
        access: AdminAccessService,
        campaigns: CampaignService,
        sessions: SessionService,
        workflows: GameWorkflowService,
        identities: IdentityProvider | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self._access = access
        self._campaigns = campaigns
        self._sessions = sessions
        self._workflows = workflows
        self._identities = identities
        self._rate_limiter = rate_limiter

    async def login_link(self, request: Request) -> ResponseTuple:
        headers = request.headers
        remote_host = request.remote_host
        url = urlsplit(request.target)
        token = parse_qs(url.query).get('token', [''])[0]
        if not token:
            return login_response()
        session_id = await self._access.consume_login(token)
        if session_id is None:
            return page_response(
                HTTPStatus.UNAUTHORIZED, 'Ссылка недействительна или уже использована.'
            )
        cookie_value = self._session_cookie(session_id, headers, remote_host)
        return HTTPStatus.SEE_OTHER, {'Location': '/campaigns', 'Set-Cookie': cookie_value}, b''

    async def register_page(self, request: Request) -> ResponseTuple:
        code = parse_qs(urlsplit(request.target).query).get('code', [''])[0]
        return login_response(registration=True, code=code)

    async def login(self, request: Request) -> ResponseTuple:
        if self._identities is None:
            return page_response(HTTPStatus.SERVICE_UNAVAILABLE, 'Локальный вход отключён.')
        limited = await self._rate_limit(
            f'login:{self._client_ip(request.headers, request.remote_host)}',
            limit=10,
            window=timedelta(minutes=10),
        )
        if limited is not None:
            return limited
        form = request.form
        user_id = await self._identities.authenticate(
            form.get('login', [''])[0], form.get('password', [''])[0]
        )
        if user_id is None:
            return login_response(error='Неверный логин или пароль.')
        return await self._local_session(user_id, request.headers, request.remote_host)

    async def register(self, request: Request) -> ResponseTuple:
        if self._identities is None:
            return page_response(HTTPStatus.SERVICE_UNAVAILABLE, 'Регистрация отключена.')
        limited = await self._rate_limit(
            f'register:{self._client_ip(request.headers, request.remote_host)}',
            limit=10,
            window=timedelta(minutes=10),
        )
        if limited is not None:
            return limited
        form = request.form
        try:
            user_id = await self._identities.register(
                form.get('code', [''])[0], form.get('login', [''])[0], form.get('password', [''])[0]
            )
        except InvalidRegistrationCode:
            return login_response(error='Код недействителен или просрочен.', registration=True)
        except LoginAlreadyExists:
            return login_response(error='Этот логин уже занят.', registration=True)
        except AuthenticationError:
            return login_response(
                error='Логин: 3–32 символа A–Z, цифры, точка, дефис или подчёркивание. Пароль — от 10 символов.',
                registration=True,
            )
        return await self._local_session(user_id, request.headers, request.remote_host)

    async def dashboard(self, request: Request) -> ResponseTuple:
        authenticated = await self._authenticated(request)
        if isinstance(authenticated, tuple):
            return authenticated
        identity, session_id = authenticated.identity, authenticated.session_id
        try:
            chat_id = int(
                parse_qs(urlsplit(request.target).query).get('campaign', [str(identity.chat_id)])[0]
            )
        except ValueError:
            return page_response(HTTPStatus.BAD_REQUEST, 'Некорректная кампания.')
        role = await self._campaigns.get_role(chat_id, identity.user_id)
        if role is None:
            return page_response(HTTPStatus.FORBIDDEN, 'Нет доступа к этой кампании.')
        return await self._dashboard(
            AdminIdentity(chat_id, identity.user_id, None), session_id, role
        )

    async def campaigns(self, request: Request) -> ResponseTuple:
        authenticated = await self._authenticated(request)
        if isinstance(authenticated, tuple):
            return authenticated
        identity, session_id = authenticated.identity, authenticated.session_id
        return campaigns_response(
            await self._campaigns.list_for_user(identity.user_id),
            identity.chat_id,
            await self._access.csrf_token(session_id) or '',
        )

    async def settings(self, request: Request) -> ResponseTuple:
        authenticated = await self._authenticated(request)
        if isinstance(authenticated, tuple):
            return authenticated
        identity, session_id = authenticated.identity, authenticated.session_id
        try:
            chat_id = int(
                parse_qs(urlsplit(request.target).query).get('campaign', [str(identity.chat_id)])[0]
            )
        except ValueError:
            return page_response(HTTPStatus.BAD_REQUEST, 'Некорректная кампания.')
        if not await self._campaigns.is_master(chat_id, identity.user_id):
            return page_response(HTTPStatus.FORBIDDEN, 'Настройки доступны только мастеру.')
        return await self._settings(AdminIdentity(chat_id, identity.user_id, None), session_id)

    async def sessions(self, request: Request) -> ResponseTuple:
        authenticated = await self._authenticated(request)
        if isinstance(authenticated, tuple):
            return authenticated
        identity, session_id = authenticated.identity, authenticated.session_id
        return sessions_response(
            await self._access.list_sessions(identity, session_id),
            await self._access.csrf_token(session_id) or '',
        )

    async def logout(self, request: Request) -> ResponseTuple:
        authenticated = await self._authenticated(request)
        if isinstance(authenticated, tuple):
            return authenticated
        session_id = authenticated.session_id
        await self._access.revoke(session_id)
        return (
            HTTPStatus.SEE_OTHER,
            {
                'Location': '/',
                'Set-Cookie': 'd20_admin=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0',
            },
            b'',
        )

    async def revoke_session(self, request: Request) -> ResponseTuple:
        authenticated = await self._authenticated(request)
        if isinstance(authenticated, tuple):
            return authenticated
        identity, session_id, form = (
            authenticated.identity,
            authenticated.session_id,
            authenticated.form,
        )
        revocation_id = form.get('revocation_id', [''])[0]
        current = any(
            session.current and session.revocation_id == revocation_id
            for session in await self._access.list_sessions(identity, session_id)
        )
        if not revocation_id or not await self._access.revoke_by_id(identity, revocation_id):
            return page_response(HTTPStatus.NOT_FOUND, 'Активная сессия не найдена.')
        headers = {'Location': '/sessions'}
        if current:
            headers = {
                'Location': '/',
                'Set-Cookie': 'd20_admin=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0',
            }
        return HTTPStatus.SEE_OTHER, headers, b''

    async def save_settings(self, request: Request) -> ResponseTuple:
        return await self._master_action(request, self._save_settings)

    async def schedule(self, request: Request) -> ResponseTuple:
        return await self._master_action(request, self._schedule)

    async def start_session(self, request: Request) -> ResponseTuple:
        return await self._master_action(request, self._start_session)

    async def stop_session(self, request: Request) -> ResponseTuple:
        return await self._master_action(request, self._stop_session, include_form=False)

    async def invite_player(self, request: Request) -> ResponseTuple:
        return await self._master_action(request, self._invite_player)

    async def rename_player(self, request: Request) -> ResponseTuple:
        return await self._master_action(request, self._rename_player)

    async def remove_player(self, request: Request) -> ResponseTuple:
        return await self._master_action(request, self._remove_player)

    async def transfer_master(self, request: Request) -> ResponseTuple:
        return await self._master_action(request, self._transfer_master)

    async def _authenticated(self, request: Request) -> _PageContext | ResponseTuple:
        session_id = self._cookie(request.headers, 'd20_admin')
        identity = await self._access.authenticate(session_id)
        if identity is None:
            if request.method == 'GET' and urlsplit(request.target).path == '/':
                return landing_response()
            return page_response(HTTPStatus.UNAUTHORIZED, 'Запросите новую ссылку командой /admin.')
        form = request.form if request.method == 'POST' else {}
        if request.method == 'POST':
            expected = await self._access.csrf_token(session_id)
            supplied = form.get('csrf_token', [''])[0]
            if expected is None or not secrets.compare_digest(expected, supplied):
                return page_response(
                    HTTPStatus.FORBIDDEN, 'Проверка безопасности формы не пройдена.'
                )
        return _PageContext(identity, session_id, form)

    async def _master_action(
        self, request: Request, action, *, include_form: bool = True
    ) -> ResponseTuple:
        authenticated = await self._authenticated(request)
        if isinstance(authenticated, tuple):
            return authenticated
        identity, _session_id, form = (
            authenticated.identity,
            authenticated.session_id,
            authenticated.form,
        )
        try:
            chat_id = int(form.get('chat_id', [str(identity.chat_id)])[0])
        except ValueError:
            return page_response(HTTPStatus.BAD_REQUEST, 'Некорректная кампания.')
        if not await self._campaigns.is_master(chat_id, identity.user_id):
            return page_response(HTTPStatus.FORBIDDEN, 'Недостаточно прав в этой кампании.')
        selected = AdminIdentity(chat_id, identity.user_id, None)
        return await action(selected, form) if include_form else await action(selected)

    async def _local_session(
        self, user_id: int, headers: Mapping[str, str], remote_host: str | None
    ) -> tuple[HTTPStatus, dict[str, str], bytes]:
        campaigns = await self._campaigns.list_for_user(user_id)
        initial_chat_id = campaigns[0].chat_id if campaigns else 0
        session_id = await self._access.create_session(
            AdminIdentity(initial_chat_id, user_id, None)
        )
        return (
            HTTPStatus.SEE_OTHER,
            {
                'Location': '/campaigns',
                'Set-Cookie': self._session_cookie(session_id, headers, remote_host),
            },
            b'',
        )

    def _session_cookie(
        self, session_id: str, headers: Mapping[str, str], remote_host: str | None
    ) -> str:
        return session_cookie(session_id, headers, remote_host)

    def _client_ip(self, headers: Mapping[str, str], remote_host: str | None) -> str:
        return client_ip(headers, remote_host)

    async def _rate_limit(
        self,
        key: str,
        *,
        limit: int,
        window: timedelta,
    ) -> tuple[HTTPStatus, dict[str, str], bytes] | None:
        if self._rate_limiter is None:
            return None
        result = await self._rate_limiter.hit(key, limit=limit, window=window)
        if result.allowed:
            return None
        retry_header = {'Retry-After': str(result.retry_after)}
        status, headers, body = page_response(
            HTTPStatus.TOO_MANY_REQUESTS,
            'Слишком много попыток. Повторите запрос позже.',
        )
        return status, {**headers, **retry_header}, body

    async def _dashboard(
        self, identity: AdminIdentity, session_id: str, role: str = 'master'
    ) -> tuple[HTTPStatus, dict[str, str], bytes]:
        session = await self._sessions.get_planned(identity.chat_id)
        active = await self._sessions.get_active(identity.chat_id)
        history = await self._sessions.get_history(identity.chat_id)
        roster = await self._campaigns.get_roster(identity.chat_id)
        default_url = await self._sessions.get_default_url(identity.chat_id) or getenv(
            'D20_BOT_FOUNDRY_URL', ''
        )
        timezone_name = await self._sessions.get_announcement_timezone(identity.chat_id)
        return dashboard_response(
            identity,
            session,
            active,
            roster,
            default_url,
            history,
            timezone_name,
            await self._access.csrf_token(session_id) or '',
            role,
        )

    async def _schedule(
        self, identity: AdminIdentity, form: Mapping[str, list[str]]
    ) -> tuple[HTTPStatus, dict[str, str], bytes]:
        try:
            local = datetime.fromisoformat(form['scheduled_at'][0])
            if local.tzinfo is None:
                raise ValueError
            scheduled_at = local.astimezone(UTC)
            foundry_url = form['foundry_url'][0]
        except KeyError, ValueError, IndexError:
            return page_response(HTTPStatus.BAD_REQUEST, 'Неверные дата или URL.')
        if not valid_url(foundry_url):
            return page_response(HTTPStatus.BAD_REQUEST, 'Неверный Foundry URL.')
        await self._workflows.schedule_and_notify(
            identity.chat_id, identity.chat_title, scheduled_at, foundry_url
        )
        return HTTPStatus.SEE_OTHER, {'Location': f'/?campaign={identity.chat_id}'}, b''

    async def _settings(
        self, identity: AdminIdentity, session_id: str
    ) -> tuple[HTTPStatus, dict[str, str], bytes]:
        roster = await self._campaigns.get_roster(identity.chat_id)
        title = (
            roster.campaign.title if roster and roster.campaign.title else identity.chat_title or ''
        )
        default_url = await self._sessions.get_default_url(identity.chat_id) or getenv(
            'D20_BOT_FOUNDRY_URL', ''
        )
        timezone_name = await self._sessions.get_announcement_timezone(identity.chat_id)
        return settings_response(
            title,
            default_url,
            timezone_name,
            await self._access.csrf_token(session_id) or '',
            identity.chat_id,
        )

    async def _save_settings(
        self, identity: AdminIdentity, form: Mapping[str, list[str]]
    ) -> tuple[HTTPStatus, dict[str, str], bytes]:
        try:
            title = form['title'][0].strip()
            foundry_url = form['foundry_url'][0].strip()
            timezone_name = form['announcement_timezone'][0]
        except KeyError, IndexError, ValueError:
            return page_response(HTTPStatus.BAD_REQUEST, 'Некорректные настройки кампании.')
        if (
            not title
            or len(title) > 100
            or not valid_url(foundry_url)
            or timezone_name not in ANNOUNCEMENT_TIMEZONES
        ):
            return page_response(HTTPStatus.BAD_REQUEST, 'Проверьте название и Foundry URL.')
        now = datetime.now(UTC)
        await self._campaigns.set_title(identity.chat_id, title)
        await self._sessions.set_default_url(identity.chat_id, foundry_url, now)
        await self._sessions.set_announcement_timezone(identity.chat_id, timezone_name, now)
        return (
            HTTPStatus.SEE_OTHER,
            {'Location': f'/settings?campaign={identity.chat_id}'},
            b'',
        )

    async def _start_session(
        self, identity: AdminIdentity, form: Mapping[str, list[str]]
    ) -> tuple[HTTPStatus, dict[str, str], bytes]:
        title = form.get('title', [''])[0].strip() or None
        if title is not None and len(title) > 100:
            return page_response(HTTPStatus.BAD_REQUEST, 'Название слишком длинное.')
        result = await self._workflows.start_and_notify(identity.chat_id, identity.user_id, title)
        if result.status is SessionStartStatus.FORBIDDEN:
            return page_response(HTTPStatus.FORBIDDEN, 'Доступ к кампании отозван.')
        if result.status is SessionStartStatus.ALREADY_ACTIVE:
            return page_response(HTTPStatus.CONFLICT, 'Сессия уже активна.')
        session = result.session
        assert session is not None
        return HTTPStatus.SEE_OTHER, {'Location': f'/?campaign={identity.chat_id}'}, b''

    async def _stop_session(
        self, identity: AdminIdentity
    ) -> tuple[HTTPStatus, dict[str, str], bytes]:
        result = await self._workflows.stop_and_notify(identity.chat_id, identity.user_id)
        if result.status is SessionStopStatus.FORBIDDEN:
            return page_response(HTTPStatus.FORBIDDEN, 'Доступ к кампании отозван.')
        if result.status is SessionStopStatus.NO_ACTIVE_SESSION:
            return page_response(HTTPStatus.CONFLICT, 'Активной сессии нет.')
        session = result.session
        assert session is not None
        return HTTPStatus.SEE_OTHER, {'Location': f'/?campaign={identity.chat_id}'}, b''

    async def _rename_player(
        self, identity: AdminIdentity, form: Mapping[str, list[str]]
    ) -> tuple[HTTPStatus, dict[str, str], bytes]:
        try:
            user_id = int(form['user_id'][0])
            name = form['name'][0].strip()
        except KeyError, ValueError, IndexError:
            return page_response(HTTPStatus.BAD_REQUEST, 'Некорректные данные игрока.')
        if not name or len(name) > 64:
            return page_response(
                HTTPStatus.BAD_REQUEST, 'Имя должно содержать от 1 до 64 символов.'
            )
        if await self._campaigns.rename_player(identity.chat_id, user_id, name) is None:
            return page_response(HTTPStatus.NOT_FOUND, 'Игрок не найден в этой кампании.')
        return HTTPStatus.SEE_OTHER, {'Location': f'/?campaign={identity.chat_id}'}, b''

    async def _invite_player(
        self, identity: AdminIdentity, form: Mapping[str, list[str]]
    ) -> tuple[HTTPStatus, dict[str, str], bytes]:
        try:
            user_id = int(form['user_id'][0])
            name = form['name'][0].strip()
        except KeyError, ValueError, IndexError:
            return page_response(HTTPStatus.BAD_REQUEST, 'Некорректные данные игрока.')
        if user_id <= 0 or not name or len(name) > 64:
            return page_response(
                HTTPStatus.BAD_REQUEST,
                'Укажите положительный Telegram ID и имя от 1 до 64 символов.',
            )
        if user_id == identity.user_id:
            return page_response(
                HTTPStatus.CONFLICT,
                'Нельзя пригласить самого себя как игрока.',
            )
        if await self._campaigns.get_role(identity.chat_id, user_id) is not None:
            return page_response(HTTPStatus.CONFLICT, 'Пользователь уже состоит в кампании.')
        await self._workflows.invite_player(identity.chat_id, identity.user_id, user_id, name)
        return HTTPStatus.SEE_OTHER, {'Location': f'/?campaign={identity.chat_id}'}, b''

    async def _remove_player(
        self, identity: AdminIdentity, form: Mapping[str, list[str]]
    ) -> tuple[HTTPStatus, dict[str, str], bytes]:
        try:
            user_id = int(form['user_id'][0])
        except KeyError, ValueError, IndexError:
            return page_response(HTTPStatus.BAD_REQUEST, 'Некорректные данные игрока.')
        if not await self._campaigns.remove_player(identity.chat_id, user_id):
            return page_response(HTTPStatus.NOT_FOUND, 'Игрок не найден в этой кампании.')
        return HTTPStatus.SEE_OTHER, {'Location': f'/?campaign={identity.chat_id}'}, b''

    async def _transfer_master(
        self, identity: AdminIdentity, form: Mapping[str, list[str]]
    ) -> tuple[HTTPStatus, dict[str, str], bytes]:
        try:
            user_id = int(form['user_id'][0])
        except KeyError, ValueError, IndexError:
            return page_response(HTTPStatus.BAD_REQUEST, 'Некорректный новый мастер.')
        if not await self._campaigns.transfer_master(identity.chat_id, identity.user_id, user_id):
            return page_response(
                HTTPStatus.CONFLICT,
                'Передать роль можно только зарегистрированному игроку этой кампании.',
            )
        return HTTPStatus.SEE_OTHER, {'Location': f'/?campaign={identity.chat_id}'}, b''

    @staticmethod
    def _cookie(headers: Mapping[str, str], name: str) -> str | None:
        return cookie(headers, name)
