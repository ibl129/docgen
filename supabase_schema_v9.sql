-- Migratie v9: dossier_types tabel voor beheerbare soort-opties met tooltip-beschrijving
CREATE TABLE IF NOT EXISTS dossier_types (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  naam text NOT NULL,
  beschrijving text,
  created_at timestamptz DEFAULT now()
);
