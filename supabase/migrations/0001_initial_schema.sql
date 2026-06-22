-- Creator Intelligence Hub — initial schema
-- Run in a new Supabase project's SQL editor.

create extension if not exists pgcrypto;

create type public.platform_type as enum ('bilibili', 'douyin', 'x');
create type public.job_status as enum ('queued', 'running', 'succeeded', 'partially_succeeded', 'failed', 'cancelled');
create type public.job_type as enum ('bilibili_crawl', 'douyin_crawl', 'x_crawl', 'bilibili_comments', 'transcribe_video', 'full_crawl', 'manual');
create type public.transcript_status as enum ('pending', 'processing', 'completed', 'failed', 'skipped');
create type public.transcript_source as enum ('platform_subtitle', 'srt', 'vtt', 'json_subtitle', 'public_copy', 'whisper_cpp', 'manual');

-- Membership is deliberately separate from auth.users. Data policies require a
-- matching row, so even another authenticated Supabase account sees nothing.
create table public.app_users (
  user_id uuid primary key references auth.users(id) on delete cascade,
  created_at timestamptz not null default now()
);

create table public.creators (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  platform public.platform_type not null,
  profile_url text not null,
  platform_creator_id text not null,
  sec_uid text,
  category text,
  is_tracked boolean not null default true,
  follower_count bigint check (follower_count is null or follower_count >= 0),
  total_likes_count bigint check (total_likes_count is null or total_likes_count >= 0),
  last_crawled_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (platform, platform_creator_id)
);

create table public.videos (
  id uuid primary key default gen_random_uuid(),
  creator_id uuid not null references public.creators(id) on delete cascade,
  platform public.platform_type not null,
  platform_video_id text not null,
  title text not null,
  video_url text not null,
  cover_url text,
  description text,
  published_at timestamptz,
  duration_seconds integer check (duration_seconds is null or duration_seconds >= 0),
  parts_json jsonb not null default '[]'::jsonb,
  chapters_json jsonb not null default '[]'::jsonb,
  is_pinned boolean,
  view_count bigint check (view_count is null or view_count >= 0),
  like_count bigint check (like_count is null or like_count >= 0),
  coin_count bigint check (coin_count is null or coin_count >= 0),
  favorite_count bigint check (favorite_count is null or favorite_count >= 0),
  share_count bigint check (share_count is null or share_count >= 0),
  comment_count bigint check (comment_count is null or comment_count >= 0),
  danmaku_count bigint check (danmaku_count is null or danmaku_count >= 0),
  transcript_status public.transcript_status not null default 'pending',
  keep_original_file boolean not null default false,
  reference_summary text,
  candidate_quotes jsonb not null default '[]'::jsonb,
  ai_summary text,
  ai_core_ideas jsonb,
  ai_user_pain_points jsonb,
  ai_topic_ideas jsonb,
  ai_x_drafts jsonb,
  last_crawled_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (platform, platform_video_id)
);

create table public.comments (
  id uuid primary key default gen_random_uuid(),
  video_id uuid not null references public.videos(id) on delete cascade,
  parent_comment_id uuid references public.comments(id) on delete cascade,
  platform_comment_id text not null,
  author_name text,
  author_platform_id text,
  content text not null,
  like_count bigint check (like_count is null or like_count >= 0),
  published_at timestamptz,
  is_reply boolean not null default false,
  is_representative boolean not null default true,
  is_partial_public_sample boolean not null default false,
  created_at timestamptz not null default now(),
  unique (video_id, platform_comment_id)
);

