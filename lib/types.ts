export type Platform = "bilibili" | "douyin";
export type TranscriptStatus = "pending" | "processing" | "completed" | "failed" | "skipped";
export type JobStatus = "queued" | "running" | "succeeded" | "partially_succeeded" | "failed" | "cancelled";

export interface Creator {
  id: string; name: string; platform: Platform; profile_url: string; platform_creator_id: string;
  sec_uid: string | null; category: string | null; is_tracked: boolean; follower_count: number | null;
  total_likes_count: number | null; last_crawled_at: string | null; created_at: string; updated_at: string;
}

export interface Video {
  id: string; creator_id: string; platform: Platform; platform_video_id: string; title: string; video_url: string;
  cover_url: string | null; description: string | null; published_at: string | null; duration_seconds: number | null;
  parts_json: Array<{ title?: string; duration_seconds?: number; page?: number }>;
  chapters_json: Array<{ timestamp?: string; start_seconds?: number; title?: string; description?: string }>;
  view_count: number | null; like_count: number | null; coin_count: number | null; favorite_count: number | null;
  share_count: number | null; comment_count: number | null; danmaku_count: number | null;
  transcript_status: TranscriptStatus; keep_original_file: boolean; reference_summary: string | null;
  candidate_quotes: string[]; last_crawled_at: string | null; created_at: string;
  creators?: Pick<Creator, "id" | "name" | "platform"> | null;
}

export interface CrawlJob {
  id: string; platform: Platform | null; job_type: string; status: JobStatus; started_at: string | null;
  finished_at: string | null; success_count: number; updated_count: number; skipped_count: number; failed_count: number;
  error_summary: string | null; manifest_path: string | null; created_at: string;
  creators?: { name: string } | null; videos?: { title: string } | null;
}
