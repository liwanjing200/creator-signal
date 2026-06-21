import { updatePassword } from "@/app/actions";
import { Flash } from "@/components/flash";

export const dynamic = "force-dynamic";

export default async function ResetPasswordPage({ searchParams }: { searchParams: Promise<{ error?: string }> }) {
  const { error } = await searchParams;
  return <main className="auth-shell">
    <section className="auth-story">
      <div className="brand"><span className="brand-mark">CS</span> Creator Signal</div>
      <div className="auth-copy">
        <span className="eyebrow">Secure update</span>
        <h1>设置一个新密码。</h1>
        <p>新密码至少 8 位；更新成功后会返回登录页。</p>
      </div>
      <div className="auth-foot">Recovery session protected</div>
    </section>
    <section className="auth-form-wrap">
      <form action={updatePassword} className="auth-form">
        <span className="eyebrow">New password</span>
        <h2>更新密码</h2>
        <p>请连续输入两次相同的新密码。</p>
        <Flash error={error} />
        <div className="field" style={{ marginBottom: 16 }}>
          <label className="required" htmlFor="password">新密码</label>
          <input className="input" id="password" name="password" type="password" autoComplete="new-password" minLength={8} required />
        </div>
        <div className="field" style={{ marginBottom: 22 }}>
          <label className="required" htmlFor="password_confirmation">再次输入</label>
          <input className="input" id="password_confirmation" name="password_confirmation" type="password" autoComplete="new-password" minLength={8} required />
        </div>
        <button className="button button-primary" style={{ width: "100%" }} type="submit">保存新密码</button>
      </form>
    </section>
  </main>;
}
