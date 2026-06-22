"""Comment, subtitle, transcription, and queued-job pipeline for Creator Signal.

All media work is local. Only structured text, status, and local path metadata are
written to Supabase.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import ssl
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LOCAL_ROOT = ROOT / "local-data"
MANIFEST_ROOT = LOCAL_ROOT / "manifests"
TRANSCRIPT_ROOT = LOCAL_ROOT / "transcripts"
RETAINED_ROOT = LOCAL_ROOT / "retained-media"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(args: list[str], *, timeout: int = 900, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        args,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=os.environ.copy(),
    )
    if check and completed.returncode:
        raise RuntimeError(
            f"Command failed ({completed.returncode}): {' '.join(args[:4])}\n"
            f"{(completed.stderr or completed.stdout)[-2500:]}"
        )
    return completed


def run_ytdlp(arguments: list[str], *, timeout: int, check: bool = True, use_browser: bool = True) -> subprocess.CompletedProcess[str]:
    base = [sys.executable, "-m", "yt_dlp"]
    first = run([*base, *arguments], timeout=timeout, check=False)
    if first.returncode == 0:
        return first
    browser = os.getenv("YTDLP_COOKIES_FROM_BROWSER", "chrome").strip() if use_browser else ""
    if browser:
        second = run([*base, "--cookies-from-browser", browser, *arguments], timeout=timeout, check=False)
        if second.returncode == 0 or not check:
            return second
        raise RuntimeError(f"yt-dlp failed with local browser session:\n{second.stderr[-2500:]}")
    if check:
        raise RuntimeError(f"yt-dlp failed:\n{first.stderr[-2500:]}")
    return first


def write_manifest(job_id: str, kind: str, payload: dict[str, Any], directory: Path = MANIFEST_ROOT) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{kind}-{job_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def video_by_id(db: Any, video_id: str) -> dict[str, Any]:
    rows = db.request(
        "GET",
        "videos?select=*,creators(id,name,platform,platform_creator_id,profile_url,sec_uid)"
        f"&id=eq.{urllib.parse.quote(video_id)}&limit=1",
    )
    if not rows:
        raise RuntimeError(f"Video not found: {video_id}")
    return rows[0]


def create_job(db: Any, video: dict[str, Any], kind: str, options: dict[str, Any]) -> dict[str, Any]:
    rows = db.request(
        "POST",
        "crawl_jobs",
        {
            "platform": video["platform"],
            "creator_id": video["creator_id"],
            "video_id": video["id"],
            "job_type": kind,
            "status": "running",
            "started_at": utc_now(),
            "options_json": options,
        },
        "return=representation",
    )
    return rows[0]


def finish_job(
    db: Any,
    job: dict[str, Any],
    *,
    status: str,
    success: int = 0,
    updated: int = 0,
    skipped: int = 0,
    failed: int = 0,
    error: str | None = None,
    manifest: Path | None = None,
) -> None:
    db.request(
        "PATCH",
        f"crawl_jobs?id=eq.{job['id']}",
        {
            "status": status,
            "finished_at": utc_now(),
            "success_count": success,
            "updated_count": updated,
            "skipped_count": skipped,
            "failed_count": failed,
            "error_summary": error[:4000] if error else None,
            "manifest_path": str(manifest) if manifest else None,
        },
    )


def _comment_row(video_id: str, item: dict[str, Any], *, parent_id: str | None = None) -> dict[str, Any]:
    member = item.get("member") or {}
    published = None
    if item.get("ctime"):
        published = datetime.fromtimestamp(int(item["ctime"]), timezone.utc).isoformat()
    return {
        "video_id": video_id,
        "parent_comment_id": parent_id,
        "platform_comment_id": str(item.get("rpid") or item.get("id")),
        "author_name": member.get("uname") or None,
        "author_platform_id": str(member.get("mid")) if member.get("mid") is not None else None,
        "content": str((item.get("content") or {}).get("message") or "").strip(),
        "like_count": int(item.get("like") or 0),
        "published_at": published,
        "is_reply": parent_id is not None,
        "is_representative": True,
        "is_partial_public_sample": False,
    }


def collect_bilibili_comments(
    db: Any,
    video: dict[str, Any],
    options: dict[str, Any],
    *,
    job: dict[str, Any] | None = None,
    dry_run: bool = False,
    fetch_json: Any,
    fetch_comments: Any | None = None,
) -> dict[str, Any]:
    if video["platform"] != "bilibili":
        raise RuntimeError("Bilibili comment collection requires a Bilibili video")
    limit = max(1, min(int(options.get("limit", 30)), 100))
    include_replies = bool(options.get("include_replies", False))
    delay = max(0.0, float(options.get("delay", 1)))
    active_job = job or (None if dry_run else create_job(db, video, "bilibili_comments", options))
    started = utc_now()
    inserted = updated = skipped = failed = 0
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        detail = fetch_json(
            f"https://api.bilibili.com/x/web-interface/view?bvid={urllib.parse.quote(video['platform_video_id'])}",
            int(options.get("retries", 3)),
        )
        aid = detail.get("aid")
        if not aid:
            raise RuntimeError("Bilibili video did not return an aid")
        if fetch_comments:
            data = fetch_comments(aid, limit, int(options.get("retries", 3)), video["platform_video_id"])
        else:
            endpoint = (
                "https://api.bilibili.com/x/v2/reply/main?"
                + urllib.parse.urlencode({"type": 1, "oid": aid, "mode": 3, "next": 0, "ps": min(limit, 20)})
            )
            data = fetch_json(endpoint, int(options.get("retries", 3)))
        roots = data.get("replies") or []
        candidates: list[tuple[dict[str, Any], dict[str, Any] | None]] = []
        for root in roots:
            candidates.append((root, None))
            if include_replies:
                for reply in root.get("replies") or []:
                    candidates.append((reply, root))
        candidates = candidates[:limit]
        root_ids: dict[str, str] = {}
        for item, parent in candidates:
            row = _comment_row(video["id"], item)
            if not row["platform_comment_id"] or not row["content"]:
                skipped += 1
                continue
            if parent:
                parent_rpid = str(parent.get("rpid"))
                row["parent_comment_id"] = root_ids.get(parent_rpid)
                row["is_reply"] = True
            if dry_run:
                records.append(row)
                inserted += 1
                continue
            existing = db.request(
                "GET",
                "comments?select=id&video_id=eq."
                f"{video['id']}&platform_comment_id=eq.{urllib.parse.quote(row['platform_comment_id'])}&limit=1",
            )
            result = db.request(
                "POST",
                "comments?on_conflict=video_id,platform_comment_id",
                row,
                "resolution=merge-duplicates,return=representation",
            )
            if parent is None:
                root_ids[row["platform_comment_id"]] = result[0]["id"]
            if existing:
                updated += 1
            else:
                inserted += 1
            records.append({"id": result[0]["id"], "platform_comment_id": row["platform_comment_id"]})
            if delay:
                time.sleep(delay)
    except Exception as exc:
        failed = 1
        errors.append(str(exc))
    status = "succeeded" if not failed else ("partially_succeeded" if inserted or updated else "failed")
    payload = {
        "job_id": active_job and active_job["id"],
        "job_type": "bilibili_comments",
        "video_id": video["id"],
        "bvid": video["platform_video_id"],
        "started_at": started,
        "finished_at": utc_now(),
        "status": status,
        "options": options,
        "counts": {"success": inserted, "updated": updated, "skipped": skipped, "failed": failed},
        "errors": errors,
        "records": records,
    }
    manifest = None if dry_run or not active_job else write_manifest(active_job["id"], "bilibili-comments", payload)
    if active_job:
        finish_job(db, active_job, status=status, success=inserted, updated=updated, skipped=skipped, failed=failed, error="\n".join(errors) or None, manifest=manifest)
    return payload


TIME_RE = re.compile(r"(?P<h>\d{1,2}):(?P<m>\d{2}):(?P<s>\d{2})[,.](?P<ms>\d{3})")


def _seconds(value: str) -> float:
    match = TIME_RE.search(value)
    if not match:
        return 0.0
    return int(match["h"]) * 3600 + int(match["m"]) * 60 + int(match["s"]) + int(match["ms"]) / 1000


def parse_srt_vtt(path: Path) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    start = end = None
    text_lines: list[str] = []

    def flush() -> None:
        nonlocal start, end, text_lines
        text = " ".join(text_lines).strip()
        text = re.sub(r"<[^>]+>", "", text)
        if start is not None and end is not None and text:
            segments.append({"start": start, "end": end, "text": text})
        start = end = None
        text_lines = []

    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines() + [""]:
        line = raw.strip().lstrip("\ufeff")
        if "-->" in line:
            flush()
            left, right = line.split("-->", 1)
            start, end = _seconds(left), _seconds(right)
        elif not line:
            flush()
        elif start is not None and not line.isdigit() and line.upper() != "WEBVTT":
            text_lines.append(line)
    return segments


def parse_json_segments(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    result: list[dict[str, Any]] = []
    if isinstance(payload, dict) and isinstance(payload.get("body"), list):
        for item in payload["body"]:
            result.append({
                "start": float(item.get("from") or 0),
                "end": float(item.get("to") or item.get("from") or 0),
                "text": str(item.get("content") or item.get("text") or "").strip(),
            })
    elif isinstance(payload, dict) and isinstance(payload.get("transcription"), list):
        for item in payload["transcription"]:
            offsets = item.get("offsets") or {}
            timestamps = item.get("timestamps") or {}
            start = offsets.get("from", timestamps.get("from", 0))
            end = offsets.get("to", timestamps.get("to", start))
            if isinstance(start, str):
                start = _seconds(start)
            elif float(start or 0) > 1000:
                start = float(start) / 1000
            if isinstance(end, str):
                end = _seconds(end)
            elif float(end or 0) > 1000:
                end = float(end) / 1000
            result.append({"start": float(start or 0), "end": float(end or start or 0), "text": str(item.get("text") or "").strip()})
    elif isinstance(payload, dict) and isinstance(payload.get("segments"), list):
        for item in payload["segments"]:
            result.append({"start": float(item.get("start") or 0), "end": float(item.get("end") or 0), "text": str(item.get("text") or "").strip()})
    return [item for item in result if item["text"]]


JUNK_LINES = {
    "字幕", "谢谢观看", "感谢观看", "本期视频就到这里", "我们下期再见", "下期再见",
    "请点赞投币收藏", "一键三连", "记得点赞关注", "点赞关注不迷路",
}


def clean_segments(segments: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    cleaned: list[dict[str, Any]] = []
    previous = ""
    for segment in segments:
        text = re.sub(r"\s+", " ", str(segment["text"])).strip(" \t-—")
        normalized = re.sub(r"[，。！？,.!?\s]", "", text)
        if not normalized or normalized in JUNK_LINES or len(normalized) <= 1:
            continue
        if normalized == previous:
            continue
        previous = normalized
        cleaned.append({**segment, "text": text})
    return "\n".join(item["text"] for item in cleaned), cleaned


def reference_extract(cleaned_text: str, chapters: list[dict[str, Any]] | None) -> tuple[str | None, list[str]]:
    if chapters:
        chapter_lines = [
            "：".join(part for part in [str(item.get("title") or "").strip(), str(item.get("description") or "").strip()] if part)
            for item in chapters
        ]
        summary = "；".join(line for line in chapter_lines if line)[:800] or None
    else:
        sentences = [part.strip() for part in re.split(r"(?<=[。！？!?])\s*|\n+", cleaned_text) if part.strip()]
        summary = "".join(sentences[:4])[:800] or None
    candidates: list[str] = []
    for sentence in [part.strip() for part in re.split(r"(?<=[。！？!?])\s*|\n+", cleaned_text)]:
        compact = re.sub(r"\s+", "", sentence)
        if 15 <= len(compact) <= 100 and sentence not in candidates:
            candidates.append(sentence)
        if len(candidates) >= 6:
            break
    return summary, candidates


def write_srt(path: Path, segments: list[dict[str, Any]]) -> None:
    def stamp(seconds: float) -> str:
        millis = round(seconds * 1000)
        h, remain = divmod(millis, 3_600_000)
        m, remain = divmod(remain, 60_000)
        s, ms = divmod(remain, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    blocks = [f"{index}\n{stamp(item['start'])} --> {stamp(item['end'])}\n{item['text']}" for index, item in enumerate(segments, 1)]
    path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")


def _download_subtitle(video_url: str, directory: Path, retries: int) -> tuple[Path | None, list[dict[str, Any]]]:
    output = directory / "platform.%(ext)s"
    run_ytdlp([
        "--skip-download", "--write-subs", "--write-auto-subs",
        "--sub-langs", "zh-Hans,zh-CN,zh,zh-TW,en", "--sub-format", "srt/vtt/json3/best",
        "--retries", str(retries), "-o", str(output), video_url,
    ], timeout=120, check=False, use_browser=False)
    candidates = sorted([*directory.glob("platform*.srt"), *directory.glob("platform*.vtt"), *directory.glob("platform*.json*")])
    for candidate in candidates:
        try:
            segments = parse_json_segments(candidate) if candidate.suffix.startswith(".json") else parse_srt_vtt(candidate)
            if sum(len(item["text"]) for item in segments) >= 80:
                return candidate, segments
        except Exception:
            continue
    return None, []


def _whisper_model(model: str) -> Path:
    env_name = "WHISPER_CPP_MODEL_MEDIUM" if model == "medium" else "WHISPER_CPP_MODEL_SMALL"
    configured = os.getenv(env_name)
    if configured:
        return Path(configured).expanduser()
    return Path.home() / "Library" / "Application Support" / "Creator Signal" / "models" / f"ggml-{model}.bin"


def _download_bilibili_audio(video: dict[str, Any], directory: Path, retries: int) -> Path:
    parts = video.get("parts_json") or []
    cid = parts[0].get("cid") if parts else None
    if not cid:
        raise RuntimeError("B站视频缺少 CID，无法读取公开音频流")
    query = urllib.parse.urlencode({"bvid": video["platform_video_id"], "cid": cid, "fnval": 16, "qn": 64, "fourk": 1})
    endpoint = f"https://api.bilibili.com/x/player/playurl?{query}"
    context = ssl.create_default_context()
    try:
        import certifi  # type: ignore
        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126 Safari/537.36",
        "Referer": video["video_url"],
    }
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            request = urllib.request.Request(endpoint, headers=headers)
            with urllib.request.urlopen(request, timeout=30, context=context) as response:
                payload = json.load(response)
            if payload.get("code") != 0:
                raise RuntimeError(f"B站播放地址接口失败：{payload.get('code')} {payload.get('message')}")
            audio_streams = ((payload.get("data") or {}).get("dash") or {}).get("audio") or []
            if not audio_streams:
                raise RuntimeError("B站播放地址没有返回公开音频流")
            stream = max(audio_streams, key=lambda item: int(item.get("bandwidth") or 0))
            urls = [stream.get("baseUrl") or stream.get("base_url"), *(stream.get("backupUrl") or stream.get("backup_url") or [])]
            target = directory / "source.m4s"
            for source_url in [url for url in urls if url]:
                try:
                    media_request = urllib.request.Request(source_url, headers=headers)
                    with urllib.request.urlopen(media_request, timeout=120, context=context) as response, target.open("wb") as handle:
                        shutil.copyfileobj(response, handle, length=1024 * 1024)
                    if target.stat().st_size > 1024:
                        return target
                except Exception as download_error:
                    last_error = download_error
            raise last_error or RuntimeError("B站公开音频流下载失败")
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(min(2 ** attempt, 5))
    raise RuntimeError(str(last_error or "B站公开音频流下载失败"))


def _local_whisper(video: dict[str, Any], directory: Path, model: str, max_duration: int, retries: int) -> tuple[list[dict[str, Any]], Path, Path]:
    duration = int(video.get("duration_seconds") or 0)
    if duration and duration > max_duration:
        raise RuntimeError(f"视频时长 {duration} 秒，超过本地限制 {max_duration} 秒")
    whisper = shutil.which("whisper-cli") or shutil.which("whisper-cpp")
    media_template = directory / "source.%(ext)s"
    if video.get("platform") == "bilibili":
        media_candidates = [_download_bilibili_audio(video, directory, retries)]
        completed = None
    else:
        completed = run_ytdlp([
            "-f", "bestaudio/best", "--no-playlist", "--retries", str(retries),
            "-o", str(media_template), video["video_url"],
        ], timeout=1200)
        media_candidates = [path for path in directory.glob("source.*") if path.is_file()]
    if not media_candidates:
        raise RuntimeError(f"媒体下载完成但没有找到文件：{completed.stdout[-500:] if completed else ''}")
    media = media_candidates[0]
    audio = directory / "audio-16k.wav"
    run(["ffmpeg", "-y", "-i", str(media), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(audio)], timeout=1200)
    if whisper:
        model_path = _whisper_model(model)
        if not model_path.exists():
            raise RuntimeError(f"未找到 {model} 模型：{model_path}。请先运行 scripts/setup_whisper_mac.sh {model}")
        prefix = directory / "whisper"
        run([whisper, "-m", str(model_path), "-f", str(audio), "-l", "auto", "-oj", "-osrt", "-otxt", "-of", str(prefix)], timeout=7200)
        json_path = prefix.with_suffix(".json")
        srt_path = prefix.with_suffix(".srt")
        if json_path.exists():
            segments = parse_json_segments(json_path)
        elif srt_path.exists():
            segments = parse_srt_vtt(srt_path)
        else:
            raise RuntimeError("Whisper 已结束，但没有生成 JSON 或 SRT")
    else:
        try:
            import mlx_whisper  # type: ignore
        except ImportError as exc:
            raise RuntimeError("未找到 whisper-cli 或 MLX Whisper。请先运行 scripts/setup_whisper_mac.sh") from exc
        repo_env = "MLX_WHISPER_MODEL_MEDIUM" if model == "medium" else "MLX_WHISPER_MODEL_SMALL"
        repo = os.getenv(repo_env) or f"mlx-community/whisper-{model}-mlx"
        result = mlx_whisper.transcribe(str(audio), path_or_hf_repo=repo, verbose=False)
        segments = [
            {"start": float(item.get("start") or 0), "end": float(item.get("end") or 0), "text": str(item.get("text") or "").strip()}
            for item in result.get("segments") or []
            if str(item.get("text") or "").strip()
        ]
        if not segments:
            raise RuntimeError("MLX Whisper 已结束，但没有生成字幕段落")
    return segments, media, audio


def _save_file_row(db: Any, video_id: str, kind: str, path: Path, retained: bool = True) -> None:
    db.request(
        "POST",
        "saved_files",
        {
            "video_id": video_id,
            "file_kind": kind,
            "local_path": str(path),
            "file_size_bytes": path.stat().st_size if path.exists() else None,
            "is_retained": retained,
        },
    )


def transcribe_video(
    db: Any,
    video: dict[str, Any],
    options: dict[str, Any],
    *,
    job: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    force = bool(options.get("force", False))
    model = str(options.get("model") or "small")
    retries = int(options.get("retries", 3))
    max_duration = int(options.get("max_duration", 7200))
    if model not in {"small", "medium"}:
        raise RuntimeError("model 只支持 small 或 medium")
    active_job = job or (None if dry_run else create_job(db, video, "transcribe_video", options))
    if video.get("transcript_status") == "completed" and not force:
        if active_job:
            manifest = write_manifest(active_job["id"], "transcribe", {"status": "succeeded", "skipped": "already completed"})
            finish_job(db, active_job, status="succeeded", skipped=1, manifest=manifest)
        return {"status": "succeeded", "counts": {"skipped": 1}}
    if dry_run:
        return {"status": "dry_run", "video_id": video["id"], "model": model}

    started = utc_now()
    job_id = active_job["id"]
    temp_parent = LOCAL_ROOT / "tmp"
    temp_parent.mkdir(parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp(prefix=f"transcribe-{video['id'][:8]}-", dir=temp_parent))
    artifact_dir = TRANSCRIPT_ROOT / video["platform"] / video["id"] / datetime.now().strftime("%Y%m%d-%H%M%S")
    artifact_dir.mkdir(parents=True, exist_ok=True)
    source = "platform_subtitle"
    media: Path | None = None
    audio: Path | None = None
    transcript_id: str | None = None
    try:
        db.request("PATCH", f"videos?id=eq.{video['id']}", {"transcript_status": "processing"})
        rows = db.request(
            "POST",
            "transcripts",
            {
                "video_id": video["id"], "source": "platform_subtitle", "status": "processing",
                "model_name": None, "started_at": started,
            },
            "return=representation",
        )
        transcript_id = rows[0]["id"]
        subtitle_path, segments = _download_subtitle(video["video_url"], workdir, retries)
        if not segments:
            source = "whisper_cpp"
            segments, media, audio = _local_whisper(video, workdir, model, max_duration, retries)
        raw_text = "\n".join(item["text"] for item in segments)
        cleaned_text, cleaned_segments = clean_segments(segments)
        if not cleaned_text:
            raise RuntimeError("字幕或转录结果为空")
        summary, quotes = reference_extract(cleaned_text, video.get("chapters_json") or [])
        txt_path = artifact_dir / "transcript.txt"
        srt_path = artifact_dir / "transcript.srt"
        json_path = artifact_dir / "transcript.json"
        txt_path.write_text(cleaned_text + "\n", encoding="utf-8")
        write_srt(srt_path, cleaned_segments)
        json_path.write_text(json.dumps({"source": source, "language": "auto", "segments": cleaned_segments}, ensure_ascii=False, indent=2), encoding="utf-8")
        db.request(
            "PATCH",
            f"transcripts?id=eq.{transcript_id}",
            {
                "source": source, "status": "completed", "language": "auto",
                "model_name": (f"mlx/whisper-{model}" if source == "whisper_cpp" and not (shutil.which("whisper-cli") or shutil.which("whisper-cpp")) else model) if source == "whisper_cpp" else None,
                "raw_text": raw_text, "cleaned_text": cleaned_text, "segments_json": cleaned_segments,
                "txt_local_path": str(txt_path), "subtitle_local_path": str(srt_path), "json_local_path": str(json_path),
                "completed_at": utc_now(), "error_message": None,
            },
        )
        db.request("DELETE", f"transcript_segments?transcript_id=eq.{transcript_id}")
        rows_to_insert = [
            {
                "transcript_id": transcript_id, "video_id": video["id"], "segment_index": index,
                "start_seconds": item["start"], "end_seconds": max(item["end"], item["start"]), "text": item["text"],
            }
            for index, item in enumerate(cleaned_segments)
        ]
        for offset in range(0, len(rows_to_insert), 200):
            db.request("POST", "transcript_segments", rows_to_insert[offset:offset + 200])
        db.request(
            "PATCH",
            f"videos?id=eq.{video['id']}",
            {"transcript_status": "completed", "reference_summary": summary, "candidate_quotes": quotes},
        )
        for kind, path in [("txt", txt_path), ("srt", srt_path), ("json", json_path)]:
            _save_file_row(db, video["id"], kind, path)
        retained: list[str] = []
        if video.get("keep_original_file") and media:
            RETAINED_ROOT.mkdir(parents=True, exist_ok=True)
            target = RETAINED_ROOT / f"{video['platform_video_id']}{media.suffix}"
            shutil.move(str(media), target)
            _save_file_row(db, video["id"], "video", target)
            retained.append(str(target))
        manifest_payload = {
            "job_id": job_id, "job_type": "transcribe_video", "video_id": video["id"],
            "source": source, "model": model if source == "whisper_cpp" else None,
            "started_at": started, "finished_at": utc_now(), "status": "succeeded",
            "segments": len(cleaned_segments), "artifacts": [str(txt_path), str(srt_path), str(json_path)],
            "retained_media": retained,
        }
        manifest = write_manifest(job_id, "transcribe", manifest_payload)
        finish_job(db, active_job, status="succeeded", success=1, manifest=manifest)
        return manifest_payload
    except Exception as exc:
        if transcript_id:
            db.request(
                "PATCH", f"transcripts?id=eq.{transcript_id}",
                {"status": "failed", "completed_at": utc_now(), "error_message": str(exc)[:4000]},
            )
        db.request("PATCH", f"videos?id=eq.{video['id']}", {"transcript_status": "failed"})
        payload = {"job_id": job_id, "job_type": "transcribe_video", "video_id": video["id"], "status": "failed", "error": str(exc)}
        manifest = write_manifest(job_id, "transcribe", payload)
        finish_job(db, active_job, status="failed", failed=1, error=str(exc), manifest=manifest)
        return payload
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def process_queued_jobs(db: Any, *, limit: int, fetch_json: Any, fetch_comments: Any | None = None) -> dict[str, int]:
    jobs = db.request(
        "GET",
        f"crawl_jobs?select=*&status=eq.queued&job_type=in.(bilibili_comments,transcribe_video)&order=created_at.asc&limit={max(1, limit)}",
    ) or []
    counts = {"processed": 0, "succeeded": 0, "failed": 0}
    for job in jobs:
        db.request("PATCH", f"crawl_jobs?id=eq.{job['id']}&status=eq.queued", {"status": "running", "started_at": utc_now()})
        job["status"] = "running"
        job["started_at"] = utc_now()
        try:
            video = video_by_id(db, job["video_id"])
            if job["job_type"] == "bilibili_comments":
                result = collect_bilibili_comments(db, video, job.get("options_json") or {}, job=job, fetch_json=fetch_json, fetch_comments=fetch_comments)
            elif job["job_type"] == "transcribe_video":
                result = transcribe_video(db, video, job.get("options_json") or {}, job=job)
            else:
                raise RuntimeError(f"本地执行器暂不支持任务类型：{job['job_type']}")
            counts["processed"] += 1
            counts["succeeded" if result.get("status") in {"succeeded", "partially_succeeded"} else "failed"] += 1
        except Exception as exc:
            finish_job(db, job, status="failed", failed=1, error=str(exc))
            counts["processed"] += 1
            counts["failed"] += 1
    return counts
