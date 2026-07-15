CREATE TABLE campaigns (
    id          INTEGER PRIMARY KEY,
    chat_id     INTEGER NOT NULL UNIQUE,
    title       TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE characters (
    id                INTEGER PRIMARY KEY,
    campaign_id       INTEGER NOT NULL,
    telegram_user_id  INTEGER NOT NULL,
    name              TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
    UNIQUE (campaign_id, telegram_user_id)
);

CREATE TABLE sessions (
    id           INTEGER PRIMARY KEY,
    campaign_id  INTEGER NOT NULL,
    number       INTEGER NOT NULL,
    title        TEXT,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
    UNIQUE (campaign_id, number)
);

CREATE UNIQUE INDEX one_active_session_per_campaign
    ON sessions(campaign_id)
    WHERE finished_at IS NULL;

CREATE TABLE recap_entries (
    id            INTEGER PRIMARY KEY,
    session_id    INTEGER NOT NULL,
    character_id  INTEGER NOT NULL,
    text          TEXT NOT NULL,
    position      INTEGER NOT NULL,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (character_id) REFERENCES characters(id),
    UNIQUE (session_id, position)
);
