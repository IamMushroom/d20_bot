CREATE TABLE web_login_tokens (
    token_hash       TEXT PRIMARY KEY,
    telegram_user_id INTEGER NOT NULL,
    initial_chat_id  INTEGER NOT NULL,
    chat_title       TEXT,
    expires_at       TEXT NOT NULL
);

CREATE TABLE web_sessions (
    session_hash     TEXT PRIMARY KEY,
    telegram_user_id INTEGER NOT NULL,
    initial_chat_id  INTEGER NOT NULL,
    chat_title       TEXT,
    csrf_token       TEXT NOT NULL,
    revocation_id    TEXT NOT NULL UNIQUE,
    created_at       TEXT NOT NULL,
    expires_at       TEXT NOT NULL
);

CREATE INDEX web_login_tokens_expires_at ON web_login_tokens(expires_at);
CREATE INDEX web_sessions_expires_at ON web_sessions(expires_at);
CREATE INDEX web_sessions_user_id ON web_sessions(telegram_user_id);
