# Oplevering: contract-looptijd + dossier dupliceren (Python/Render)

Feature van 8 jun 2026. Code is gepusht; onderstaande stappen zijn nodig om het
op productie (Render + Supabase) te activeren.

## 1. Database-migratie (handmatig)
Voer `supabase_schema_v14.sql` uit in de **Supabase SQL-editor** (er is geen runner).
Dit voegt de contract-velden op `dossiers` toe + de tabel `contract_signalen`.

## 2. Env-vars op Render
Zet (Render → service `docgen` → Environment):
- `CRON_SECRET_KEY` — lang willekeurig geheim (beveiligt de cron-route).
- `SUPABASE_SERVICE_KEY` — moet al gezet zijn (cron + storage gebruiken service_role).
- Optioneel voor échte e-mail (anders wordt alleen gelogd):
  `SMTP_HOST`, `SMTP_PORT` (587), `SMTP_USER`, `SMTP_PASS`, `MAIL_FROM`.

## 3. Crontab (thuisserver)
Voeg een dagelijkse aanroep toe (bv. 07:00):
```
0 7 * * * curl -fsS "https://docgen-qipm.onrender.com/cron/contract-signalen?key=<CRON_SECRET_KEY>" >/dev/null
```

## 4. Verifiëren
- Open een dossier → vul ingangs-/einddatum, accounthouder en signaalmomenten in → Opslaan.
- "Contracten" in de nav toont aflopende/verlopen dossiers (met badge).
- "Dupliceren" op de dossierpagina maakt een concept-kopie met alle ingevulde gegevens.
- Handmatige cron-test: `curl ".../cron/contract-signalen?key=..."` → JSON met aantallen;
  tweede aanroep dezelfde dag = 0 (idempotent).

## Tests
`python3 tests/test_contract.py` en `python3 tests/test_docx_render.py` (beide groen).
