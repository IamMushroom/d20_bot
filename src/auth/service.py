from typing import Protocol


class AuthenticationError(ValueError):
    pass


class UnknownTelegramUser(AuthenticationError):
    pass


class InvalidRegistrationCode(AuthenticationError):
    pass


class LoginAlreadyExists(AuthenticationError):
    pass


class IdentityProvider(Protocol):
    async def issue_registration_code(self, telegram_user_id: int) -> str: ...

    async def register(self, code: str, login: str, password: str) -> int: ...

    async def authenticate(self, login: str, password: str) -> int | None: ...
