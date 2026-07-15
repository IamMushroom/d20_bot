CREATE TABLE game_configs_new (
    chat_id       INTEGER PRIMARY KEY,
    foundry_url   TEXT,
    web_base_url  TEXT,
    updated_at    TEXT NOT NULL
);

INSERT INTO game_configs_new (chat_id, foundry_url, updated_at)
SELECT chat_id, foundry_url, updated_at FROM game_configs;

DROP TABLE game_configs;
ALTER TABLE game_configs_new RENAME TO game_configs;
