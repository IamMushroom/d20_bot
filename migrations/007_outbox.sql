CREATE TABLE outbox_events (
    id           INTEGER PRIMARY KEY,
    event_type   TEXT NOT NULL,
    payload      TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    delivered_at TEXT
);

CREATE INDEX pending_outbox_events
    ON outbox_events(id)
    WHERE delivered_at IS NULL;
