import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from auth import (
    AuthenticationError,
    InvalidRegistrationCode,
    LoginAlreadyExists,
    SQLiteLocalIdentityProvider,
    UnknownTelegramUser,
)
from database import SQLiteDatabase, apply_migrations

MIGRATIONS = Path(__file__).resolve().parents[2] / 'migrations'


def test_local_registration_and_authentication(tmp_path):
    async def scenario():
        database = await SQLiteDatabase.connect(str(tmp_path / 'auth.sqlite3'))
        await apply_migrations(database, MIGRATIONS)
        await database.execute(
            "INSERT INTO users (telegram_user_id, created_at) VALUES (7, '2026-01-01T00:00:00+00:00')"
        )
        auth = SQLiteLocalIdentityProvider(database)
        code = await auth.issue_registration_code(7)
        user_id = await auth.register(code.lower(), 'Mushroom', 'correct horse battery')
        authenticated = await auth.authenticate('mUsHrOoM', 'correct horse battery')
        rejected = await auth.authenticate('Mushroom', 'wrong password')
        stored = await database.fetch_one('SELECT * FROM local_accounts')
        await database.close()
        return code, user_id, authenticated, rejected, stored

    code, user_id, authenticated, rejected, stored = asyncio.run(scenario())
    assert len(code) == 14
    assert user_id == authenticated == 7
    assert rejected is None
    assert stored is not None
    assert stored['password_hash'] != 'correct horse battery'


def test_registration_codes_are_one_time_and_accounts_are_unique(tmp_path):
    async def scenario():
        database = await SQLiteDatabase.connect(str(tmp_path / 'auth.sqlite3'))
        await apply_migrations(database, MIGRATIONS)
        for user_id in (7, 8):
            await database.execute(
                "INSERT INTO users (telegram_user_id, created_at) VALUES (?, '2026-01-01T00:00:00+00:00')",
                (user_id,),
            )
        auth = SQLiteLocalIdentityProvider(database)
        first = await auth.issue_registration_code(7)
        await auth.register(first, 'player', 'long-enough-password')
        with pytest.raises(InvalidRegistrationCode):
            await auth.register(first, 'another', 'long-enough-password')
        second = await auth.issue_registration_code(8)
        with pytest.raises(LoginAlreadyExists):
            await auth.register(second, 'PLAYER', 'long-enough-password')
        await database.close()

    asyncio.run(scenario())


def test_registration_requires_known_telegram_user(tmp_path):
    async def scenario():
        database = await SQLiteDatabase.connect(str(tmp_path / 'auth.sqlite3'))
        await apply_migrations(database, MIGRATIONS)
        auth = SQLiteLocalIdentityProvider(database)
        with pytest.raises(UnknownTelegramUser):
            await auth.issue_registration_code(404)
        await database.close()

    asyncio.run(scenario())


def test_expired_registration_code_is_rejected(tmp_path):
    async def scenario():
        database = await SQLiteDatabase.connect(str(tmp_path / 'auth.sqlite3'))
        await apply_migrations(database, MIGRATIONS)
        await database.execute(
            "INSERT INTO users (telegram_user_id, created_at) VALUES (7, '2026-01-01T00:00:00+00:00')"
        )
        auth = SQLiteLocalIdentityProvider(database)
        code = await auth.issue_registration_code(7)
        await database.execute(
            'UPDATE local_registration_codes SET expires_at = ?',
            ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(),),
        )
        with pytest.raises(InvalidRegistrationCode):
            await auth.register(code, 'player', 'long-enough-password')
        await database.close()

    asyncio.run(scenario())


def test_local_auth_rejects_invalid_credentials_and_allows_password_reset(tmp_path):
    async def scenario():
        database = await SQLiteDatabase.connect(str(tmp_path / 'auth.sqlite3'))
        await apply_migrations(database, MIGRATIONS)
        await database.execute(
            "INSERT INTO users (telegram_user_id, created_at) VALUES (7, '2026-01-01T00:00:00+00:00')"
        )
        auth = SQLiteLocalIdentityProvider(database)
        code = await auth.issue_registration_code(7)
        with pytest.raises(AuthenticationError):
            await auth.register(code, 'bad login', 'long-enough-password')
        code = await auth.issue_registration_code(7)
        with pytest.raises(AuthenticationError):
            await auth.register(code, 'valid', 'short')
        code = await auth.issue_registration_code(7)
        await auth.register(code, 'first-login', 'first-long-password')
        reset = await auth.issue_registration_code(7)
        await auth.register(reset, 'second-login', 'second-long-password')
        missing = await auth.authenticate('missing', 'any-long-password')
        too_long = await auth.authenticate('second-login', 'x' * 257)
        old = await auth.authenticate('first-login', 'first-long-password')
        current = await auth.authenticate('second-login', 'second-long-password')
        await database.close()
        return missing, too_long, old, current

    assert asyncio.run(scenario()) == (None, None, None, 7)
