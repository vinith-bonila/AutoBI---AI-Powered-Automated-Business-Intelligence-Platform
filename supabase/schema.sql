-- AutoBI — Supabase schema
-- Run this in the Supabase SQL editor (or `supabase db push`) once, then set
-- STORAGE_BACKEND=supabase + SUPABASE_URL + SUPABASE_SERVICE_KEY on the backend.

-- ---------------------------------------------------------------------------
-- 1. Storage bucket for the raw CSV and cleaned Parquet files.
-- ---------------------------------------------------------------------------
insert into storage.buckets (id, name, public)
values ('autobi', 'autobi', false)
on conflict (id) do nothing;

-- ---------------------------------------------------------------------------
-- 2. Datasets: metadata + analysis artifacts as jsonb.
--    The backend reaches these through PostgREST with the service-role key.
-- ---------------------------------------------------------------------------
create table if not exists public.datasets (
    id          text primary key,
    filename    text not null,
    status      text not null default 'pending',
    meta        jsonb not null default '{}'::jsonb,
    profile     jsonb,
    quality     jsonb,
    analysis    jsonb,
    dashboard   jsonb,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);

create index if not exists datasets_created_at_idx on public.datasets (created_at desc);

-- ---------------------------------------------------------------------------
-- 3. Saved dashboards (save / load / share the customized configuration).
-- ---------------------------------------------------------------------------
create table if not exists public.saved_dashboards (
    id          text primary key,
    dataset_id  text references public.datasets (id) on delete cascade,
    name        text not null,
    config      jsonb not null default '{}'::jsonb,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);

create index if not exists saved_dashboards_dataset_idx
    on public.saved_dashboards (dataset_id);

-- ---------------------------------------------------------------------------
-- 4. Lock the tables down. RLS is ON with NO policies, so the anon/public key
--    cannot read or write them. Only the service-role key (used server-side by
--    the AutoBI backend) bypasses RLS. Storage stays private for the same
--    reason — objects are only reached with the service key.
-- ---------------------------------------------------------------------------
alter table public.datasets enable row level security;
alter table public.saved_dashboards enable row level security;

-- (Intentionally no policies: all access is server-side via the service role.)
