import { requestPasswordReset } from "@/app/actions";
import { Flash } from "@/components/flash";

export const dynamic = "force-dynamic";

export default async function ForgotPasswordPage({ searchParams }: { searchParams: Promise<{ error?: string }> }) {
  const { error } = await searchParams;
  return <main className="auth-shell">
    <section className="auth-story">
      <div className="brand"><span className="brand-mark">CS</span> Creator Signal</div>
      <div className="auth-copy">
        <span className="eyebrow">Account recovery</span>
        <h1>重新进入你的资料库。</h1>
        <p>输入唯一账号邮箱，Supabase 会发送安全的密码重置链接。</p>
      </div>
      <div className="auth-foot">Private by design · Supabase Auth</div>
    </section>
    <section className="auth-form-wrap">
      <form action={requestPasswordReset} className="auth-form">
        <span className="eyebrow">Reset password</span>
        <h2>发送重置邮件</h2>
        <p>邮件中的链接只在短时间内有效。</p>
        <Flash error={error} />
        <div className="field" style={{ marginBottom: 22 }}>
          <label className="required" htmlFor="email">邮箱</label>
          <input className="input" id="email" name="email" type="email" autoComplete="email" required defaultValue="lishuyue200@gmail.com" />
        </div>
        <button className="button button-primary" style={{ width: "100%" }} type="submit">发送重置邮件</button>
        <a className="auth-link" href="/login">返回登录</a>
      </form>
    </section>
  </main>;
}
