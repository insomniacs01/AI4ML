create extension if not exists pgcrypto;

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = timezone('utc', now());
  return new;
end;
$$;

create table if not exists public.profiles (
  user_id uuid primary key references auth.users(id) on delete cascade,
  email text not null unique,
  display_name text,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

drop trigger if exists profiles_set_updated_at on public.profiles;
create trigger profiles_set_updated_at
before update on public.profiles
for each row
execute function public.set_updated_at();

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (user_id, email, display_name)
  values (
    new.id,
    coalesce(new.email, ''),
    nullif(trim(coalesce(new.raw_user_meta_data ->> 'display_name', '')), '')
  )
  on conflict (user_id) do update
    set email = excluded.email,
        display_name = coalesce(excluded.display_name, public.profiles.display_name),
        updated_at = timezone('utc', now());
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
after insert on auth.users
for each row
execute function public.handle_new_user();

insert into public.profiles (user_id, email, display_name)
select
  u.id,
  coalesce(u.email, ''),
  nullif(trim(coalesce(u.raw_user_meta_data ->> 'display_name', '')), '')
from auth.users as u
on conflict (user_id) do update
  set email = excluded.email,
      display_name = coalesce(excluded.display_name, public.profiles.display_name),
      updated_at = timezone('utc', now());

create table if not exists public.teams (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  invite_code text not null unique,
  description text,
  status text not null default 'active' check (status in ('active', 'disabled', 'archived')),
  created_by uuid not null references public.profiles(user_id) on delete restrict,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

create or replace function public.generate_team_invite_code()
returns text
language plpgsql
as $$
declare
  candidate text;
begin
  loop
    candidate := upper(substr(replace(gen_random_uuid()::text, '-', ''), 1, 8));
    exit when not exists (select 1 from public.teams where invite_code = candidate);
  end loop;
  return candidate;
end;
$$;

alter table public.teams
alter column invite_code set default public.generate_team_invite_code();
alter table public.teams
  add column if not exists description text;
alter table public.teams
  add column if not exists status text not null default 'active';

do $$
begin
  alter table public.teams
    drop constraint if exists teams_status_check;
  alter table public.teams
    add constraint teams_status_check
    check (status in ('active', 'disabled', 'archived'));
end;
$$;

drop trigger if exists teams_set_updated_at on public.teams;
create trigger teams_set_updated_at
before update on public.teams
for each row
execute function public.set_updated_at();

create table if not exists public.team_members (
  team_id uuid not null references public.teams(id) on delete cascade,
  user_id uuid not null references public.profiles(user_id) on delete cascade,
  role text not null check (role in ('team_owner', 'admin', 'business_user', 'developer_user', 'member')),
  member_status text not null default 'active' check (member_status in ('invited', 'active', 'frozen', 'removed')),
  invited_by uuid references public.profiles(user_id) on delete set null,
  joined_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now()),
  primary key (team_id, user_id)
);

alter table public.team_members
  add column if not exists member_status text not null default 'active';
alter table public.team_members
  add column if not exists invited_by uuid references public.profiles(user_id) on delete set null;
alter table public.team_members
  add column if not exists updated_at timestamptz not null default timezone('utc', now());

drop trigger if exists team_members_set_updated_at on public.team_members;
create trigger team_members_set_updated_at
before update on public.team_members
for each row
execute function public.set_updated_at();

do $$
declare
  constraint_name text;
begin
  for constraint_name in
    select conname
    from pg_constraint
    where conrelid = 'public.team_members'::regclass
      and contype = 'c'
  loop
    execute format('alter table public.team_members drop constraint if exists %I', constraint_name);
  end loop;
end;
$$;

alter table public.team_members
  add constraint team_members_role_check
  check (role in ('team_owner', 'admin', 'business_user', 'developer_user', 'member'));
alter table public.team_members
  add constraint team_members_status_check
  check (member_status in ('invited', 'active', 'frozen', 'removed'));

create table if not exists public.ai_connectors (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references public.teams(id) on delete cascade,
  created_by uuid not null references public.profiles(user_id) on delete restrict,
  display_name text not null,
  provider_type text not null default 'openai-compatible',
  endpoint_url text,
  base_url text not null,
  model_name text not null,
  wire_api text not null check (wire_api in ('chat_completions', 'responses')),
  api_key text not null,
  is_active boolean not null default false,
  last_tested_at timestamptz,
  last_test_status text not null default 'untested' check (last_test_status in ('untested', 'passed', 'failed')),
  last_test_detail text,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

create unique index if not exists ai_connectors_one_active_per_team_idx
on public.ai_connectors (team_id)
where is_active;

drop trigger if exists ai_connectors_set_updated_at on public.ai_connectors;
create trigger ai_connectors_set_updated_at
before update on public.ai_connectors
for each row
execute function public.set_updated_at();

create table if not exists public.ai_tasks (
  id text primary key default substr(replace(gen_random_uuid()::text, '-', ''), 1, 8),
  team_id uuid not null references public.teams(id) on delete cascade,
  created_by uuid not null references public.profiles(user_id) on delete restrict,
  creator_user_id uuid references public.profiles(user_id) on delete set null,
  workflow_id text,
  name text not null,
  description text not null,
  label_column text,
  problem_type text check (problem_type is null or problem_type in ('classification', 'regression')),
  status text not null default 'draft' check (status in ('draft', 'uploaded', 'planning', 'running', 'paused_for_review', 'waiting_human', 'completed', 'failed', 'cancelled', 'published')),
  dataset_filename text,
  dataset_path text,
  dataset_profile jsonb,
  notes text,
  analysis_token_usage jsonb,
  last_run jsonb,
  last_run_attempt jsonb,
  executor_type text not null default 'codex' check (executor_type in ('codex')),
  codex_workspace_path text,
  codex_session_id text,
  codex_thread_id text,
  codex_status text,
  codex_started_at timestamptz,
  codex_finished_at timestamptz,
  structured_requirements jsonb,
  routing_policy_id text,
  routing_source text,
  stage_routing jsonb not null default '[]'::jsonb,
  interaction_policies jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

alter table public.ai_tasks
  add column if not exists creator_user_id uuid references public.profiles(user_id) on delete set null;
alter table public.ai_tasks
  add column if not exists workflow_id text;
alter table public.ai_tasks
  add column if not exists stage_routing jsonb not null default '[]'::jsonb;
alter table public.ai_tasks
  add column if not exists interaction_policies jsonb not null default '[]'::jsonb;
alter table public.ai_tasks
  add column if not exists dataset_profile jsonb;
alter table public.ai_tasks
  add column if not exists routing_policy_id text;
alter table public.ai_tasks
  add column if not exists routing_source text;
alter table public.ai_tasks
  add column if not exists executor_type text not null default 'codex';
alter table public.ai_tasks
  add column if not exists codex_workspace_path text;
alter table public.ai_tasks
  add column if not exists codex_session_id text;
alter table public.ai_tasks
  add column if not exists codex_thread_id text;
alter table public.ai_tasks
  add column if not exists codex_status text;
alter table public.ai_tasks
  add column if not exists codex_started_at timestamptz;
alter table public.ai_tasks
  add column if not exists codex_finished_at timestamptz;
update public.ai_tasks
set creator_user_id = created_by
where creator_user_id is null;
update public.ai_tasks
set executor_type = 'codex'
where executor_type is null or executor_type <> 'codex';

drop trigger if exists ai_tasks_set_updated_at on public.ai_tasks;
create trigger ai_tasks_set_updated_at
before update on public.ai_tasks
for each row
execute function public.set_updated_at();

do $$
declare
  constraint_name text;
begin
  for constraint_name in
    select conname
    from pg_constraint
    where conrelid = 'public.ai_tasks'::regclass
      and contype = 'c'
  loop
    execute format('alter table public.ai_tasks drop constraint if exists %I', constraint_name);
  end loop;
end;
$$;

alter table public.ai_tasks
  add constraint ai_tasks_problem_type_check
  check (problem_type is null or problem_type in ('classification', 'regression'));
alter table public.ai_tasks
  add constraint ai_tasks_status_check
  check (status in ('draft', 'uploaded', 'planning', 'running', 'paused_for_review', 'waiting_human', 'completed', 'failed', 'cancelled', 'published'));
alter table public.ai_tasks
  add constraint ai_tasks_executor_type_check
  check (executor_type in ('codex'));

create table if not exists public.task_runs (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references public.teams(id) on delete cascade,
  task_id text not null references public.ai_tasks(id) on delete cascade,
  status text not null check (status in ('running', 'completed', 'failed')),
  output_dir text not null,
  best_model text,
  metric_name text,
  metric_value double precision,
  leaderboard jsonb,
  token_usage jsonb,
  notes text,
  started_at timestamptz,
  finished_at timestamptz,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now()),
  unique (task_id, output_dir)
);

drop trigger if exists task_runs_set_updated_at on public.task_runs;
create trigger task_runs_set_updated_at
before update on public.task_runs
for each row
execute function public.set_updated_at();

create table if not exists public.token_ledgers (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references public.teams(id) on delete cascade,
  user_id uuid references public.profiles(user_id) on delete set null,
  task_id text references public.ai_tasks(id) on delete cascade,
  connector_id uuid references public.ai_connectors(id) on delete set null,
  connector_display_name text,
  phase text not null,
  stage_key text,
  source_key text not null,
  model_name text,
  input_tokens integer not null default 0,
  output_tokens integer not null default 0,
  total_tokens integer not null default 0,
  calculation_method text not null default 'provider_usage',
  raw_usage jsonb,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now()),
  unique (team_id, task_id, phase, source_key)
);

alter table public.token_ledgers
  add column if not exists user_id uuid references public.profiles(user_id) on delete set null;
alter table public.token_ledgers
  add column if not exists connector_display_name text;
alter table public.token_ledgers
  add column if not exists stage_key text;
alter table public.token_ledgers
  add column if not exists calculation_method text not null default 'provider_usage';

drop trigger if exists token_ledgers_set_updated_at on public.token_ledgers;
create trigger token_ledgers_set_updated_at
before update on public.token_ledgers
for each row
execute function public.set_updated_at();

create table if not exists public.quota_accounts (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references public.teams(id) on delete cascade,
  user_id uuid references public.profiles(user_id) on delete cascade,
  connector_id uuid references public.ai_connectors(id) on delete cascade,
  scope_type text not null default 'member' check (scope_type in ('member', 'team', 'connector')),
  scope_key text not null default '',
  token_quota integer not null default 0,
  token_used integer not null default 0,
  status text not null default 'active' check (status in ('active', 'frozen', 'exhausted')),
  warning_threshold integer not null default 0,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

alter table public.quota_accounts
  add column if not exists id uuid default gen_random_uuid();
update public.quota_accounts
set id = gen_random_uuid()
where id is null;
do $$
begin
  alter table public.quota_accounts
    drop constraint if exists quota_accounts_pkey;
  alter table public.quota_accounts
    add constraint quota_accounts_pkey primary key (id);
exception
  when duplicate_object then null;
end;
$$;
alter table public.quota_accounts
  alter column user_id drop not null;
alter table public.quota_accounts
  add column if not exists connector_id uuid references public.ai_connectors(id) on delete cascade;
alter table public.quota_accounts
  add column if not exists scope_type text not null default 'member';
alter table public.quota_accounts
  add column if not exists scope_key text not null default '';
update public.quota_accounts
set scope_type = coalesce(nullif(scope_type, ''), 'member'),
    scope_key = coalesce(nullif(scope_key, ''), user_id::text, connector_id::text, team_id::text)
where scope_key = '' or scope_type is null;
alter table public.quota_accounts
  add column if not exists status text not null default 'active';
alter table public.quota_accounts
  add column if not exists warning_threshold integer not null default 0;
do $$
begin
  alter table public.quota_accounts
    drop constraint if exists quota_accounts_scope_type_check;
  alter table public.quota_accounts
    add constraint quota_accounts_scope_type_check
    check (scope_type in ('member', 'team', 'connector'));
  alter table public.quota_accounts
    drop constraint if exists quota_accounts_status_check;
  alter table public.quota_accounts
    add constraint quota_accounts_status_check
    check (status in ('active', 'frozen', 'exhausted'));
end;
$$;
create unique index if not exists quota_accounts_scope_unique_idx
on public.quota_accounts (team_id, scope_type, scope_key);

drop trigger if exists quota_accounts_set_updated_at on public.quota_accounts;
create trigger quota_accounts_set_updated_at
before update on public.quota_accounts
for each row
execute function public.set_updated_at();

create table if not exists public.ai_routing_policies (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references public.teams(id) on delete cascade,
  stage text not null,
  connector_id uuid references public.ai_connectors(id) on delete set null,
  model_name text,
  config jsonb,
  created_by uuid references public.profiles(user_id) on delete set null,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now()),
  unique (team_id, stage)
);

alter table public.ai_routing_policies
  drop column if exists fallback_connector_id;
alter table public.ai_routing_policies
  drop column if exists fallback_model_name;

drop trigger if exists ai_routing_policies_set_updated_at on public.ai_routing_policies;
create trigger ai_routing_policies_set_updated_at
before update on public.ai_routing_policies
for each row
execute function public.set_updated_at();

create table if not exists public.workflow_stage_records (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references public.teams(id) on delete cascade,
  task_id text not null references public.ai_tasks(id) on delete cascade,
  stage text not null,
  status text not null,
  selected_connector_id uuid references public.ai_connectors(id) on delete set null,
  model_name text,
  selection_source text,
  summary text,
  artifact_refs jsonb,
  started_at timestamptz,
  finished_at timestamptz,
  duration_seconds double precision,
  log_excerpt text,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

alter table public.workflow_stage_records
  add column if not exists started_at timestamptz;
alter table public.workflow_stage_records
  add column if not exists finished_at timestamptz;
alter table public.workflow_stage_records
  add column if not exists duration_seconds double precision;
alter table public.workflow_stage_records
  add column if not exists log_excerpt text;

drop trigger if exists workflow_stage_records_set_updated_at on public.workflow_stage_records;
create trigger workflow_stage_records_set_updated_at
before update on public.workflow_stage_records
for each row
execute function public.set_updated_at();

create table if not exists public.task_agent_runs (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references public.teams(id) on delete cascade,
  task_id text not null references public.ai_tasks(id) on delete cascade,
  agent_id text not null,
  stage text not null,
  name text not null,
  role text not null,
  short_role text not null,
  status text not null default 'pending',
  progress integer not null default 0 check (progress >= 0 and progress <= 100),
  current_task text not null,
  selected_connector_id uuid references public.ai_connectors(id) on delete set null,
  model_name text,
  selection_source text,
  artifact_refs jsonb,
  started_at timestamptz,
  finished_at timestamptz,
  duration_seconds double precision,
  log_excerpt text,
  worker_id text,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

alter table public.task_agent_runs
  add column if not exists progress integer not null default 0;
alter table public.task_agent_runs
  add column if not exists current_task text not null default '';
alter table public.task_agent_runs
  add column if not exists selected_connector_id uuid references public.ai_connectors(id) on delete set null;
alter table public.task_agent_runs
  add column if not exists artifact_refs jsonb;
alter table public.task_agent_runs
  add column if not exists started_at timestamptz;
alter table public.task_agent_runs
  add column if not exists finished_at timestamptz;
alter table public.task_agent_runs
  add column if not exists duration_seconds double precision;
alter table public.task_agent_runs
  add column if not exists log_excerpt text;
alter table public.task_agent_runs
  add column if not exists worker_id text;

create unique index if not exists task_agent_runs_current_unique_idx
on public.task_agent_runs (team_id, task_id, agent_id);

drop trigger if exists task_agent_runs_set_updated_at on public.task_agent_runs;
create trigger task_agent_runs_set_updated_at
before update on public.task_agent_runs
for each row
execute function public.set_updated_at();

create table if not exists public.task_agent_events (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references public.teams(id) on delete cascade,
  task_id text not null references public.ai_tasks(id) on delete cascade,
  agent_id text not null,
  stage text not null,
  kind text not null default 'agent',
  status text not null,
  text text not null,
  artifact_refs jsonb,
  created_at timestamptz not null default timezone('utc', now())
);

create index if not exists task_agent_events_task_created_idx
on public.task_agent_events (team_id, task_id, created_at desc);

create table if not exists public.task_agent_messages (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references public.teams(id) on delete cascade,
  task_id text not null references public.ai_tasks(id) on delete cascade,
  from_agent_id text not null,
  to_agent_id text,
  stage text not null,
  message_type text not null default 'coordination',
  status text not null default 'sent',
  content text not null,
  payload jsonb,
  artifact_refs jsonb,
  correlation_id text,
  created_at timestamptz not null default timezone('utc', now())
);

alter table public.task_agent_messages
  add column if not exists to_agent_id text;
alter table public.task_agent_messages
  add column if not exists message_type text not null default 'coordination';
alter table public.task_agent_messages
  add column if not exists status text not null default 'sent';
alter table public.task_agent_messages
  add column if not exists payload jsonb;
alter table public.task_agent_messages
  add column if not exists artifact_refs jsonb;
alter table public.task_agent_messages
  add column if not exists correlation_id text;

create index if not exists task_agent_messages_task_created_idx
on public.task_agent_messages (team_id, task_id, created_at desc);

create unique index if not exists task_agent_messages_correlation_unique_idx
on public.task_agent_messages (team_id, task_id, correlation_id)
where correlation_id is not null;

create table if not exists public.human_interaction_requests (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references public.teams(id) on delete cascade,
  task_id text not null references public.ai_tasks(id) on delete cascade,
  stage text not null,
  status text not null default 'open',
  requested_by uuid references public.profiles(user_id) on delete set null,
  assigned_to uuid references public.profiles(user_id) on delete set null,
  assignee_type text,
  assignee_value text,
  timeout_at timestamptz,
  version_id text,
  payload jsonb,
  decision jsonb,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

alter table public.human_interaction_requests
  add column if not exists assignee_type text;
alter table public.human_interaction_requests
  add column if not exists assignee_value text;
alter table public.human_interaction_requests
  add column if not exists timeout_at timestamptz;
alter table public.human_interaction_requests
  add column if not exists version_id text;

drop trigger if exists human_interaction_requests_set_updated_at on public.human_interaction_requests;
create trigger human_interaction_requests_set_updated_at
before update on public.human_interaction_requests
for each row
execute function public.set_updated_at();

create table if not exists public.platform_assets (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references public.teams(id) on delete cascade,
  created_by uuid references public.profiles(user_id) on delete set null,
  asset_type text not null check (asset_type in ('prompt', 'plan')),
  title text not null,
  description text,
  storage_path text,
  category text,
  tags text[] not null default '{}'::text[],
  visibility text not null default 'private' check (visibility in ('private', 'team', 'public', 'unlisted')),
  version text,
  source_task_id text references public.ai_tasks(id) on delete set null,
  source_asset_id uuid references public.platform_assets(id) on delete set null,
  model_card jsonb,
  metadata jsonb,
  review_status text not null default 'private',
  published_at timestamptz,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

alter table public.platform_assets
  add column if not exists category text;
alter table public.platform_assets
  add column if not exists tags text[] not null default '{}'::text[];
alter table public.platform_assets
  add column if not exists visibility text not null default 'private';
alter table public.platform_assets
  add column if not exists version text;
alter table public.platform_assets
  add column if not exists source_task_id text references public.ai_tasks(id) on delete set null;
alter table public.platform_assets
  add column if not exists source_asset_id uuid references public.platform_assets(id) on delete set null;
alter table public.platform_assets
  add column if not exists model_card jsonb;
alter table public.platform_assets
  add column if not exists published_at timestamptz;

do $$
begin
  alter table public.platform_assets
    drop constraint if exists platform_assets_asset_type_check;

  delete from public.platform_assets
  where asset_type not in ('prompt', 'plan');

  alter table public.platform_assets
    add constraint platform_assets_asset_type_check
    check (asset_type in ('prompt', 'plan'));

  alter table public.platform_assets
    drop constraint if exists platform_assets_visibility_check;
  alter table public.platform_assets
    add constraint platform_assets_visibility_check
    check (visibility in ('private', 'team', 'public', 'unlisted'));
end;
$$;

drop trigger if exists platform_assets_set_updated_at on public.platform_assets;
create trigger platform_assets_set_updated_at
before update on public.platform_assets
for each row
execute function public.set_updated_at();

create table if not exists public.audit_logs (
  id uuid primary key default gen_random_uuid(),
  team_id uuid references public.teams(id) on delete cascade,
  actor_id uuid references public.profiles(user_id) on delete set null,
  action text not null,
  resource_type text,
  resource_id text,
  detail jsonb,
  created_at timestamptz not null default timezone('utc', now())
);

create or replace function public.prevent_last_admin_change()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  if tg_op = 'DELETE' and old.role in ('admin', 'team_owner') and old.member_status = 'active' then
    if not exists (
      select 1
      from public.team_members
      where team_id = old.team_id
        and role in ('admin', 'team_owner')
        and member_status = 'active'
        and user_id <> old.user_id
    ) then
      raise exception 'A team must keep at least one admin';
    end if;
    return old;
  end if;

  if tg_op = 'UPDATE'
    and old.role in ('admin', 'team_owner')
    and old.member_status = 'active'
    and (
      new.role not in ('admin', 'team_owner')
      or new.member_status <> 'active'
    )
  then
    if not exists (
      select 1
      from public.team_members
      where team_id = old.team_id
        and role in ('admin', 'team_owner')
        and member_status = 'active'
        and user_id <> old.user_id
    ) then
      raise exception 'A team must keep at least one admin';
    end if;
  end if;

  return new;
end;
$$;

drop trigger if exists team_members_keep_admin on public.team_members;
create trigger team_members_keep_admin
before update or delete on public.team_members
for each row
execute function public.prevent_last_admin_change();

create or replace function public.create_team_with_owner(team_name text)
returns uuid
language plpgsql
security definer
set search_path = public
as $$
declare
  current_user_id uuid := auth.uid();
  created_team_id uuid;
begin
  if current_user_id is null then
    raise exception 'Not authenticated';
  end if;

  if trim(coalesce(team_name, '')) = '' then
    raise exception 'Team name is required';
  end if;

  insert into public.teams (name, created_by)
  values (trim(team_name), current_user_id)
  returning id into created_team_id;

  insert into public.team_members (team_id, user_id, role)
  values (created_team_id, current_user_id, 'team_owner');

  return created_team_id;
end;
$$;

create or replace function public.join_team_with_code(team_code text)
returns uuid
language plpgsql
security definer
set search_path = public
as $$
declare
  current_user_id uuid := auth.uid();
  matched_team_id uuid;
begin
  if current_user_id is null then
    raise exception 'Not authenticated';
  end if;

  select id
    into matched_team_id
  from public.teams
  where invite_code = upper(trim(coalesce(team_code, '')));

  if matched_team_id is null then
    raise exception 'Invite code not found';
  end if;

  insert into public.team_members (team_id, user_id, role)
  values (matched_team_id, current_user_id, 'business_user')
  on conflict (team_id, user_id) do nothing;

  return matched_team_id;
end;
$$;

create or replace function public.activate_ai_connector(target_team_id uuid, target_connector_id uuid)
returns public.ai_connectors
language plpgsql
security definer
set search_path = public
as $$
declare
  activated public.ai_connectors;
begin
  if auth.uid() is null then
    raise exception 'Not authenticated';
  end if;

  if not public.is_member_of_team(target_team_id) then
    raise exception 'You do not have access to the requested team.';
  end if;

  update public.ai_connectors
  set is_active = false
  where team_id = target_team_id
    and id <> target_connector_id
    and is_active = true;

  update public.ai_connectors
  set is_active = true
  where team_id = target_team_id
    and id = target_connector_id
  returning * into activated;

  if activated.id is null then
    raise exception 'Connector not found';
  end if;

  return activated;
end;
$$;

create or replace function public.adjust_member_token_usage(
  target_team_id uuid,
  target_user_id uuid,
  token_delta integer
)
returns public.quota_accounts
language plpgsql
security definer
set search_path = public
as $$
declare
  adjusted public.quota_accounts;
begin
  if auth.uid() is null then
    raise exception 'Not authenticated';
  end if;

  if not public.is_member_of_team(target_team_id) then
    raise exception 'You do not have access to the requested team.';
  end if;

  insert into public.quota_accounts (team_id, user_id, scope_type, scope_key, token_quota, token_used, status)
  values (target_team_id, target_user_id, 'member', target_user_id::text, 0, greatest(coalesce(token_delta, 0), 0), 'active')
  on conflict (team_id, scope_type, scope_key) do update
    set token_used = greatest(public.quota_accounts.token_used + coalesce(token_delta, 0), 0),
        status = case
          when public.quota_accounts.status = 'frozen' then 'frozen'
          when public.quota_accounts.token_quota > 0
            and greatest(public.quota_accounts.token_used + coalesce(token_delta, 0), 0) >= public.quota_accounts.token_quota
            then 'exhausted'
          else 'active'
        end,
        updated_at = timezone('utc', now())
  returning * into adjusted;

  return adjusted;
end;
$$;

create or replace function public.is_member_of_team(target_team_id uuid)
returns boolean
language sql
security definer
set search_path = public
as $$
  select exists (
    select 1
    from public.team_members
    where team_id = target_team_id
      and user_id = auth.uid()
      and member_status = 'active'
  );
$$;

create or replace function public.is_team_admin(target_team_id uuid)
returns boolean
language sql
security definer
set search_path = public
as $$
  select exists (
    select 1
    from public.team_members
    where team_id = target_team_id
      and user_id = auth.uid()
      and member_status = 'active'
      and role in ('team_owner', 'admin')
  );
$$;

create or replace function public.shares_team_with(target_user_id uuid)
returns boolean
language sql
security definer
set search_path = public
as $$
  select exists (
    select 1
    from public.team_members current_member
    join public.team_members other_member
      on current_member.team_id = other_member.team_id
    where current_member.user_id = auth.uid()
      and current_member.member_status = 'active'
      and other_member.user_id = target_user_id
      and other_member.member_status = 'active'
  );
$$;

alter table public.profiles enable row level security;
alter table public.teams enable row level security;
alter table public.team_members enable row level security;
alter table public.ai_connectors enable row level security;
alter table public.ai_tasks enable row level security;
alter table public.task_runs enable row level security;
alter table public.token_ledgers enable row level security;
alter table public.quota_accounts enable row level security;
alter table public.ai_routing_policies enable row level security;
alter table public.workflow_stage_records enable row level security;
alter table public.task_agent_runs enable row level security;
alter table public.task_agent_events enable row level security;
alter table public.task_agent_messages enable row level security;
alter table public.human_interaction_requests enable row level security;
alter table public.platform_assets enable row level security;
alter table public.audit_logs enable row level security;

drop policy if exists profiles_select_self_or_teammates on public.profiles;
create policy profiles_select_self_or_teammates
on public.profiles
for select
to authenticated
using (
  user_id = auth.uid()
  or public.shares_team_with(user_id)
);

drop policy if exists profiles_update_self on public.profiles;
create policy profiles_update_self
on public.profiles
for update
to authenticated
using (user_id = auth.uid())
with check (user_id = auth.uid());

drop policy if exists teams_select_if_member on public.teams;
create policy teams_select_if_member
on public.teams
for select
to authenticated
using (public.is_member_of_team(id));

drop policy if exists teams_update_if_admin on public.teams;
create policy teams_update_if_admin
on public.teams
for update
to authenticated
using (public.is_team_admin(id))
with check (public.is_team_admin(id));

drop policy if exists team_members_select_if_member on public.team_members;
create policy team_members_select_if_member
on public.team_members
for select
to authenticated
using (public.is_member_of_team(team_id));

drop policy if exists team_members_update_if_admin on public.team_members;
create policy team_members_update_if_admin
on public.team_members
for update
to authenticated
using (public.is_team_admin(team_id))
with check (public.is_team_admin(team_id));

drop policy if exists ai_connectors_select_if_member on public.ai_connectors;
create policy ai_connectors_select_if_member
on public.ai_connectors
for select
to authenticated
using (public.is_member_of_team(team_id));

drop policy if exists ai_connectors_insert_if_member on public.ai_connectors;
create policy ai_connectors_insert_if_member
on public.ai_connectors
for insert
to authenticated
with check (
  public.is_member_of_team(team_id)
  and created_by = auth.uid()
);

drop policy if exists ai_connectors_update_if_member on public.ai_connectors;
create policy ai_connectors_update_if_member
on public.ai_connectors
for update
to authenticated
using (public.is_member_of_team(team_id))
with check (public.is_member_of_team(team_id));

drop policy if exists ai_connectors_delete_if_member on public.ai_connectors;
create policy ai_connectors_delete_if_member
on public.ai_connectors
for delete
to authenticated
using (public.is_member_of_team(team_id));

drop policy if exists ai_tasks_select_if_member on public.ai_tasks;
create policy ai_tasks_select_if_member
on public.ai_tasks
for select
to authenticated
using (public.is_member_of_team(team_id));

drop policy if exists ai_tasks_insert_if_member on public.ai_tasks;
create policy ai_tasks_insert_if_member
on public.ai_tasks
for insert
to authenticated
with check (
  public.is_member_of_team(team_id)
  and created_by = auth.uid()
);

drop policy if exists ai_tasks_update_if_member on public.ai_tasks;
create policy ai_tasks_update_if_member
on public.ai_tasks
for update
to authenticated
using (public.is_member_of_team(team_id))
with check (public.is_member_of_team(team_id));

drop policy if exists ai_tasks_delete_if_member on public.ai_tasks;
create policy ai_tasks_delete_if_member
on public.ai_tasks
for delete
to authenticated
using (public.is_member_of_team(team_id));

drop policy if exists task_runs_all_if_member on public.task_runs;
create policy task_runs_all_if_member
on public.task_runs
for all
to authenticated
using (public.is_member_of_team(team_id))
with check (public.is_member_of_team(team_id));

drop policy if exists token_ledgers_all_if_member on public.token_ledgers;
create policy token_ledgers_all_if_member
on public.token_ledgers
for all
to authenticated
using (public.is_member_of_team(team_id))
with check (public.is_member_of_team(team_id));

drop policy if exists quota_accounts_all_if_member on public.quota_accounts;
create policy quota_accounts_all_if_member
on public.quota_accounts
for all
to authenticated
using (public.is_member_of_team(team_id))
with check (public.is_member_of_team(team_id));

drop policy if exists ai_routing_policies_all_if_member on public.ai_routing_policies;
create policy ai_routing_policies_all_if_member
on public.ai_routing_policies
for all
to authenticated
using (public.is_member_of_team(team_id))
with check (public.is_member_of_team(team_id));

drop policy if exists workflow_stage_records_all_if_member on public.workflow_stage_records;
create policy workflow_stage_records_all_if_member
on public.workflow_stage_records
for all
to authenticated
using (public.is_member_of_team(team_id))
with check (public.is_member_of_team(team_id));

drop policy if exists task_agent_runs_all_if_member on public.task_agent_runs;
create policy task_agent_runs_all_if_member
on public.task_agent_runs
for all
to authenticated
using (public.is_member_of_team(team_id))
with check (public.is_member_of_team(team_id));

drop policy if exists task_agent_events_all_if_member on public.task_agent_events;
create policy task_agent_events_all_if_member
on public.task_agent_events
for all
to authenticated
using (public.is_member_of_team(team_id))
with check (public.is_member_of_team(team_id));

drop policy if exists task_agent_messages_all_if_member on public.task_agent_messages;
create policy task_agent_messages_all_if_member
on public.task_agent_messages
for all
to authenticated
using (public.is_member_of_team(team_id))
with check (public.is_member_of_team(team_id));

drop policy if exists human_interaction_requests_all_if_member on public.human_interaction_requests;
create policy human_interaction_requests_all_if_member
on public.human_interaction_requests
for all
to authenticated
using (public.is_member_of_team(team_id))
with check (public.is_member_of_team(team_id));

drop policy if exists platform_assets_all_if_member on public.platform_assets;
create policy platform_assets_all_if_member
on public.platform_assets
for all
to authenticated
using (public.is_member_of_team(team_id))
with check (public.is_member_of_team(team_id));

drop policy if exists audit_logs_all_if_member on public.audit_logs;
create policy audit_logs_all_if_member
on public.audit_logs
for all
to authenticated
using (team_id is null or public.is_member_of_team(team_id))
with check (team_id is null or public.is_member_of_team(team_id));

grant execute on function public.create_team_with_owner(text) to authenticated;
grant execute on function public.join_team_with_code(text) to authenticated;
grant execute on function public.activate_ai_connector(uuid, uuid) to authenticated;
grant execute on function public.adjust_member_token_usage(uuid, uuid, integer) to authenticated;
grant execute on function public.is_member_of_team(uuid) to authenticated;
grant execute on function public.shares_team_with(uuid) to authenticated;
