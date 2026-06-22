"use server";

import { revalidatePath } from "next/cache";
import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { formNumber, formShanghaiDateTime, formText } from "@/lib/format";
import type { Platform, TranscriptStatus } from "@/lib/types";

function destination(path: string, kind: "success" | "error", message: string) {
  return `${path}?${kind}=${encodeURIComponent(message)}`;
}

export async function login(formData: FormData) {
  const supabase = await createClient();
  const email = String(formData.get("email") ?? "").trim();
  const password = String(formData.get("password") ?? "");
  const { error } = await supabase.auth.signInWithPassword({ email, password });
  if (error) redirect(destination("/login", "error", "邮箱或密码不正确"));
  redirect("/");
}

export async function requestPasswordReset(formData: FormData) {
  const supabase = await createClient();
  const email = String(formData.get("email") ?? "").trim();
  const headerStore = await headers();
  const origin = headerStore.get("origin") ?? `https://${headerStore.get("host")}`;
  const { error } = await supabase.auth.resetPasswordForEmail(email, {
    redirectTo: `${origin}/auth/callback?next=/reset-password`
  });
  if (error) redirect(destination("/forgot-password", "error", "暂时无法发送重置邮件，请稍后再试"));
  redirect(destination("/login", "success", "重置邮件已发送，请查看邮箱"));
}

export async function updatePassword(formData: FormData) {
  const password = String(formData.get("password") ?? "");
  const confirmation = String(formData.get("password_confirmation") ?? "");
  if (password.length < 8) redirect(destination("/reset-password", "error", "密码至少需要 8 位"));
  if (password !== confirmation) redirect(destination("/reset-password", "error", "两次输入的密码不一致"));

  const supabase = await createClient();
  const { error } = await supabase.auth.updateUser({ password });
  if (error) redirect(destination("/reset-password", "error", "密码更新失败，请重新发送重置邮件"));
  await supabase.auth.signOut();
  redirect(destination("/login", "success", "密码已更新，请使用新密码登录"));
}

export async function logout() {
  const supabase = await createClient();
  await supabase.auth.signOut();
  redirect("/login");
}

export async function createCreator(formData: FormData) {
  const supabase = await createClient();
  const platform = String(formData.get("platform")) as Platform;
  const payload = {
    name: String(formData.get("name") ?? "").trim(),
    platform,
    profile_url: String(formData.get("profile_url") ?? "").trim(),
    platform_creator_id: String(formData.get("platform_creator_id") ?? "").trim(),
    sec_uid: platform === "douyin" ? formText(formData.get("sec_uid")) : null,
    category: formText(formData.get("category")),
    is_tracked: formData.get("is_tracked") === "on",
    follower_count: formNumber(formData.get("follower_count")),
    total_likes_count: formNumber(formData.get("total_likes_count"))
  };
  const { error } = await supabase.from("creators").insert(payload);
  if (error) redirect(destination("/creators", "error", error.code === "23505" ? "这个平台 ID 已存在" : error.message));
  revalidatePath("/creators");
  redirect(destination("/creators", "success", "博主已添加"));
}

export async function updateCreator(id: string, formData: FormData) {
  const supabase = await createClient();
  const platform = String(formData.get("platform")) as Platform;
  const { error } = await supabase.from("creators").update({
    name: String(formData.get("name") ?? "").trim(),
    platform,
    profile_url: String(formData.get("profile_url") ?? "").trim(),
    platform_creator_id: String(formData.get("platform_creator_id") ?? "").trim(),
    sec_uid: platform === "douyin" ? formText(formData.get("sec_uid")) : null,
    category: formText(formData.get("category")),
    is_tracked: formData.get("is_tracked") === "on",
    follower_count: formNumber(formData.get("follower_count")),
    total_likes_count: formNumber(formData.get("total_likes_count"))
  }).eq("id", id);
  if (error) redirect(destination(`/creators/${id}/edit`, "error", error.message));
  revalidatePath("/creators");
  revalidatePath(`/creators/${id}`);
  redirect(destination(`/creators/${id}`, "success", "博主信息已更新"));
}

export async function toggleCreator(id: string, nextState: boolean) {
  const supabase = await createClient();
  await supabase.from("creators").update({ is_tracked: nextState }).eq("id", id);
  revalidatePath("/creators");
  revalidatePath(`/creators/${id}`);
}

