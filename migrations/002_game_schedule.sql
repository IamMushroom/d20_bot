CREATE TABLE game_schedules (
    chat_id       INTEGER PRIMARY KEY,
    scheduled_at  TEXT NOT NULL,
    foundry_url   TEXT NOT NULL,
    message_id    INTEGER,
    updated_at    TEXT NOT NULL
);
