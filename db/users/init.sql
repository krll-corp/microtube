CREATE TABLE IF NOT EXISTS users (
    login_hash TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL
);
