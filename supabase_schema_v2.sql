-- DocGen Supabase Schema v2 — Dossier migratie
-- Voer dit uit bovenop het bestaande schema (supabase_schema.sql).

-- Dossiers
create table if not exists dossiers (
  id uuid primary key default gen_random_uuid(),
  naam text not null,
  omschrijving text,
  status text default 'concept', -- concept, afgerond
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

-- Invullingen: koppeling dossier <-> template met opgeslagen waarden
create table if not exists invullingen (
  id uuid primary key default gen_random_uuid(),
  dossier_id uuid references dossiers(id) on delete cascade,
  template_id uuid references templates(id) on delete restrict,
  waarden jsonb not null default '{}',
  extern_toegang text default 'verborgen', -- verborgen, leesbaar, invulbaar
  updated_at timestamptz default now()
);

-- Dossier tokens (extern delen via magic link)
create table if not exists dossier_tokens (
  id uuid primary key default gen_random_uuid(),
  dossier_id uuid references dossiers(id) on delete cascade,
  omschrijving text,
  status text default 'actief', -- actief, ingetrokken
  created_at timestamptz default now()
);

-- GRANT rechten
GRANT ALL ON dossiers TO service_role;
GRANT ALL ON invullingen TO service_role;
GRANT ALL ON dossier_tokens TO service_role;
