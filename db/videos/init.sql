CREATE TABLE IF NOT EXISTS videos (
    hash TEXT PRIMARY KEY,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);
