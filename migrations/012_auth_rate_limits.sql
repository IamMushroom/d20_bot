CREATE TABLE auth_rate_limits (
    key_hash  TEXT PRIMARY KEY,
    attempts  INTEGER NOT NULL,
    reset_at  TEXT NOT NULL
);

CREATE INDEX auth_rate_limits_reset_at ON auth_rate_limits(reset_at);
