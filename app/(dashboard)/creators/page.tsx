import Link from "next/link";
import { createCreator, toggleCreator } from "@/app/actions";
import { EmptyState } from "@/components/empty-state";
import { Flash } from "@/components/flash";
import { PlatformBadge } from "@/components/platform-badge";
import { Badge } from "@/components/badge";
import { createClient } from "@/lib/supabase/server";
import { formatDate, formatNumber } from "@/lib/format";
import type { Creator, Platform } from "@/lib/types";

type Params = { q?: string; platform?: Platform; category?: string; status?: string; success?: string; error?: string };

export default async function CreatorsPage({ searchParams }: { searchParams: Promise<Params> }) {
  const params = await searchParams;
  const supabase = await createClient();
  let query = supabase.from("creators").select("*").order("is_tracked", { ascending: false }).order("updated_at", { ascending: false });
  if (params.q) query = query.ilike("name", `%${params.q.replace(/[%_,()]/g, "")}%`);
  if (params.platform) query = query.eq("platform", params.platform);
  if (params.category) query = query.eq("category", params.category);
  if (params.status === "tracked") query = query.eq("is_tracked", true);
  if (params.status === "paused") query = query.eq("is_tracked", false);
  const [{ data }, { data: categoryRows }] = await Promise.all([
    query,
    supabase.from("creators").select("category").not("category", "is", null)
  ]);
  const creators = (data ?? []) as Creator[];
  const categories = [...new Set((categoryRows ?? []).map((row) => row.category).filter(Boolean))] as string[];

  return <>
    <header className="topbar">
      <div><span className="eyebrow">Creators</span><h1 className="page-title">博主管理</h1><p className="page-subtitle">维护 B站、抖音和 X 创作者资料，决定谁进入采集队列。</p></div>
      <div className="top-actions"><a className="button button-primary" href="#new-creator">＋ 新增博主</a></div>
    </header>
    <Flash success={params.success} error={params.error} />
    <form className="filters">
      <div className="filter-field search-field"><label htmlFor="q">搜索</label><input className="input" id="q" name="q" defaultValue={params.q} placeholder="搜索博主名称" /></div>
      <div className="filter-field"><label htmlFor="platform">平台</label><select className="select" id="platform" name="platform" defaultValue={params.platform ?? ""}><option value="">全部平台</option><option value="bilibili">B站</option><option value="douyin">抖音</option><option value="x">X</option></select></div>
      <div className="filter-field"><label htmlFor="category">分类</label><select className="select" id="category" name="category" defaultValue={params.category ?? ""}><option value="">全部分类</option>{categories.map((category) => <option key={category}>{category}</option>)}</select></div>
      <div className="filter-field"><label htmlFor="status">状态</label><select className="select" id="status" name="status" defaultValue={params.status ?? ""}><option value="">全部状态</option><option value="tracked">追踪中</option><option value="paused">已停用</option></select></div>
      <button className="button button-secondary" type="submit">筛选</button>
      <Link className="button button-secondary" href="/creators">清除</Link>
    </form>

    <section className="table-card">
      {creators.length ? <div className="table-scroll"><table><thead><tr><th>博主</th><th>平台</th><th>分类</th><th>粉丝</th><th>获赞</th><th>最近采集</th><th>状态</th><th></th></tr></thead><tbody>
        {creators.map((creator) => <tr key={creator.id}>
          <td><div className="cell-title"><Link href={`/creators/${creator.id}`}>{creator.name}</Link></div><div className="cell-subtitle">ID · {creator.platform_creator_id}</div></td>
          <td><PlatformBadge platform={creator.platform} /></td>
          <td>{creator.category ?? "—"}</td>
          <td>{formatNumber(creator.follower_count)}</td>
          <td>{formatNumber(creator.total_likes_count)}</td>
          <td>{formatDate(creator.last_crawled_at, true)}</td>
          <td><Badge tone={creator.is_tracked ? "green" : "neutral"}>{creator.is_tracked ? "追踪中" : "已停用"}</Badge></td>
          <td><div className="row-actions"><Link className="button button-secondary button-small" href={`/creators/${creator.id}/edit`}>编辑</Link><form action={toggleCreator.bind(null, creator.id, !creator.is_tracked)}><button className="button button-secondary button-small" type="submit">{creator.is_tracked ? "停用" : "启用"}</button></form></div></td>
        </tr>)}
      </tbody></table></div> : <EmptyState title="没有匹配的博主" description="新增第一位创作者，或调整当前筛选条件。" action={<a className="button button-primary" href="#new-creator">新增博主</a>} />}
    </section>

    <section className="card section-gap" id="new-creator">
      <div className="card-header"><div><h2 className="card-title">新增博主</h2><div className="cell-subtitle">阶段 1 支持手工录入，采集器稍后接入。</div></div></div>
      <form action={createCreator} className="card-body">
        <div className="form-grid">
          <div className="field"><label className="required" htmlFor="name">名称</label><input className="input" id="name" name="name" required /></div>
          <div className="field"><label className="required" htmlFor="platform-new">平台</label><select className="select" id="platform-new" name="platform" required><option value="bilibili">B站</option><option value="douyin">抖音</option><option value="x">X</option></select></div>
          <div className="field form-span-2"><label className="required" htmlFor="profile_url">主页链接</label><input className="input" id="profile_url" name="profile_url" type="url" required placeholder="https://..." /></div>
          <div className="field"><label className="required" htmlFor="platform_creator_id">平台 ID</label><input className="input" id="platform_creator_id" name="platform_creator_id" required /><span className="field-hint">B站 UID、抖音用户标识或 X @username</span></div>
          <div className="field"><label htmlFor="sec_uid">抖音 SecUID</label><input className="input" id="sec_uid" name="sec_uid" /></div>
          <div className="field"><label htmlFor="category-new">分类</label><input className="input" id="category-new" name="category" placeholder="例如：AI 工具" /></div>
          <div className="field"><label>追踪状态</label><label className="checkbox-field"><input name="is_tracked" type="checkbox" defaultChecked /> 加入采集队列</label></div>
          <div className="field"><label htmlFor="follower_count">粉丝数</label><input className="input" id="follower_count" name="follower_count" type="number" min="0" /></div>
          <div className="field"><label htmlFor="total_likes_count">抖音获赞数</label><input className="input" id="total_likes_count" name="total_likes_count" type="number" min="0" /></div>
        </div>
        <div className="form-actions"><button className="button button-primary" type="submit">保存博主</button></div>
      </form>
    </section>
  </>;
}
