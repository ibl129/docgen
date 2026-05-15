-- Migratie v7: user_preferences tabel voor weergavevoorkeuren per gebruiker
CREATE TABLE IF NOT EXISTS user_preferences (
    user_id text PRIMARY KEY,
    preferences jsonb NOT NULL DEFAULT '{}'
);
