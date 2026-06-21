-- Optional phase-1 test data. Replace the URLs/IDs or enter records in the UI.
-- This is intentionally not run automatically.
insert into public.creators
  (name, platform, profile_url, platform_creator_id, category, is_tracked)
values
  ('示例 B站博主', 'bilibili', 'https://space.bilibili.com/123456', '123456', 'AI 工具', true),
  ('示例抖音博主', 'douyin', 'https://www.douyin.com/user/example', 'example', '内容创作', false)
on conflict (platform, platform_creator_id) do nothing;
