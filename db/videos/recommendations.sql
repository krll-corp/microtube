BEGIN;

CREATE TABLE IF NOT EXISTS watch_history (
    login_hash TEXT NOT NULL,
    video_id TEXT NOT NULL REFERENCES videos(hash) ON DELETE CASCADE,
    first_watched_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    watched_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (login_hash, video_id)
);

CREATE TABLE IF NOT EXISTS user_feed (
    login_hash TEXT NOT NULL,
    version BIGINT GENERATED ALWAYS AS IDENTITY,
    watched_count BIGINT NOT NULL,
    profile_ids TEXT[] NOT NULL,
    video_ids TEXT[] NOT NULL,
    PRIMARY KEY (login_hash, version)
);

COMMIT;
