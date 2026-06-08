-- Migratie v14: contract-looptijd + aflopen-signalen op dossiers.
--
-- Voegt ingangs-/einddatum, een gekoppelde accounthouder (gedenormaliseerd e-mail/naam
-- zodat signalen blijven werken als de Supabase-user-API later wegvalt) en een lijst
-- signaalmomenten ('x dagen vooraf') toe. Plus een logboektabel contract_signalen die
-- verstuurde signalen idempotent maakt. De cron-route zet status='verlopen' op de einddatum.

ALTER TABLE dossiers ADD COLUMN IF NOT EXISTS ingangsdatum date;
ALTER TABLE dossiers ADD COLUMN IF NOT EXISTS einddatum date;
ALTER TABLE dossiers ADD COLUMN IF NOT EXISTS accounthouder_id text;
ALTER TABLE dossiers ADD COLUMN IF NOT EXISTS accounthouder_email text;
ALTER TABLE dossiers ADD COLUMN IF NOT EXISTS accounthouder_naam text;
-- Lijst ints, bijv. [60, 30, 7]; default lege lijst zodat de cron veilig itereert.
ALTER TABLE dossiers ADD COLUMN IF NOT EXISTS signaal_dagen jsonb NOT NULL DEFAULT '[]';

-- Logboek van verstuurde contract-signalen (idempotentie per moment).
CREATE TABLE IF NOT EXISTS contract_signalen (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  dossier_id uuid NOT NULL REFERENCES dossiers(id) ON DELETE CASCADE,
  soort text NOT NULL,            -- 'vooraf' of 'verlopen'
  dagen_vooraf integer,          -- gevuld bij 'vooraf', NULL bij 'verlopen'
  verstuurd_op timestamptz NOT NULL DEFAULT now(),
  verstuurd_naar text
);

-- Eén signaalmoment kan nooit twee keer mailen. COALESCE omdat NULL in Postgres niet
-- uniek-conflicteert; 'verlopen' krijgt zo een vaste -1 in de unieke sleutel.
CREATE UNIQUE INDEX IF NOT EXISTS uq_contract_signaal
  ON contract_signalen (dossier_id, soort, COALESCE(dagen_vooraf, -1));

-- RLS: alleen service_role (conform v10/v12). De Flask-backend benadert alles via die key.
ALTER TABLE contract_signalen ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all" ON contract_signalen;
CREATE POLICY "service_role_all" ON contract_signalen
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');
