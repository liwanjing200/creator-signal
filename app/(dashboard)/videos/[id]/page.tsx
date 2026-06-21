import Image from "next/image";
import Link from "next/link";
import { notFound } from "next/navigation";
import { toggleKeepOriginal } from "@/app/actions";
import { Badge } from "@/components/badge";
import { EmptyState } from "@/components/empty-state";
import { PlatformBadge } from "@/components/platform-badge";
import { createClient } from "@/lib/supabase/server";
import { formatDate, formatDuration, formatNumber, jobStatusLabel, transcriptLabel } from "@/lib/format";
import type { CrawlJob, Video } from "@/lib/types";

interface CommentRow { id: string; author_name: string | null; content: string; like_count: number | null; published_at: string | null; is_partial_public_sample: boolean; }
interface TranscriptRow { id: string; source: string; status: string; language: string | null; model_name: string | null; raw_text: string | null; cleaned_text: string | null; error_message: string | null; completed_at: string | null; }
interface SegmentRow { id: number; start_seconds: number; end_seconds: number; text: string; }
interface MetricSnapshot { id: number; view_count: number | null; like_count: number | null; comment_count: number | null; captured_at: string; }

export default async function VideoDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const supabase = await createClient();
  const [videoResult, commentsResult, transcriptResult, segmentsResult, metricsResult, jobsResult] = await Promise.all([
    supabase.from("videos").select("*, creators(id, name, platform)").eq("id", id).single(),
    supabase.from("comments").select("*").eq("video_id", id).order("like_count", { ascending: false, nullsFirst: false }).limit(30),
    supabase.from("transcripts").select("*").eq("video_id", id).order("created_at", { ascending: false }).limit(1).maybeSingle(),
    supabase.from("transcript_segments").select("*").eq("video_id", id).order("segment_index").limit(500),
    supabase.from("video_metrics_snapshots").select("*").eq("video_id", id).order("captured_at", { ascending: false }).limit(12),
    supabase.from("crawl_jobs").select("*").eq("video_id", id).order("created_at", { ascending: false }).limit(10)
  ]);
  if (!videoResult.data) notFound();
  const video = videoResult.data as unknown as Video;
  const comments = (commentsResult.data ?? []) as CommentRow[];
  const transcript = transcriptResult.data as TranscriptRow | null;
  const segments = (segmentsResult.data ?? []) as SegmentRow[];
  const jobs = (jobsResult.data ?? []) as CrawlJob[];
  const metricSnapshots = (metricsResult.data ?? []) as MetricSnapshot[];
  const isDouyinPartial = video.platform === "douyin";

  return <>
    <header className="topbar"><div><span className="eyebrow">Video detail</span><h1 className="page-title">视频详情</h1><p className="page-subtitle">元数据、互动快照、评论和字幕集中在一个页面。</p></div><div className="top-actions"><Link className="button button-secondary" href="/videos">← 返回</Link><a className="button button-primary" href={video.video_url} target="_blank" rel="noreferrer">打开原视频 ↗</a></div></header>
    <section className="detail-hero">
      <div style={{ display: "flex", gap: 20, alignItems: "flex-start" }}>
        {video.cover_url && <Image src={video.cover_url} alt="" width={240} height={145} unoptimized style={{ width: 180, height: 108, borderRadius: 10, objectFit: "cover", flex: "0 0 auto" }} />}
        <div><div className="detail-meta"><PlatformBadge platform={video.platform} /><Badge tone={video.transcript_status === "completed" ? "green" : video.transcript_status === "failed" ? "red" : "neutral"}>{transcriptLabel[video.transcript_status]}</Badge></div><h2 className="detail-title">{video.title}</h2><p className="detail-description">{video.description || "暂无视频简介"}</p><div className="cell-subtitle" style={{ marginTop: 10 }}>{video.creators?.name} · {formatDate(video.published_at, true)} · {formatDuration(video.duration_seconds)}</div></div>
      </div>
      <div className="top-actions"><button className="button button-secondary" disabled title="阶段 4 接入本地任务队列">转写（阶段 4）</button><button className="button button-secondary" disabled title="阶段 4 接入本地任务队列">重新转写</button></div>
    </section>
    <section className="metrics-row">
      <div className="metric"><div className="metric-label">播放</div><div className="metric-value">{formatNumber(video.view_count)}</div></div><div className="metric"><div className="metric-label">点赞</div><div className="metric-value">{formatNumber(video.like_count)}</div></div><div className="metric"><div className="metric-label">投币</div><div className="metric-value">{formatNumber(video.coin_count)}</div></div><div className="metric"><div className="metric-label">收藏</div><div className="metric-value">{formatNumber(video.favorite_count)}</div></div><div className="metric"><div className="metric-label">分享</div><div className="metric-value">{formatNumber(video.share_count)}</div></div><div className="metric"><div className="metric-label">评论</div><div className="metric-value">{formatNumber(video.comment_count)}</div></div><div className="metric"><div className="metric-label">弹幕</div><div className="metric-value">{formatNumber(video.danmaku_count)}</div></div><div className="metric"><div className="metric-label">数据快照</div><div className="metric-value">{metricSnapshots.length}</div></div>
    </section>
    <section className="content-grid">
      <div style={{ display: "grid", gap: 18 }}>
        <div className="card"><div className="card-header"><h2 className="card-title">字幕</h2>{transcript && <Badge tone={transcript.status === "completed" ? "green" : transcript.status === "failed" ? "red" : "neutral"}>{transcript.status}</Badge>}</div><div className="card-body">
          {transcript ? <><dl className="definition-list"><dt>来源</dt><dd>{transcript.source}</dd><dt>语言</dt><dd>{transcript.language ?? "—"}</dd><dt>模型</dt><dd>{transcript.model_name ?? "非模型字幕"}</dd><dt>完成时间</dt><dd>{formatDate(transcript.completed_at, true)}</dd>{transcript.error_message && <><dt>错误</dt><dd style={{ color: "var(--red)" }}>{transcript.error_message}</dd></>}</dl>
            <h3 className="card-title section-gap">清洗字幕</h3><p className="detail-description section-gap">{transcript.cleaned_text || "暂无清洗文本"}</p><h3 className="card-title section-gap">原始字幕</h3><p className="detail-description section-gap">{transcript.raw_text || "暂无原始文本"}</p></> : <EmptyState title="暂无字幕" description="阶段 4 将优先读取平台字幕；没有时才在本地临时转写。" />}
        </div></div>
        <div className="card"><div className="card-header"><h2 className="card-title">时间戳字幕</h2><span className="cell-subtitle">{segments.length} 段</span></div><div className="card-body">
          {segments.length ? <div className="timeline">{segments.map((segment) => <div className="timeline-item" key={segment.id}><span className="timeline-dot" /><div className="timeline-title">{segment.text}</div><div className="timeline-meta">{formatDuration(Math.floor(segment.start_seconds))} — {formatDuration(Math.floor(segment.end_seconds))}</div></div>)}</div> : <p className="page-subtitle">暂无时间戳段落。</p>}
        </div></div>
        <div className="card"><div className="card-header"><h2 className="card-title">页面章节</h2><span className="cell-subtitle">{video.chapters_json?.length ?? 0} 章</span></div><div className="card-body">
          {video.chapters_json?.length ? <div className="timeline">{video.chapters_json.map((chapter, index) => <div className="timeline-item" key={`${chapter.start_seconds ?? chapter.timestamp}-${index}`}><span className="timeline-dot" /><div className="timeline-title">{chapter.title || `章节 ${index + 1}`}</div>{chapter.description && <p className="detail-description" style={{ marginTop: 5 }}>{chapter.description}</p>}<div className="timeline-meta">{chapter.timestamp ?? formatDuration(chapter.start_seconds ?? null)}</div></div>)}</div> : <p className="page-subtitle">页面没有公开章节，或尚未采集。</p>}
        </div></div>
        <div className="card"><div className="card-header"><h2 className="card-title">评论</h2><span className="cell-subtitle">{comments.length} 条代表性片段</span></div><div className="card-body">
          {isDouyinPartial && <div className="note" style={{ marginBottom: 18 }}>抖音评论仅来自页面公开可见的少量片段，不是完整评论 API 数据。</div>}
          {comments.length ? <div className="timeline">{comments.map((comment) => <div className="timeline-item" key={comment.id}><span className="timeline-dot" /><div className="timeline-title">{comment.author_name ?? "匿名用户"} · {formatNumber(comment.like_count)} 赞</div><p className="detail-description" style={{ marginTop: 5 }}>{comment.content}</p><div className="timeline-meta">{formatDate(comment.published_at, true)}</div></div>)}</div> : <p className="page-subtitle">暂无评论数据。</p>}
        </div></div>
      </div>
      <aside style={{ display: "grid", gap: 18, alignContent: "start" }}>
        <div className="card"><div className="card-header"><h2 className="card-title">本地文件策略</h2></div><div className="card-body"><p className="page-subtitle">默认在转写成功后删除临时音视频。标记保留后，文件也只存在你的 Mac 或外接硬盘。</p><form action={toggleKeepOriginal.bind(null, id, !video.keep_original_file)} className="section-gap"><button className={`button ${video.keep_original_file ? "button-danger" : "button-secondary"}`} type="submit">{video.keep_original_file ? "取消保留原文件" : "标记保留原文件"}</button></form></div></div>
        <div className="card"><div className="card-header"><h2 className="card-title">内容参考</h2><Badge>本地抽取</Badge></div><div className="card-body"><h3 className="card-title">参考摘要</h3><p className="detail-description section-gap">{video.reference_summary || "暂无。阶段 4 将基于章节或字幕做轻量抽取，不冒充深度 AI 分析。"}</p><h3 className="card-title section-gap">候选关键句</h3>{video.candidate_quotes?.length ? <ul>{video.candidate_quotes.map((quote, i) => <li key={i}>{quote}</li>)}</ul> : <p className="page-subtitle section-gap">暂无候选关键句。</p>}</div></div>
        <div className="card"><div className="card-header"><h2 className="card-title">互动数据快照</h2></div><div className="card-body">{metricSnapshots.length ? <div className="timeline">{metricSnapshots.map((snapshot) => <div className="timeline-item" key={snapshot.id}><span className="timeline-dot" /><div className="timeline-title">{formatNumber(snapshot.view_count)} 播放 · {formatNumber(snapshot.like_count)} 赞 · {formatNumber(snapshot.comment_count)} 评论</div><div className="timeline-meta">{formatDate(snapshot.captured_at, true)}</div></div>)}</div> : <p className="page-subtitle">暂无互动快照。阶段 2 每次采集会追加一条。</p>}</div></div>
        <div className="card"><div className="card-header"><h2 className="card-title">任务日志</h2></div><div className="card-body">{jobs.length ? <div className="timeline">{jobs.map((job) => <div className="timeline-item" key={job.id}><span className="timeline-dot" /><div className="timeline-title">{job.job_type.replaceAll("_", " ")} · {jobStatusLabel[job.status]}</div><div className="timeline-meta">{formatDate(job.created_at, true)} · {job.success_count} 成功 / {job.failed_count} 失败</div></div>)}</div> : <p className="page-subtitle">暂无关联任务。</p>}</div></div>
      </aside>
    </section>
  </>;
}

