-- Migratie v4: financieringsvormen beheer tabel
CREATE TABLE IF NOT EXISTS financieringsvormen (
    id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    naam text NOT NULL,
    created_at timestamptz DEFAULT now()
);

GRANT ALL ON financieringsvormen TO authenticated, service_role;
ALTER TABLE financieringsvormen DISABLE ROW LEVEL SECURITY;

-- Vul standaard vormen in als de tabel leeg is
INSERT INTO financieringsvormen (naam)
SELECT naam FROM (VALUES ('Zvw'), ('Wlz'), ('Wmo'), ('Jeugdwet'), ('Overig')) AS t(naam)
WHERE NOT EXISTS (SELECT 1 FROM financieringsvormen);
