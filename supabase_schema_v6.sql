-- Migratie v6: extern_status per invulling (open / verzonden)
ALTER TABLE invullingen ADD COLUMN IF NOT EXISTS extern_status text NOT NULL DEFAULT 'open';
