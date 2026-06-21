"use server";

import { revalidatePath } from "next/cache";
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

