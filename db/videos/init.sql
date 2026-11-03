CREATE TABLE IF NOT EXISTS videos (
    hash TEXT PRIMARY KEY,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,     
    vectors JSONB NOT NULL DEFAULT '{}'::jsonb,
    indexed BOOLEAN NOT NULL DEFAULT FALSE,
    processing_now BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS tags (
    tag_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tag TEXT NOT NULL UNIQUE CHECK (btrim(tag) <> ''),
    vector vector(768) CHECK (vector_norm(vector) > 0)
);

CREATE INDEX IF NOT EXISTS tags_vector_cosine_idx
    ON tags USING hnsw (vector vector_cosine_ops);