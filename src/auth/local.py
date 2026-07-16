import asyncio
import hashlib
import hmac
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import cast

from auth.service import (
    AuthenticationError,
    InvalidRegistrationCode,
    LoginAlreadyExists,
    UnknownTelegramUser,
)
from database import Database

LOGIN_PATTERN = re.compile(r'[A-Za-z0-9_.-]{3,32}\Z')
CODE_ALPHABET = '23456789ABCDEFGHJKLMNPQRSTUVWXYZ'


def _code_hash(code: str) -> str:
    normalized = code.replace('-', '').replace(' ', '').upper()
    return hashlib.sha256(normalized.encode('ascii', errors='ignore')).hexdigest()


def _password_hash(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)


class SQLiteLocalIdentityProvider:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def issue_registration_code(self, telegram_user_id: int) -> str:
        user = await self._database.fetch_one(
            'SELECT 1 FROM users WHERE telegram_user_id = ?', (telegram_user_id,)
        )
        if user is None:
            raise UnknownTelegramUser('Telegram user is not registered in any campaign')
        now = datetime.now(UTC)
        await self._database.execute(
            'DELETE FROM local_registration_codes WHERE telegram_user_id = ? OR expires_at <= ?',
            (telegram_user_id, now.isoformat()),
        )
        raw = ''.join(secrets.choice(CODE_ALPHABET) for _ in range(12))
        await self._database.execute(
            'INSERT INTO local_registration_codes (code_hash, telegram_user_id, expires_at) VALUES (?, ?, ?)',
            (_code_hash(raw), telegram_user_id, (now + timedelta(minutes=15)).isoformat()),
        )
        return '-'.join(raw[index : index + 4] for index in range(0, 12, 4))

    async def register(self, code: str, login: str, password: str) -> int:
        if not LOGIN_PATTERN.fullmatch(login) or not 10 <= len(password) <= 256:
            raise AuthenticationError('Invalid login or password')
        now = datetime.now(UTC)
        row = await self._database.fetch_one(
            'DELETE FROM local_registration_codes WHERE code_hash = ? AND expires_at > ? RETURNING telegram_user_id',
            (_code_hash(code), now.isoformat()),
        )
        if row is None:
            raise InvalidRegistrationCode('Registration code is invalid or expired')
        telegram_user_id = cast(int, row['telegram_user_id'])
        salt = secrets.token_bytes(16)
        password_hash = await asyncio.to_thread(_password_hash, password, salt)
        try:
            await self._database.execute(
                '''INSERT INTO local_accounts (
                    telegram_user_id, login, login_key, password_salt, password_hash,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(telegram_user_id) DO UPDATE SET
                    login = excluded.login, login_key = excluded.login_key,
                    password_salt = excluded.password_salt,
                    password_hash = excluded.password_hash, updated_at = excluded.updated_at''',
                (
                    telegram_user_id,
                    login,
                    login.casefold(),
                    salt,
                    password_hash,
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
        except Exception as error:
            if 'UNIQUE constraint failed: local_accounts.login_key' in str(error):
                raise LoginAlreadyExists('Login is already used') from error
            raise
        return telegram_user_id

    async def authenticate(self, login: str, password: str) -> int | None:
        if len(password) > 256:
            return None
        row = await self._database.fetch_one(
            'SELECT telegram_user_id, password_salt, password_hash FROM local_accounts WHERE login_key = ?',
            (login.casefold(),),
        )
        if row is None:
            return None
        salt = cast(bytes, row['password_salt'])
        expected = cast(bytes, row['password_hash'])
        actual = await asyncio.to_thread(_password_hash, password, salt)
        return cast(int, row['telegram_user_id']) if hmac.compare_digest(actual, expected) else None


__all__ = ['SQLiteLocalIdentityProvider']