create table public.transcripts (
  id uuid primary key default gen_random_uuid(),
  video_id uuid not null references public.videos(id) on delete cascade,
  source public.transcript_source not null,
  status public.transcript_status not null default 'pending',
  language text,
  model_name text,
  raw_text text,
  cleaned_text text,
  segments_json jsonb not null default '[]'::jsonb,
  txt_local_path text,
  subtitle_local_path text,
  json_local_path text,
  started_at timestamptz,
  completed_at timestamptz,
  error_message text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.transcript_segments (
  id bigint generated always as identity primary key,
  transcript_id uuid not null references public.transcripts(id) on delete cascade,
  video_id uuid not null references public.videos(id) on delete cascade,
  segment_index integer not null check (segment_index >= 0),
  start_seconds numeric(12,3) not null check (start_seconds >= 0),
  end_seconds numeric(12,3) not null check (end_seconds >= start_seconds),
  text text not null,
  created_at timestamptz not null default now(),
  unique (transcript_id, segment_index)
);

create table public.creator_metrics_snapshots (
  id bigint generated always as identity primary key,
  creator_id uuid not null references public.creators(id) on delete cascade,
  follower_count bigint,
  total_likes_count bigint,
  captured_at timestamptz not null default now()
);

create table public.video_metrics_snapshots (
  id bigint generated always as identity primary key,
  video_id uuid not null references public.videos(id) on delete cascade,
  view_count bigint,
  like_count bigint,
  coin_count bigint,
  favorite_count bigint,
  share_count bigint,
  comment_count bigint,
  danmaku_count bigint,
  captured_at timestamptz not null default now()
);

create table public.crawl_jobs (
  id uuid primary key default gen_random_uuid(),
  platform public.platform_type,
  creator_id uuid references public.creators(id) on delete set null,
  video_id uuid references public.videos(id) on delete set null,
  job_type public.job_type not null,
  status public.job_status not null default 'queued',
  started_at timestamptz,
  finished_at timestamptz,
  success_count integer not null default 0 check (success_count >= 0),
  updated_count integer not null default 0 check (updated_count >= 0),
  skipped_count integer not null default 0 check (skipped_count >= 0),
  failed_count integer not null default 0 check (failed_count >= 0),
  error_summary text,
  manifest_path text,
  options_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table public.saved_files (
  id uuid primary key default gen_random_uuid(),
  video_id uuid not null references public.videos(id) on delete cascade,
  file_kind text not null check (file_kind in ('video', 'audio', 'txt', 'srt', 'vtt', 'json', 'other')),
  local_path text not null,
  file_size_bytes bigint,
  checksum_sha256 text,
  is_retained boolean not null default false,
  deleted_at timestamptz,
  created_at timestamptz not null default now()
);

create index creators_tracking_idx on public.creators (is_tracked, platform);
create index videos_creator_published_idx on public.videos (creator_id, published_at desc);
create index videos_transcript_status_idx on public.videos (transcript_status);
create index comments_video_idx on public.comments (video_id, like_count desc nulls last);
create index transcript_segments_video_idx on public.transcript_segments (video_id, start_seconds);
create index creator_metrics_timeline_idx on public.creator_metrics_snapshots (creator_id, captured_at desc);
create index video_metrics_timeline_idx on public.video_metrics_snapshots (video_id, captured_at desc);
create index crawl_jobs_recent_idx on public.crawl_jobs (created_at desc);

create or replace function public.set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create trigger creators_set_updated_at before update on public.creators
for each row execute function public.set_updated_at();
create trigger videos_set_updated_at before update on public.videos
for each row execute function public.set_updated_at();
create trigger transcripts_set_updated_at before update on public.transcripts
for each row execute function public.set_updated_at();

create or replace function public.is_app_user()
returns boolean language sql stable security definer set search_path = public
as $$ select exists (select 1 from public.app_users where user_id = auth.uid()) $$;
revoke all on function public.is_app_user() from public;
grant execute on function public.is_app_user() to authenticated;

alter table public.app_users enable row level security;
alter table public.creators enable row level security;
alter table public.videos enable row level security;
alter table public.comments enable row level security;
alter table public.transcripts enable row level security;
alter table public.transcript_segments enable row level security;
alter table public.creator_metrics_snapshots enable row level security;
alter table public.video_metrics_snapshots enable row level security;
alter table public.crawl_jobs enable row level security;
alter table public.saved_files enable row level security;

revoke all on all tables in schema public from anon;
grant select, insert, update, delete on all tables in schema public to authenticated, service_role;
grant usage, select on all sequences in schema public to authenticated, service_role;

create policy "read own membership" on public.app_users for select to authenticated
using (user_id = auth.uid());

-- One-person application: membership grants full CRUD; service_role bypasses RLS
-- for trusted local ingestion scripts.
do $$
declare table_name text;
begin
  foreach table_name in array array[
    'creators', 'videos', 'comments', 'transcripts', 'transcript_segments',
    'creator_metrics_snapshots', 'video_metrics_snapshots', 'crawl_jobs', 'saved_files'
  ] loop
    execute format(
      'create policy "app user full access" on public.%I for all to authenticated using (public.is_app_user()) with check (public.is_app_user())',
      table_name
    );
  end loop;
end $$;

-- After creating your Auth user, run this once in the SQL editor:
-- insert into public.app_users (user_id)
-- select id from auth.users where email = 'you@example.com'
-- on conflict do nothing;
