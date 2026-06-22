import Link from "next/link";
import { Badge } from "@/components/badge";
import { EmptyState } from "@/components/empty-state";
import { createClient } from "@/lib/supabase/server";
import { formatDate, jobDuration, jobStatusLabel, platformLabel } from "@/lib/format";
import type { CrawlJob, JobStatus, Platform } from "@/lib/types";

type Params = { platform?: Platform; status?: JobStatus; type?: string };
function tone(status: JobStatus) { return status === "succeeded" ? "green" as const : status === "failed" ? "red" as const : status === "running" ? "blue" as const : status === "partially_succeeded" ? "amber" as const : "neutral" as const; }

export default async function JobsPage({ searchParams }: { searchParams: Promise<Params> }) {
  const params = await searchParams;
  const supabase = await createClient();
  let query = supabase.from("crawl_jobs").select("*, creators(name), videos(title)").order("created_at", { ascending: false }).limit(200);
  if (params.platform) query = query.eq("platform", params.platform);
  if (params.status) query = query.eq("status", params.status);
  if (params.type) query = query.eq("job_type", params.type);
  const { data } = await query;
  const jobs = (data ?? []) as unknown as CrawlJob[];

  return <>
    <header className="topbar"><div><span className="eyebrow">Operations</span><h1 className="page-title">任务日志</h1><p className="page-subtitle">采集、评论与转写任务的结果、耗时和错误记录。</p></div></header>
    <form className="filters"><div className="filter-field"><label htmlFor="platform">平台</label><select className="select" id="platform" name="platform" defaultValue={params.platform ?? ""}><option value="">全部平台</option><option value="bilibili">B站</option><option value="douyin">抖音</option><option value="x">X</option></select></div><div className="filter-field"><label htmlFor="type">任务类型</label><select className="select" id="type" name="type" defaultValue={params.type ?? ""}><option value="">全部类型</option><option value="bilibili_crawl">B站采集</option><option value="douyin_crawl">抖音采集</option><option value="x_crawl">X 同步</option><option value="bilibili_comments">B站评论</option><option value="transcribe_video">视频转写</option><option value="full_crawl">全平台运行</option><option value="manual">手工记录</option></select></div><div className="filter-field"><label htmlFor="status">状态</label><select className="select" id="status" name="status" defaultValue={params.status ?? ""}><option value="">全部状态</option><option value="queued">等待中</option><option value="running">运行中</option><option value="succeeded">成功</option><option value="partially_succeeded">部分成功</option><option value="failed">失败</option><option value="cancelled">已取消</option></select></div><button className="button button-secondary" type="submit">筛选</button><Link className="button button-secondary" href="/jobs">清除</Link></form>
    <section className="table-card">{jobs.length ? <div className="table-scroll"><table><thead><tr><th>开始时间</th><th>任务</th><th>平台</th><th>对象</th><th>状态</th><th>耗时</th><th>成功</th><th>更新</th><th>跳过</th><th>失败</th><th>错误 / Manifest</th></tr></thead><tbody>{jobs.map((job) => <tr key={job.id}><td>{formatDate(job.started_at ?? job.created_at, true)}</td><td><div className="cell-title">{job.job_type.replaceAll("_", " ")}</div></td><td>{job.platform ? platformLabel[job.platform] : "全平台"}</td><td>{job.creators?.name ?? job.videos?.title ?? "—"}</td><td><Badge tone={tone(job.status)}>{jobStatusLabel[job.status]}</Badge></td><td>{jobDuration(job.started_at, job.finished_at)}</td><td>{job.success_count}</td><td>{job.updated_count}</td><td>{job.skipped_count}</td><td>{job.failed_count}</td><td><div className="cell-subtitle" title={job.error_summary ?? job.manifest_path ?? ""}>{job.error_summary ?? job.manifest_path ?? "—"}</div></td></tr>)}</tbody></table></div> : <EmptyState title="还没有任务日志" description="后续本地脚本每次运行都会创建 crawl_jobs 记录，并保存本地 manifest 路径。" />}</section>
  </>;
}
