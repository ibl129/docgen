-- Migratie v5: ongelezen inzendingen per gebruiker bijhouden
CREATE TABLE IF NOT EXISTS inzendingen_gelezen (
    user_id   uuid PRIMARY KEY,
    gezien_op timestamptz NOT NULL DEFAULT now()
);

GRANT ALL ON inzendingen_gelezen TO authenticated, service_role;
ALTER TABLE inzendingen_gelezen DISABLE ROW LEVEL SECURITY;
