import Image from "next/image";
import Link from "next/link";
import { createVideo } from "@/app/actions";
import { Badge } from "@/components/badge";
import { EmptyState } from "@/components/empty-state";
import { Flash } from "@/components/flash";
import { PlatformBadge } from "@/components/platform-badge";
import { createClient } from "@/lib/supabase/server";
import { formatDate, formatNumber, platformLabel, transcriptLabel } from "@/lib/format";
import type { Creator, Platform, TranscriptStatus, Video } from "@/lib/types";

type Params = { q?: string; platform?: Platform; creator?: string; status?: TranscriptStatus; from?: string; to?: string; sort?: string; success?: string; error?: string };

export default async function VideosPage({ searchParams }: { searchParams: Promise<Params> }) {
  const params = await searchParams;
  const supabase = await createClient();
  const sortColumns: Record<string, string> = { newest: "published_at", views: "view_count", likes: "like_count", crawled: "last_crawled_at" };
  let query = supabase.from("videos").select("*, creators(id, name, platform)").order(sortColumns[params.sort ?? "newest"] ?? "published_at", { ascending: false, nullsFirst: false });
  if (params.q) query = query.ilike("title", `%${params.q.replace(/[%_,()]/g, "")}%`);
  if (params.platform) query = query.eq("platform", params.platform);
  if (params.creator) query = query.eq("creator_id", params.creator);
  if (params.status) query = query.eq("transcript_status", params.status);
  if (params.from) query = query.gte("published_at", `${params.from}T00:00:00+08:00`);
  if (params.to) query = query.lte("published_at", `${params.to}T23:59:59+08:00`);
  const [{ data }, { data: creatorRows }] = await Promise.all([query, supabase.from("creators").select("*").order("name")]);
  const videos = (data ?? []) as unknown as Video[];
  const creators = (creatorRows ?? []) as Creator[];

  return <>
    <header className="topbar"><div><span className="eyebrow">Content library</span><h1 className="page-title">视频资料库</h1><p className="page-subtitle">浏览内容、互动数据与字幕处理状态。</p></div><a className="button button-primary" href="#new-video">＋ 添加测试视频</a></header>
    <Flash success={params.success} error={params.error} />
    <form className="filters">
      <div className="filter-field search-field"><label htmlFor="q">搜索</label><input className="input" id="q" name="q" defaultValue={params.q} placeholder="搜索视频标题" /></div>
      <div className="filter-field"><label htmlFor="platform">平台</label><select className="select" id="platform" name="platform" defaultValue={params.platform ?? ""}><option value="">全部</option><option value="bilibili">B站</option><option value="douyin">抖音</option><option value="x">X</option></select></div>
      <div className="filter-field"><label htmlFor="creator">博主</label><select className="select" id="creator" name="creator" defaultValue={params.creator ?? ""}><option value="">全部</option>{creators.map((creator) => <option value={creator.id} key={creator.id}>{creator.name}</option>)}</select></div>
      <div className="filter-field"><label htmlFor="status">字幕</label><select className="select" id="status" name="status" defaultValue={params.status ?? ""}><option value="">全部</option><option value="pending">待转写</option><option value="processing">转写中</option><option value="completed">已完成</option><option value="failed">失败</option><option value="skipped">已跳过</option></select></div>
      <div className="filter-field"><label htmlFor="from">开始日期</label><input className="input" id="from" name="from" type="date" defaultValue={params.from} /></div>
      <div className="filter-field"><label htmlFor="to">结束日期</label><input className="input" id="to" name="to" type="date" defaultValue={params.to} /></div>
      <div className="filter-field"><label htmlFor="sort">排序</label><select className="select" id="sort" name="sort" defaultValue={params.sort ?? "newest"}><option value="newest">最新发布</option><option value="views">播放最多</option><option value="likes">点赞最多</option><option value="crawled">最近采集</option></select></div>
      <button className="button button-secondary" type="submit">筛选</button><Link className="button button-secondary" href="/videos">清除</Link>
    </form>
    <section className="table-card">
      {videos.length ? <div className="table-scroll"><table><thead><tr><th>封面</th><th>视频</th><th>平台</th><th>发布时间</th><th>播放</th><th>点赞</th><th>评论</th><th>字幕</th><th>最近采集</th></tr></thead><tbody>
        {videos.map((video) => <tr key={video.id}>
          <td>{video.cover_url ? <Image className="cover-thumb" src={video.cover_url} alt="" width={144} height={88} unoptimized /> : <div className="cover-placeholder">NO COVER</div>}</td>
          <td><div className="cell-title"><Link href={`/videos/${video.id}`}>{video.title}</Link></div><div className="cell-subtitle">{video.creators?.name} · {video.description ?? video.platform_video_id}</div></td>
          <td><PlatformBadge platform={video.platform} /></td><td>{formatDate(video.published_at, true)}</td><td>{formatNumber(video.view_count)}</td><td>{formatNumber(video.like_count)}</td><td>{formatNumber(video.comment_count)}</td>
          <td><Badge tone={video.transcript_status === "completed" ? "green" : video.transcript_status === "failed" ? "red" : video.transcript_status === "processing" ? "blue" : "neutral"}>{transcriptLabel[video.transcript_status]}</Badge></td><td>{formatDate(video.last_crawled_at, true)}</td>
        </tr>)}
      </tbody></table></div> : <EmptyState title="没有匹配的视频" description="先添加一条测试视频，确认页面和数据权限都工作正常。" action={<a className="button button-primary" href="#new-video">添加测试视频</a>} />}
    </section>
    <section className="card section-gap" id="new-video">
      <div className="card-header"><div><h2 className="card-title">添加测试视频</h2><div className="cell-subtitle">仅写入元数据，不下载任何媒体。</div></div></div>
      <form action={createVideo} className="card-body"><div className="form-grid">
        <div className="field"><label className="required" htmlFor="creator-new">博主</label><select className="select" id="creator-new" name="creator_id" required><option value="">请选择</option>{creators.map((creator) => <option value={creator.id} key={creator.id}>{creator.name} · {platformLabel[creator.platform]}</option>)}</select></div>
        <div className="field"><label className="required" htmlFor="platform_video_id">平台视频 ID</label><input className="input" id="platform_video_id" name="platform_video_id" required placeholder="BVID 或 Aweme ID" /></div>
        <div className="field form-span-2"><label className="required" htmlFor="title">标题</label><input className="input" id="title" name="title" required /></div>
        <div className="field form-span-2"><label className="required" htmlFor="video_url">原视频链接</label><input className="input" id="video_url" name="video_url" type="url" required /></div>
        <div className="field form-span-2"><label htmlFor="cover_url">封面链接</label><input className="input" id="cover_url" name="cover_url" type="url" /></div>
        <div className="field form-span-2"><label htmlFor="description">简介</label><textarea className="textarea" id="description" name="description" /></div>
        <div className="field"><label htmlFor="published_at">发布时间</label><input className="input" id="published_at" name="published_at" type="datetime-local" /></div>
        <div className="field"><label htmlFor="duration_seconds">时长（秒）</label><input className="input" id="duration_seconds" name="duration_seconds" type="number" min="0" /></div>
        <div className="field"><label htmlFor="view_count">播放数</label><input className="input" id="view_count" name="view_count" type="number" min="0" /></div>
        <div className="field"><label htmlFor="like_count">点赞数</label><input className="input" id="like_count" name="like_count" type="number" min="0" /></div>
        <div className="field"><label htmlFor="comment_count">评论数</label><input className="input" id="comment_count" name="comment_count" type="number" min="0" /></div>
        <div className="field"><label htmlFor="transcript_status">字幕状态</label><select className="select" id="transcript_status" name="transcript_status"><option value="pending">待转写</option><option value="completed">已完成</option><option value="skipped">已跳过</option></select></div>
      </div><div className="form-actions"><button className="button button-primary" type="submit" disabled={!creators.length}>保存测试视频</button></div></form>
    </section>
  </>;
}
