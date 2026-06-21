import { login } from "@/app/actions";
import { Flash } from "@/components/flash";

export const dynamic = "force-dynamic";

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ error?: string }> }) {
  const { error } = await searchParams;
  return <main className="auth-shell">
    <section className="auth-story">
      <div className="brand"><span className="brand-mark">CS</span> Creator Signal</div>
      <div className="auth-copy">
        <span className="eyebrow">Personal intelligence workspace</span>
        <h1>让好内容留下可追踪的信号。</h1>
        <p>统一管理 B站与抖音博主、视频、字幕和采集任务。数据属于你，运行也掌握在你自己的 Mac 上。</p>
      </div>
      <div className="auth-foot">Private by design · Supabase RLS protected</div>
    </section>
    <section className="auth-form-wrap">
      <form action={login} className="auth-form">
        <span className="eyebrow">Welcome back</span>
        <h2>登录你的资料库</h2>
        <p>这里只开放给你自己的 Supabase 账号。</p>
        <Flash error={error} />
        <div className="field" style={{ marginBottom: 16 }}>
          <label className="required" htmlFor="email">邮箱</label>
          <input className="input" id="email" name="email" type="email" autoComplete="email" required placeholder="you@example.com" />
        </div>
        <div className="field" style={{ marginBottom: 22 }}>
          <label className="required" htmlFor="password">密码</label>
          <input className="input" id="password" name="password" type="password" autoComplete="current-password" required placeholder="••••••••" />
        </div>
        <button className="button button-primary" style={{ width: "100%" }} type="submit">登录</button>
      </form>
    </section>
  </main>;
}

