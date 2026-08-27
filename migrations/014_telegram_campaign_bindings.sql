CREATE TABLE telegram_campaign_bindings (
    campaign_id INTEGER NOT NULL UNIQUE,
    chat_id     INTEGER NOT NULL UNIQUE,
    created_at  TEXT NOT NULL,
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
);

INSERT INTO telegram_campaign_bindings (campaign_id, chat_id, created_at)
SELECT id, chat_id, created_at
FROM campaigns;
