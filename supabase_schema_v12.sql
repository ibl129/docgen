-- v12: RLS inschakelen op de laatste twee publiek-toegankelijke tabellen.
-- Supabase advisor meldde 'rls_disabled_in_public' voor financieringsvormen en
-- inzendingen_gelezen (stonden in v10 bewust op DISABLE als "referentiedata", maar de
-- app benadert ze uitsluitend via de service_role-key — dus geen publieke toegang nodig).
-- Zelfde policy als alle andere tabellen: alleen service_role.

-- financieringsvormen
ALTER TABLE financieringsvormen ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all" ON financieringsvormen;
CREATE POLICY "service_role_all" ON financieringsvormen
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

-- inzendingen_gelezen (bevat gebruikersgedrag — hoort zeker niet publiek)
ALTER TABLE inzendingen_gelezen ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all" ON inzendingen_gelezen;
CREATE POLICY "service_role_all" ON inzendingen_gelezen
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');
