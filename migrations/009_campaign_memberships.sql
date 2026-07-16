CREATE TABLE users (
    id                INTEGER PRIMARY KEY,
    telegram_user_id  INTEGER NOT NULL UNIQUE,
    created_at        TEXT NOT NULL
);

CREATE TABLE campaign_memberships (
    campaign_id  INTEGER NOT NULL,
    user_id      INTEGER NOT NULL,
    role         TEXT NOT NULL CHECK (role IN ('player', 'master')),
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    PRIMARY KEY (campaign_id, user_id),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

INSERT OR IGNORE INTO users (telegram_user_id, created_at)
SELECT master_user_id, created_at FROM campaigns WHERE master_user_id IS NOT NULL
UNION
SELECT telegram_user_id, created_at FROM characters;

INSERT OR IGNORE INTO campaign_memberships (campaign_id, user_id, role, created_at, updated_at)
SELECT c.campaign_id, u.id, 'player', c.created_at, c.updated_at
FROM characters AS c
JOIN users AS u ON u.telegram_user_id = c.telegram_user_id;

INSERT INTO campaign_memberships (campaign_id, user_id, role, created_at, updated_at)
SELECT c.id, u.id, 'master', c.created_at, c.created_at
FROM campaigns AS c
JOIN users AS u ON u.telegram_user_id = c.master_user_id
ON CONFLICT(campaign_id, user_id) DO UPDATE SET role = 'master';

CREATE INDEX campaign_memberships_user_id ON campaign_memberships(user_id);
