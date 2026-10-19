CREATE TABLE IF NOT EXISTS videos (
    hash TEXT PRIMARY KEY,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,     
    vectors JSONB NOT NULL DEFAULT '{}'::jsonb,
    indexed BOOLEAN NOT NULL DEFAULT FALSE,
    processing_now BOOLEAN NOT NULL DEFAULT FALSE
);
