-- DocGen Supabase Schema
-- Run this in your Supabase SQL editor to set up the database.

create table if not exists config (
  key text primary key,
  value text
);

create table if not exists access_codes (
  id uuid primary key default gen_random_uuid(),
  code text not null unique,
  label text,
  is_admin boolean default false,
  created_at timestamptz default now()
);

create table if not exists templates (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  description text,
  docx_path text not null,
  fields jsonb not null default '[]',
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table if not exists tokens (
  id uuid primary key default gen_random_uuid(),
  template_id uuid references templates(id) on delete cascade,
  description text,
  status text default 'pending',
  created_at timestamptz default now()
);

create table if not exists submissions (
  id uuid primary key default gen_random_uuid(),
  token_id uuid references tokens(id) on delete cascade,
  values jsonb not null default '{}',
  submitted_at timestamptz default now()
);

-- Insert default config values (edit these after setup)
insert into config (key, value) values
  ('tenant_name', 'Mijn Organisatie'),
  ('primary_color', '#2563EB'),
  ('logo_url', '')
on conflict (key) do nothing;

-- Insert a default admin access code (change this immediately!)
insert into access_codes (code, label, is_admin) values
  ('admin123', 'Standaard admin', true)
on conflict (code) do nothing;

-- Storage bucket setup note:
-- Create a bucket named 'docgen-files' in Supabase Storage with public access disabled.
-- Add a policy allowing authenticated/service-role reads and writes.
