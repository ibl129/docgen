-- v10: RLS policies — alleen service_role heeft toegang tot alle tabellen.
-- De Flask-backend gebruikt uitsluitend de service_role key (supabase_admin),
-- dus geen enkele tabel hoeft via de anonieme key bereikbaar te zijn.

-- config
ALTER TABLE config ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all" ON config;
CREATE POLICY "service_role_all" ON config
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

-- templates
ALTER TABLE templates ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all" ON templates;
CREATE POLICY "service_role_all" ON templates
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

-- tokens
ALTER TABLE tokens ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all" ON tokens;
CREATE POLICY "service_role_all" ON tokens
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

-- submissions
ALTER TABLE submissions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all" ON submissions;
CREATE POLICY "service_role_all" ON submissions
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

-- dossiers
ALTER TABLE dossiers ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all" ON dossiers;
CREATE POLICY "service_role_all" ON dossiers
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

-- invullingen
ALTER TABLE invullingen ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all" ON invullingen;
CREATE POLICY "service_role_all" ON invullingen
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

-- dossier_tokens
ALTER TABLE dossier_tokens ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all" ON dossier_tokens;
CREATE POLICY "service_role_all" ON dossier_tokens
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

-- dossier_types
ALTER TABLE dossier_types ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all" ON dossier_types;
CREATE POLICY "service_role_all" ON dossier_types
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

-- user_preferences
ALTER TABLE user_preferences ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all" ON user_preferences;
CREATE POLICY "service_role_all" ON user_preferences
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

-- access_codes (legacy, voor de zekerheid ook dichtgooien)
ALTER TABLE access_codes ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all" ON access_codes;
CREATE POLICY "service_role_all" ON access_codes
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

-- financieringsvormen en inzendingen_gelezen stonden al op DISABLE ROW LEVEL SECURITY
-- (openbare referentiedata) — die laten we met rust.
