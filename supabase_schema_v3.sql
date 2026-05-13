-- Migratie v3: jaar en financieringsvorm aan dossiers
ALTER TABLE dossiers ADD COLUMN IF NOT EXISTS jaar integer;
ALTER TABLE dossiers ADD COLUMN IF NOT EXISTS financieringsvorm text;
