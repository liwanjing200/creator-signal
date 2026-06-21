import Link from "next/link";
import { redirect } from "next/navigation";
import { logout } from "@/app/actions";
import { createClient } from "@/lib/supabase/server";

const navigation = [
  { href: "/", label: "仪表盘", icon: "⌂" },
  { href: "/creators", label: "博主", icon: "◎" },
  { href: "/videos", label: "视频", icon: "▷" },
  { href: "/jobs", label: "任务日志", icon: "≡" }
];

export const dynamic = "force-dynamic";

export default async function DashboardLayout({ children }: { children: React.ReactNode }) {
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect("/login");

  return <div className="app-shell">
    <aside className="sidebar">
      <Link className="brand" href="/"><span className="brand-mark">CS</span> Creator Signal</Link>
      <div className="nav-label">Workspace</div>
      <nav className="nav-list">
        {navigation.map((item) => <Link className="nav-link" href={item.href} key={item.href}><span className="nav-icon">{item.icon}</span>{item.label}</Link>)}
      </nav>
      <div className="sidebar-foot">
        <div className="user-email">{user.email}</div>
        <form action={logout}><button className="logout-button" type="submit">安全退出</button></form>
      </div>
    </aside>
    <main className="main"><div className="main-inner">{children}</div></main>
  </div>;
}

