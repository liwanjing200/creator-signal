import Link from "next/link";
import { Badge } from "@/components/badge";
import { EmptyState } from "@/components/empty-state";
import { createClient } from "@/lib/supabase/server";
import { formatDate, jobDuration, jobStatusLabel, platformLabel } from "@/lib/format";
import type { CrawlJob } from "@/lib/types";

function chinaDayStart() {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
  return new Date(`${parts}T00:00:00+08:00`).toISOString();
}

function jobTone(status: CrawlJob["status"]) {
  if (status === "succeeded") return "green" as const;
  if (status === "failed") return "red" as const;
  if (status === "running") return "blue" as const;
  if (status === "partially_succeeded") return "amber" as const;
  return "neutral" as const;
}

export default async function DashboardPage() {
  const supabase = await createClient();
  const today = chinaDayStart();
  const [creators, newVideos, pending, completed, failed, jobs] = await Promise.all([
    supabase.from("creators").select("id", { count: "exact", head: true }).eq("is_tracked", true),
    supabase.from("videos").select("id", { count: "exact", head: true }).gte("created_at", today),
    supabase.from("videos").select("id", { count: "exact", head: true }).eq("transcript_status", "pending"),
    supabase.from("videos").select("id", { count: "exact", head: true }).eq("transcript_status", "completed"),
    supabase.from("crawl_jobs").select("id", { count: "exact", head: true }).eq("status", "failed"),
    supabase.from("crawl_jobs").select("*, creators(name), videos(title)").order("created_at", { ascending: false }).limit(6)
  ]);
  const recentJobs = (jobs.data ?? []) as unknown as CrawlJob[];

  return <>
    <header className="topbar">
      <div><span className="eyebrow">Overview</span><h1 className="page-title">内容情报仪表盘</h1><p className="page-subtitle">你关注的创作者、最新内容与本地任务，一眼看清。</p></div>
      <div className="top-actions"><Link className="button button-secondary" href="/videos">查看视频</Link><Link className="button button-primary" href="/creators">＋ 添加博主</Link></div>
    </header>

    <section className="stats-grid">
      <div className="stat-card"><div className="stat-label">追踪博主</div><div className="stat-value">{creators.count ?? 0}</div><div className="stat-note">当前启用的创作者</div></div>
      <div className="stat-card"><div className="stat-label">今日新增视频</div><div className="stat-value">{newVideos.count ?? 0}</div><div className="stat-note">按北京时间统计</div></div>
      <div className="stat-card"><div className="stat-label">待转写</div><div className="stat-value">{pending.count ?? 0}</div><div className="stat-note">等待本地 Mac 处理</div></div>
      <div className="stat-card"><div className="stat-label">已完成转写</div><div className="stat-value">{completed.count ?? 0}</div><div className="stat-note">字幕已安全写入</div></div>
    </section>

    <section className="content-grid">
      <div className="card">
        <div className="card-header"><h2 className="card-title">最近任务</h2><Link className="card-link" href="/jobs">全部任务 →</Link></div>
        {recentJobs.length ? <div className="table-scroll"><table><thead><tr><th>任务</th><th>平台</th><th>状态</th><th>结果</th><th>耗时</th></tr></thead><tbody>
          {recentJobs.map((job) => <tr key={job.id}>
            <td><div className="cell-title">{job.job_type.replaceAll("_", " ")}</div><div className="cell-subtitle">{job.creators?.name ?? job.videos?.title ?? formatDate(job.created_at, true)}</div></td>
            <td>{job.platform ? platformLabel[job.platform] : "全平台"}</td>
            <td><Badge tone={jobTone(job.status)}>{jobStatusLabel[job.status]}</Badge></td>
            <td>{job.success_count} 成功 · {job.failed_count} 失败</td>
            <td>{jobDuration(job.started_at, job.finished_at)}</td>
          </tr>)}
        </tbody></table></div> : <EmptyState title="还没有任务记录" description="阶段 2 的采集脚本会自动把每次运行写到这里。" />}
      </div>
      <div className="card">
        <div className="card-header"><h2 className="card-title">系统状态</h2><Badge tone="green">私有</Badge></div>
        <div className="card-body">
          <dl className="definition-list">
            <dt>数据访问</dt><dd>Supabase Auth + RLS</dd>
            <dt>前端密钥</dt><dd>仅 anon key</dd>
            <dt>本地媒体</dt><dd>默认临时处理</dd>
            <dt>失败任务</dt><dd><strong style={{ color: (failed.count ?? 0) > 0 ? "var(--red)" : "inherit" }}>{failed.count ?? 0}</strong> 条</dd>
          </dl>
          <div className="note section-gap">阶段 1 只处理结构化数据。不会下载视频，也不会启动任何自动采集。</div>
        </div>
      </div>
    </section>
  </>;
}

