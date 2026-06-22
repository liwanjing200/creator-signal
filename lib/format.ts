export const platformLabel = { bilibili: "B站", douyin: "抖音", x: "X" } as const;

export const transcriptLabel = {
  pending: "待转写",
  processing: "转写中",
  completed: "已完成",
  failed: "失败",
  skipped: "已跳过"
} as const;

export const jobStatusLabel = {
  queued: "等待中",
  running: "运行中",
  succeeded: "成功",
  partially_succeeded: "部分成功",
  failed: "失败",
  cancelled: "已取消"
} as const;

export function formatNumber(value: number | null | undefined) {
  if (value == null) return "—";
  return new Intl.NumberFormat("zh-CN", { notation: value >= 10000 ? "compact" : "standard", maximumFractionDigits: 1 }).format(value);
}

export function formatDate(value: string | null | undefined, withTime = false) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric", month: "short", day: "numeric",
    ...(withTime ? { hour: "2-digit", minute: "2-digit" } : {})
  }).format(new Date(value));
}

export function formatDuration(seconds: number | null | undefined) {
  if (seconds == null) return "—";
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = seconds % 60;
  return [hours, minutes, secs]
    .filter((_, index) => hours > 0 || index > 0)
    .map((part) => String(part).padStart(2, "0"))
    .join(":");
}

export function jobDuration(start: string | null, end: string | null) {
  if (!start) return "—";
  const seconds = Math.max(0, Math.round(((end ? new Date(end) : new Date()).getTime() - new Date(start).getTime()) / 1000));
  return seconds < 60 ? `${seconds} 秒` : `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`;
}

export function formNumber(value: FormDataEntryValue | null) {
  if (typeof value !== "string" || value.trim() === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
}

export function formText(value: FormDataEntryValue | null) {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

export function formShanghaiDateTime(value: FormDataEntryValue | null) {
  const text = formText(value);
  if (!text) return null;
  const date = new Date(`${text}:00+08:00`);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}
