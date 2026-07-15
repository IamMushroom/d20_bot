CREATE TABLE sessions_new (
    id           INTEGER PRIMARY KEY,
    campaign_id  INTEGER NOT NULL,
    number       INTEGER NOT NULL,
    title        TEXT,
    scheduled_at TEXT,
    started_at   TEXT,
    finished_at  TEXT,
    foundry_url  TEXT,
    message_id   INTEGER,
    updated_at   TEXT NOT NULL,
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
    UNIQUE (campaign_id, number),
    CHECK (finished_at IS NULL OR started_at IS NOT NULL)
);

INSERT INTO sessions_new (
    id, campaign_id, number, title, scheduled_at, started_at, finished_at,
    foundry_url, message_id, updated_at
)
SELECT
    id, campaign_id, number, title, NULL, started_at, finished_at,
    NULL, NULL, COALESCE(finished_at, started_at)
FROM sessions;

INSERT INTO campaigns (chat_id, title, created_at)
SELECT gs.chat_id, NULL, gs.updated_at
FROM game_schedules AS gs
WHERE NOT EXISTS (
    SELECT 1 FROM campaigns AS c WHERE c.chat_id = gs.chat_id
);

INSERT INTO sessions_new (
    campaign_id, number, title, scheduled_at, started_at, finished_at,
    foundry_url, message_id, updated_at
)
SELECT
    c.id,
    COALESCE((SELECT MAX(s.number) FROM sessions_new AS s WHERE s.campaign_id = c.id), 0) + 1,
    NULL,
    gs.scheduled_at,
    NULL,
    NULL,
    gs.foundry_url,
    gs.message_id,
    gs.updated_at
FROM game_schedules AS gs
JOIN campaigns AS c ON c.chat_id = gs.chat_id;

CREATE TABLE recap_entries_new (
    id            INTEGER PRIMARY KEY,
    session_id    INTEGER NOT NULL,
    character_id  INTEGER NOT NULL,
    text          TEXT NOT NULL,
    position      INTEGER NOT NULL,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions_new(id) ON DELETE CASCADE,
    FOREIGN KEY (character_id) REFERENCES characters(id),
    UNIQUE (session_id, position)
);

INSERT INTO recap_entries_new
SELECT * FROM recap_entries;

DROP TABLE recap_entries;
DROP TABLE sessions;
ALTER TABLE sessions_new RENAME TO sessions;
ALTER TABLE recap_entries_new RENAME TO recap_entries;

CREATE UNIQUE INDEX one_planned_session_per_campaign
    ON sessions(campaign_id)
    WHERE scheduled_at IS NOT NULL AND started_at IS NULL;

CREATE UNIQUE INDEX one_active_session_per_campaign
    ON sessions(campaign_id)
    WHERE started_at IS NOT NULL AND finished_at IS NULL;

DROP TABLE game_schedules;
