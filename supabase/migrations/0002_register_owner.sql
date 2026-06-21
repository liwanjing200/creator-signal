-- Register the single allowed application user after creating them in Supabase Auth.
insert into public.app_users (user_id)
select id
from auth.users
where lower(email) = lower('lishuyue200@gmail.com')
on conflict (user_id) do nothing;

do $$
begin
  if not exists (
    select 1
    from public.app_users au
    join auth.users u on u.id = au.user_id
    where lower(u.email) = lower('lishuyue200@gmail.com')
  ) then
    raise exception 'Auth user lishuyue200@gmail.com was not found or could not be registered';
  end if;
end $$;