export async function createVideo(formData: FormData) {
  const supabase = await createClient();
  const creatorId = String(formData.get("creator_id") ?? "");
  const { data: creator } = await supabase.from("creators").select("platform").eq("id", creatorId).single();
  if (!creator) redirect(destination("/videos", "error", "请选择有效博主"));
  const payload = {
    creator_id: creatorId,
    platform: creator.platform,
    platform_video_id: String(formData.get("platform_video_id") ?? "").trim(),
    title: String(formData.get("title") ?? "").trim(),
    video_url: String(formData.get("video_url") ?? "").trim(),
    cover_url: formText(formData.get("cover_url")),
    description: formText(formData.get("description")),
    published_at: formShanghaiDateTime(formData.get("published_at")),
    duration_seconds: formNumber(formData.get("duration_seconds")),
    view_count: formNumber(formData.get("view_count")),
    like_count: formNumber(formData.get("like_count")),
    comment_count: formNumber(formData.get("comment_count")),
    transcript_status: String(formData.get("transcript_status") ?? "pending") as TranscriptStatus,
    last_crawled_at: new Date().toISOString()
  };
  const { error } = await supabase.from("videos").insert(payload);
  if (error) redirect(destination("/videos", "error", error.code === "23505" ? "这个视频已经存在" : error.message));
  revalidatePath("/videos");
  redirect(destination("/videos", "success", "测试视频已添加"));
}

export async function toggleKeepOriginal(videoId: string, nextState: boolean) {
  const supabase = await createClient();
  await supabase.from("videos").update({ keep_original_file: nextState }).eq("id", videoId);
  revalidatePath(`/videos/${videoId}`);
}

async function queueVideoJob(
  videoId: string,
  jobType: "bilibili_comments" | "transcribe_video",
  options: Record<string, unknown> = {}
) {
  const supabase = await createClient();
  const { data: video } = await supabase
    .from("videos")
    .select("id, creator_id, platform")
    .eq("id", videoId)
    .single();
  if (!video) redirect(destination(`/videos/${videoId}`, "error", "找不到这个视频"));
  if (jobType === "bilibili_comments" && video.platform !== "bilibili") {
    redirect(destination(`/videos/${videoId}`, "error", "这个按钮只用于 B站评论"));
  }
  const { data: existing } = await supabase
    .from("crawl_jobs")
    .select("id")
    .eq("video_id", videoId)
    .eq("job_type", jobType)
    .in("status", ["queued", "running"])
    .limit(1)
    .maybeSingle();
  if (existing) redirect(destination(`/videos/${videoId}`, "success", "任务已经在等待或运行中"));
  const { error } = await supabase.from("crawl_jobs").insert({
    platform: video.platform,
    creator_id: video.creator_id,
    video_id: video.id,
    job_type: jobType,
    status: "queued",
    options_json: options
  });
  if (error) redirect(destination(`/videos/${videoId}`, "error", error.message));
  if (jobType === "transcribe_video") {
    await supabase.from("videos").update({ transcript_status: "pending" }).eq("id", videoId);
  }
  revalidatePath(`/videos/${videoId}`);
  revalidatePath("/jobs");
  redirect(destination(`/videos/${videoId}`, "success", "任务已加入队列，请保持 Mac 本地任务执行器运行"));
}

export async function queueComments(videoId: string) {
  return queueVideoJob(videoId, "bilibili_comments", { limit: 30, include_replies: false, delay: 1 });
}

export async function queueTranscription(videoId: string, force = false, model = "small") {
  return queueVideoJob(videoId, "transcribe_video", { force, model });
}

const creatorJobType = { bilibili: "bilibili_crawl", douyin: "douyin_crawl", x: "x_crawl" } as const;

export async function queueCreatorUpdate(creatorId: string) {
  const supabase = await createClient();
  const { data: creator } = await supabase.from("creators").select("id, platform").eq("id", creatorId).single();
  if (!creator) redirect(destination(`/creators/${creatorId}`, "error", "找不到这个博主"));
  const jobType = creatorJobType[creator.platform as Platform];
  const { data: existing } = await supabase.from("crawl_jobs").select("id").eq("creator_id", creatorId)
    .eq("job_type", jobType).in("status", ["queued", "running"]).limit(1).maybeSingle();
  if (!existing) {
    const { error } = await supabase.from("crawl_jobs").insert({
      platform: creator.platform, creator_id: creatorId, job_type: jobType, status: "queued",
      options_json: { max_videos: 3, retries: 3, force: false }
    });
    if (error) redirect(destination(`/creators/${creatorId}`, "error", error.message));
  }
  revalidatePath(`/creators/${creatorId}`); revalidatePath("/jobs"); revalidatePath("/");
  redirect(destination(`/creators/${creatorId}`, "success", existing ? "更新任务已在等待或运行中" : "已加入更新队列，Mac 后台会自动处理"));
}

export async function queueAllCreatorUpdates() {
  const supabase = await createClient();
  const { data: creators } = await supabase.from("creators").select("id, platform").eq("is_tracked", true);
  for (const creator of creators ?? []) {
    const jobType = creatorJobType[creator.platform as Platform];
    const { data: existing } = await supabase.from("crawl_jobs").select("id").eq("creator_id", creator.id)
      .eq("job_type", jobType).in("status", ["queued", "running"]).limit(1).maybeSingle();
    if (!existing) await supabase.from("crawl_jobs").insert({
      platform: creator.platform, creator_id: creator.id, job_type: jobType, status: "queued",
      options_json: { max_videos: 3, retries: 3, force: false }
    });
  }
  revalidatePath("/"); revalidatePath("/jobs");
  redirect(destination("/", "success", "全部追踪博主已加入更新队列"));
}
