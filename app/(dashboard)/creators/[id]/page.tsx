import Link from "next/link";
import { notFound } from "next/navigation";
import { queueCreatorUpdate, toggleCreator } from "@/app/actions";
import { Badge } from "@/components/badge";
import { EmptyState } from "@/components/empty-state";
import { Flash } from "@/components/flash";
import { PlatformBadge } from "@/components/platform-badge";
import { createClient } from "@/lib/supabase/server";
import { formatDate, formatNumber, transcriptLabel } from "@/lib/format";
import type { Creator, Video } from "@/lib/types";

export default async function CreatorDetailPage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ success?: string; error?: string }> }) {
  const { id } = await params;
  const { success, error } = await searchParams;
  const supabase = await createClient();
  const [{ data: creatorData }, { data: videosData }, { data: snapshots }] = await Promise.all([
    supabase.from("creators").select("*").eq("id", id).single(),
    supabase.from("videos").select("*").eq("creator_id", id).order("published_at", { ascending: false }).limit(20),
    supabase.from("creator_metrics_snapshots").select("*").eq("creator_id", id).order("captured_at", { ascending: false }).limit(12)
  ]);
  if (!creatorData) notFound();
  const creator = creatorData as Creator;
  const videos = (videosData ?? []) as Video[];

  return <>
    <header className="topbar">
      <div><span className="eyebrow">Creator profile</span><h1 className="page-title">{creator.name}</h1><p className="page-subtitle">创作者资料、内容列表和数据变化。</p></div>
      <div className="top-actions"><Link className="button button-secondary" href="/creators">← 返回</Link><Link className="button button-primary" href={`/creators/${id}/edit`}>编辑资料</Link></div>
    </header>
    <Flash success={success} error={error} />
    <section className="detail-hero">
      <div>
        <div className="detail-meta"><PlatformBadge platform={creator.platform} /><Badge tone={creator.is_tracked ? "green" : "neutral"}>{creator.is_tracked ? "追踪中" : "已停用"}</Badge>{creator.category && <Badge>{creator.category}</Badge>}</div>
        <h2 className="detail-title">{creator.name}</h2>
        <p className="detail-description">平台 ID · {creator.platform_creator_id}{creator.sec_uid ? `\nSecUID · ${creator.sec_uid}` : ""}</p>
      </div>
      <div className="top-actions"><form action={queueCreatorUpdate.bind(null, id)}><button className="button button-primary" type="submit">立即更新</button></form><form action={toggleCreator.bind(null, id, !creator.is_tracked)}><button className={`button ${creator.is_tracked ? "button-danger" : "button-primary"}`} type="submit">{creator.is_tracked ? "停用追踪" : "启用追踪"}</button></form></div>
    </section>
    <section className="metrics-row">
      <div className="metric"><div className="metric-label">视频数</div><div className="metric-value">{videos.length}</div></div>
      <div className="metric"><div className="metric-label">粉丝数</div><div className="metric-value">{formatNumber(creator.follower_count)}</div></div>
      <div className="metric"><div className="metric-label">获赞数</div><div className="metric-value">{formatNumber(creator.total_likes_count)}</div></div>
      <div className="metric"><div className="metric-label">最近采集</div><div className="metric-value" style={{ fontSize: 13 }}>{formatDate(creator.last_crawled_at, true)}</div></div>
      <div className="metric"><div className="metric-label">数据快照</div><div className="metric-value">{snapshots?.length ?? 0}</div></div>
      <div className="metric"><div className="metric-label">状态</div><div className="metric-value" style={{ fontSize: 13 }}>{creator.is_tracked ? "正常追踪" : "暂停"}</div></div>
    </section>
    <section className="card">
      <div className="card-header"><h2 className="card-title">最近视频</h2><Link className="card-link" href={`/videos?creator=${id}`}>查看全部 →</Link></div>
      {videos.length ? <div className="table-scroll"><table><thead><tr><th>标题</th><th>发布时间</th><th>播放</th><th>点赞</th><th>字幕</th></tr></thead><tbody>
        {videos.map((video) => <tr key={video.id}><td><div className="cell-title"><Link href={`/videos/${video.id}`}>{video.title}</Link></div></td><td>{formatDate(video.published_at, true)}</td><td>{formatNumber(video.view_count)}</td><td>{formatNumber(video.like_count)}</td><td><Badge tone={video.transcript_status === "completed" ? "green" : video.transcript_status === "failed" ? "red" : "neutral"}>{transcriptLabel[video.transcript_status]}</Badge></td></tr>)}
      </tbody></table></div> : <EmptyState title="还没有视频" description="可先在视频页手工添加测试数据；阶段 2 会自动采集。" action={<Link className="button button-primary" href="/videos#new-video">添加测试视频</Link>} />}
    </section>
    {(snapshots?.length ?? 0) > 0 && <section className="card section-gap"><div className="card-header"><h2 className="card-title">数据趋势记录</h2><span className="cell-subtitle">最近 {snapshots?.length} 次</span></div><div className="card-body"><div className="timeline">{snapshots?.map((snapshot) => <div className="timeline-item" key={snapshot.id}><span className="timeline-dot" /><div className="timeline-title">{formatNumber(snapshot.follower_count)} 粉丝 · {formatNumber(snapshot.total_likes_count)} 获赞</div><div className="timeline-meta">{formatDate(snapshot.captured_at, true)}</div></div>)}</div></div></section>}
  </>;
}
