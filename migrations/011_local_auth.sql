CREATE TABLE local_accounts (
    telegram_user_id INTEGER PRIMARY KEY,
    login             TEXT NOT NULL,
    login_key         TEXT NOT NULL UNIQUE,
    password_salt     BLOB NOT NULL,
    password_hash     BLOB NOT NULL,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    FOREIGN KEY (telegram_user_id) REFERENCES users(telegram_user_id) ON DELETE CASCADE
);

CREATE TABLE local_registration_codes (
    code_hash         TEXT PRIMARY KEY,
    telegram_user_id  INTEGER NOT NULL,
    expires_at        TEXT NOT NULL,
    FOREIGN KEY (telegram_user_id) REFERENCES users(telegram_user_id) ON DELETE CASCADE
);

CREATE INDEX local_registration_codes_expires_at
    ON local_registration_codes(expires_at);
