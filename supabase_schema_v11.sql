-- v11: gedeelde_waarden op dossier-niveau voor dossier-scope placeholders
ALTER TABLE dossiers ADD COLUMN IF NOT EXISTS gedeelde_waarden jsonb NOT NULL DEFAULT '{}';
