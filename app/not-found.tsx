import Link from "next/link";

export default function NotFound() {
  return <main style={{ minHeight: "100vh", display: "grid", placeItems: "center", padding: 24 }}><div className="empty-state"><div className="empty-icon">?</div><h3>没有找到这条记录</h3><p>它可能已删除，或当前账号没有访问权限。</p><Link className="button button-primary" href="/">返回仪表盘</Link></div></main>;
}

