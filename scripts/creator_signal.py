#!/usr/bin/env python3
"""Local Creator Signal ingestion and queued-task CLI."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pipeline


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST_DIR = ROOT / "local-data" / "manifests"

try:
    import certifi  # type: ignore

    TLS_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    TLS_CONTEXT = ssl.create_default_context()

MIXIN_KEY_ORDER = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass
class Counters:
    success: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0


class SupabaseRest:
    def __init__(self, base_url: str, service_role_key: str, retries: int = 3):
        self.base_url = base_url.rstrip("/")
        self.key = service_role_key
        self.retries = retries

    def request(
        self,
        method: str,
        path: str,
        payload: Any | None = None,
        prefer: str | None = None,
    ) -> Any:
        url = f"{self.base_url}/rest/v1/{path.lstrip('/')}"
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        for attempt in range(self.retries + 1):
            try:
                request = urllib.request.Request(url, data=body, headers=headers, method=method)
                with urllib.request.urlopen(request, timeout=30, context=TLS_CONTEXT) as response:
                    raw = response.read()
                    return json.loads(raw) if raw else None
            except (urllib.error.URLError, urllib.error.HTTPError) as exc:
                if attempt >= self.retries:
                    detail = exc.read().decode("utf-8", "replace") if isinstance(exc, urllib.error.HTTPError) else str(exc)
                    raise RuntimeError(f"Supabase {method} {path} failed: {detail}") from exc
                time.sleep(min(2**attempt, 5))
        raise AssertionError("unreachable")

    def tracked_creators(self, platform: str, limit: int | None, creator_id: str | None = None) -> list[dict[str, Any]]:
        query = (
            "creators?select=id,name,platform,profile_url,platform_creator_id"
            f"&platform=eq.{platform}&is_tracked=eq.true&order=created_at.asc"
        )
        if creator_id:
            query += f"&id=eq.{urllib.parse.quote(creator_id)}"
        if limit:
            query += f"&limit={limit}"
        return self.request("GET", query) or []


def open_db(retries: int) -> SupabaseRest:
    load_dotenv(ROOT / ".env.local")
    load_dotenv(ROOT / ".env")
    url = os.getenv("NEXT_PUBLIC_SUPABASE_URL") or os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise SystemExit("Missing NEXT_PUBLIC_SUPABASE_URL/SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
    return SupabaseRest(url, key, retries=retries)


def fetch_json(url: str, retries: int) -> dict[str, Any]:
    headers = {"User-Agent": "Mozilla/5.0 CreatorSignal/0.1"}
    for attempt in range(retries + 1):
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=30, context=TLS_CONTEXT) as response:
                payload = json.load(response)
            if payload.get("code") != 0:
                raise RuntimeError(f"Bilibili returned code {payload.get('code')}: {payload.get('message')}")
            return payload["data"]
        except (urllib.error.URLError, urllib.error.HTTPError, RuntimeError) as exc:
            if attempt >= retries:
                raise
            time.sleep(min(2**attempt, 5))
    raise AssertionError("unreachable")


def public_json(url: str, retries: int, referer: str = "https://www.bilibili.com/") -> dict[str, Any]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126 Safari/537.36",
        "Referer": referer,
    }
    for attempt in range(retries + 1):
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=30, context=TLS_CONTEXT) as response:
                return json.load(response)
        except (urllib.error.URLError, urllib.error.HTTPError) as exc:
            if attempt >= retries:
                raise
            time.sleep(min(2**attempt, 5))
    raise AssertionError("unreachable")


def recent_bvids_wbi(mid: str, max_videos: int, retries: int) -> list[str]:
    nav = public_json("https://api.bilibili.com/x/web-interface/nav", retries)
    wbi = (nav.get("data") or {}).get("wbi_img")
    if not wbi:
        raise RuntimeError(f"Bilibili nav did not return WBI keys: {nav.get('message')}")
    img_key = Path(urllib.parse.urlparse(wbi["img_url"]).path).stem
    sub_key = Path(urllib.parse.urlparse(wbi["sub_url"]).path).stem
    source = img_key + sub_key
    mixin_key = "".join(source[index] for index in MIXIN_KEY_ORDER)[:32]
    params: dict[str, Any] = {
        "mid": mid,
        "pn": 1,
        "ps": max_videos,
        "order": "pubdate",
        "platform": "web",
        "web_location": 1550101,
        "wts": int(time.time()),
    }
    params = {
        key: "".join(character for character in str(value) if character not in "!'()*")
        for key, value in params.items()
    }
    query = urllib.parse.urlencode(sorted(params.items()))
    signature = hashlib.md5((query + mixin_key).encode("utf-8")).hexdigest()
    url = f"https://api.bilibili.com/x/space/wbi/arc/search?{query}&w_rid={signature}"
    payload = public_json(url, retries, referer=f"https://space.bilibili.com/{mid}/video")
    if payload.get("code") != 0:
        raise RuntimeError(f"Bilibili WBI search failed: {payload.get('code')} {payload.get('message')}")
    return [item["bvid"] for item in payload.get("data", {}).get("list", {}).get("vlist", []) if item.get("bvid")]


def wbi_signed_data(path: str, params: dict[str, Any], retries: int, referer: str) -> dict[str, Any]:
    nav = public_json("https://api.bilibili.com/x/web-interface/nav", retries, referer=referer)
    wbi = (nav.get("data") or {}).get("wbi_img")
    if not wbi:
        raise RuntimeError(f"Bilibili nav did not return WBI keys: {nav.get('message')}")
    source = Path(urllib.parse.urlparse(wbi["img_url"]).path).stem + Path(urllib.parse.urlparse(wbi["sub_url"]).path).stem
    mixin_key = "".join(source[index] for index in MIXIN_KEY_ORDER)[:32]
    signed = {**params, "wts": int(time.time())}
    signed = {key: "".join(character for character in str(value) if character not in "!'()*") for key, value in signed.items()}
    query = urllib.parse.urlencode(sorted(signed.items()))
    signature = hashlib.md5((query + mixin_key).encode("utf-8")).hexdigest()
    payload = public_json(f"https://api.bilibili.com{path}?{query}&w_rid={signature}", retries, referer=referer)
    if payload.get("code") != 0:
        raise RuntimeError(f"Bilibili WBI request failed: {payload.get('code')} {payload.get('message')}")
    return payload.get("data") or {}


def fetch_bilibili_comments(aid: int, limit: int, retries: int, bvid: str) -> dict[str, Any]:
    return wbi_signed_data(
        "/x/v2/reply/wbi/main",
        {"oid": aid, "type": 1, "mode": 3, "ps": min(limit, 20), "next": 0},
        retries,
        f"https://www.bilibili.com/video/{bvid}",
    )


def recent_bvids(profile_url: str, creator_mid: str, max_videos: int, retries: int) -> list[str]:
    url = profile_url.rstrip("/")
    if not url.endswith("/video"):
        url += "/video"
    command = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--flat-playlist",
        "--playlist-end",
        str(max_videos),
        "--extractor-retries",
        str(retries),
        "--dump-single-json",
        "--no-warnings",
        url,
    ]
    environment = os.environ.copy()
    try:
        import certifi  # type: ignore

        environment.setdefault("SSL_CERT_FILE", certifi.where())
    except ImportError:
        pass
    completed = subprocess.run(command, capture_output=True, text=True, env=environment, timeout=120)
    if completed.returncode == 0:
        playlist = json.loads(completed.stdout)
        bvids = [entry["id"] for entry in playlist.get("entries", []) if entry and entry.get("id", "").startswith("BV")]
        if bvids:
            return bvids
    return recent_bvids_wbi(creator_mid, max_videos, retries)


def video_payload(creator_id: str, detail: dict[str, Any], crawled_at: str) -> dict[str, Any]:
    stat = detail.get("stat") or {}
    pages = [
        {
            "cid": page.get("cid"),
            "page": page.get("page"),
            "title": page.get("part"),
            "duration_seconds": page.get("duration"),
        }
        for page in detail.get("pages") or []
    ]
    published_at = datetime.fromtimestamp(detail["pubdate"], tz=timezone.utc).isoformat() if detail.get("pubdate") else None
    cover = detail.get("pic")
    if isinstance(cover, str) and cover.startswith("http://"):
        cover = "https://" + cover.removeprefix("http://")
    return {
        "creator_id": creator_id,
        "platform": "bilibili",
        "platform_video_id": detail["bvid"],
        "title": detail.get("title") or detail["bvid"],
        "video_url": f"https://www.bilibili.com/video/{detail['bvid']}",
        "cover_url": cover,
        "description": detail.get("desc") or None,
        "published_at": published_at,
        "duration_seconds": detail.get("duration"),
        "parts_json": pages,
        "view_count": stat.get("view"),
        "like_count": stat.get("like"),
        "coin_count": stat.get("coin"),
        "favorite_count": stat.get("favorite"),
        "share_count": stat.get("share"),
        "comment_count": stat.get("reply"),
        "danmaku_count": stat.get("danmaku"),
        "last_crawled_at": crawled_at,
    }


def bilibili_chapters(detail: dict[str, Any], retries: int) -> list[dict[str, Any]]:
    pages = detail.get("pages") or []
    if not pages or not pages[0].get("cid"):
        return []
    url = "https://api.bilibili.com/x/player/v2?" + urllib.parse.urlencode({"bvid": detail["bvid"], "cid": pages[0]["cid"]})
    try:
        payload = public_json(url, retries, referer=f"https://www.bilibili.com/video/{detail['bvid']}")
        if payload.get("code") != 0:
            return []
        chapters = []
        for item in (payload.get("data") or {}).get("view_points") or []:
            start = float(item.get("from") or 0)
            chapters.append({
                "start_seconds": start,
                "timestamp": f"{int(start) // 60:02d}:{int(start) % 60:02d}",
                "title": item.get("content") or item.get("title"),
                "description": item.get("content") or None,
            })
        return chapters
    except Exception:
        return []


def snapshot_payload(video_id: str, video: dict[str, Any], captured_at: str) -> dict[str, Any]:
    return {
        "video_id": video_id,
        "view_count": video.get("view_count"),
        "like_count": video.get("like_count"),
        "coin_count": video.get("coin_count"),
        "favorite_count": video.get("favorite_count"),
        "share_count": video.get("share_count"),
        "comment_count": video.get("comment_count"),
        "danmaku_count": video.get("danmaku_count"),
        "captured_at": captured_at,
    }


def crawl_creator(
    db: SupabaseRest,
    creator: dict[str, Any],
    args: argparse.Namespace,
    manifest_dir: Path,
    job: dict[str, Any] | None = None,
) -> tuple[Counters, dict[str, Any]]:
    started_at = (job or {}).get("started_at") or utc_now()
    job_id: str | None = (job or {}).get("id")
    manifest_path: Path | None = None
    counters = Counters()
    errors: list[str] = []
    warnings: list[str] = []
    records: list[dict[str, Any]] = []

    if not args.dry_run and not job:
        created = db.request(
            "POST",
            "crawl_jobs",
            {
                "platform": "bilibili",
                "creator_id": creator["id"],
                "job_type": "bilibili_crawl",
                "status": "running",
                "started_at": started_at,
                "options_json": {
                    "max_videos": args.max_videos,
                    "force": args.force,
                    "retries": args.retries,
                },
            },
            "return=representation",
        )
        job_id = created[0]["id"]
    if job_id:
        manifest_path = manifest_dir / f"bilibili-{creator['platform_creator_id']}-{job_id}.json"

    try:
        try:
            bvids = recent_bvids(creator["profile_url"], creator["platform_creator_id"], args.max_videos, args.retries)
        except Exception as listing_error:
            cached = db.request(
                "GET",
                f"videos?select=platform_video_id&creator_id=eq.{creator['id']}"
                f"&platform=eq.bilibili&order=published_at.desc&limit={args.max_videos}",
            )
            bvids = [row["platform_video_id"] for row in cached or []]
            if not bvids:
                raise listing_error
            warnings.append(f"Profile listing unavailable; refreshed known videos instead: {listing_error}")
        for bvid in bvids:
            try:
                detail = fetch_json(
                    f"https://api.bilibili.com/x/web-interface/view?bvid={urllib.parse.quote(bvid)}",
                    args.retries,
                )
                crawled_at = utc_now()
                video = video_payload(creator["id"], detail, crawled_at)
                chapters = bilibili_chapters(detail, args.retries)
                if chapters:
                    video["chapters_json"] = chapters
                existing = db.request(
                    "GET",
                    f"videos?select=id&platform=eq.bilibili&platform_video_id=eq.{urllib.parse.quote(bvid)}&limit=1",
                ) if not args.dry_run else []
                if args.dry_run:
                    records.append({"action": "would_upsert", "video": video})
                    counters.success += 1
                    continue
                rows = db.request(
                    "POST",
                    "videos?on_conflict=platform,platform_video_id",
                    video,
                    "resolution=merge-duplicates,return=representation",
                )
                video_id = rows[0]["id"]
                db.request("POST", "video_metrics_snapshots", snapshot_payload(video_id, video, crawled_at))
                action = "updated" if existing else "inserted"
                if existing:
                    counters.updated += 1
                else:
                    counters.success += 1
                records.append({"action": action, "bvid": bvid, "video_id": video_id, "title": video["title"]})
            except Exception as exc:  # continue with other videos
                counters.failed += 1
                errors.append(f"{bvid}: {exc}")
        if not bvids:
            counters.skipped += 1
            errors.append("No public videos were returned for this creator")
    except Exception as exc:
        counters.failed += 1
        errors.append(str(exc))

    finished_at = utc_now()
    status = "succeeded"
    if counters.failed and (counters.success or counters.updated):
        status = "partially_succeeded"
    elif counters.failed:
        status = "failed"
    manifest = {
        "job_id": job_id,
        "job_type": "bilibili_crawl",
        "creator": creator,
        "started_at": started_at,
        "finished_at": finished_at,
        "status": status,
        "dry_run": args.dry_run,
        "counts": counters.__dict__,
        "errors": errors,
        "warnings": warnings,
        "records": records,
    }
    if not args.dry_run and job_id and manifest_path:
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        db.request("PATCH", f"creators?id=eq.{creator['id']}", {"last_crawled_at": finished_at})
        db.request(
            "PATCH",
            f"crawl_jobs?id=eq.{job_id}",
            {
                "status": status,
                "finished_at": finished_at,
                "success_count": counters.success,
                "updated_count": counters.updated,
                "skipped_count": counters.skipped,
                "failed_count": counters.failed,
                "error_summary": "\n".join(errors)[:4000] or None,
                "manifest_path": str(manifest_path),
            },
        )
    return counters, manifest


def command_bilibili(args: argparse.Namespace) -> int:
    db = open_db(args.retries)
    creators = db.tracked_creators("bilibili", args.max_creators, args.creator_id)
    if not creators:
        print("No tracked Bilibili creators found.")
        return 0
    manifest_dir = Path(args.manifest_dir).expanduser().resolve()
    total = Counters()
    for creator in creators:
        print(f"[{creator['name']}] reading latest {args.max_videos} videos...", flush=True)
        counters, manifest = crawl_creator(db, creator, args, manifest_dir)
        for field in total.__dict__:
            setattr(total, field, getattr(total, field) + getattr(counters, field))
        print(f"[{creator['name']}] {manifest['status']}: {counters.__dict__}")
    print(json.dumps({"creators": len(creators), "counts": total.__dict__}, ensure_ascii=False))
    return 1 if total.failed and not (total.success or total.updated) else 0


def selected_videos(db: SupabaseRest, platform: str, video_id: str | None, limit: int, pending_only: bool = False) -> list[dict[str, Any]]:
    query = f"videos?select=*&platform=eq.{platform}&order=published_at.desc&limit={max(1, limit)}"
    if video_id:
        query += f"&id=eq.{urllib.parse.quote(video_id)}"
    elif pending_only:
        query += "&transcript_status=in.(pending,failed)"
    return db.request("GET", query) or []


def command_comments(args: argparse.Namespace) -> int:
    db = open_db(args.retries)
    videos = selected_videos(db, "bilibili", args.video_id, args.max_videos)
    failed = 0
    for video in videos:
        result = pipeline.collect_bilibili_comments(
            db,
            video,
            {
                "limit": args.limit,
                "include_replies": args.include_replies,
                "delay": args.delay,
                "retries": args.retries,
            },
            dry_run=args.dry_run,
            fetch_json=fetch_json,
            fetch_comments=fetch_bilibili_comments,
        )
        print(json.dumps({"video": video["title"], **result["counts"], "status": result["status"], "errors": result.get("errors", [])}, ensure_ascii=False))
        failed += result["counts"]["failed"]
    return 1 if failed and not args.dry_run else 0


def command_transcribe(args: argparse.Namespace) -> int:
    db = open_db(args.retries)
    platform = args.platform or "bilibili"
    videos = selected_videos(db, platform, args.video_id, args.max_videos, pending_only=not args.force)
    failed = 0
    for video in videos:
        result = pipeline.transcribe_video(
            db,
            video,
            {
                "force": args.force,
                "model": args.model,
                "retries": args.retries,
                "max_duration": args.max_duration,
            },
            dry_run=args.dry_run,
        )
        print(json.dumps(result, ensure_ascii=False))
        failed += int(result.get("status") == "failed")
    return 1 if failed else 0


def command_worker(args: argparse.Namespace) -> int:
    db = open_db(args.retries)
    while True:
        creator_counts = process_queued_creator_jobs(db, args.max_jobs)
        remaining = max(1, args.max_jobs - creator_counts["processed"])
        video_counts = pipeline.process_queued_jobs(db, limit=remaining, fetch_json=fetch_json, fetch_comments=fetch_bilibili_comments)
        counts = {key: creator_counts[key] + video_counts[key] for key in creator_counts}
        print(json.dumps(counts, ensure_ascii=False), flush=True)
        if args.once:
            return 1 if counts["failed"] else 0
        time.sleep(max(2, args.poll_seconds))


def metric_number(value: Any) -> int | None:
    if value in (None, ""):
        return None
    text = str(value).strip().lower()
    multiplier = 1
    if text.endswith(("万", "w")):
        multiplier, text = 10_000, text[:-1]
    elif text.endswith("亿"):
        multiplier, text = 100_000_000, text[:-1]
    try:
        return int(float(text.replace(",", "")) * multiplier)
    except ValueError:
        return None


def chapter_seconds(timestamp: str | None) -> float | None:
    if not timestamp:
        return None
    try:
        pieces = [int(part) for part in timestamp.split(":")]
        if len(pieces) == 2:
            return pieces[0] * 60 + pieces[1]
        if len(pieces) == 3:
            return pieces[0] * 3600 + pieces[1] * 60 + pieces[2]
    except ValueError:
        return None
    return None


def crawl_douyin_creator(db: SupabaseRest, creator: dict[str, Any], args: argparse.Namespace, job: dict[str, Any] | None = None) -> tuple[Counters, dict[str, Any]]:
    started = (job or {}).get("started_at") or utc_now()
    counters = Counters()
    errors: list[str] = []
    records: list[dict[str, Any]] = []
    if not args.dry_run and not job:
        job = db.request(
            "POST", "crawl_jobs",
            {"platform": "douyin", "creator_id": creator["id"], "job_type": "douyin_crawl", "status": "running", "started_at": started,
             "options_json": {"max_videos": args.max_videos, "force": args.force, "retries": args.retries}},
            "return=representation",
        )[0]
    try:
        command = [
            "node", str(ROOT / "scripts" / "douyin_cdp.mjs"), "--url", creator["profile_url"],
            "--max-videos", str(args.max_videos), "--wait-ms", str(args.wait_ms),
        ]
        endpoint = os.getenv("CHROME_CDP_URL")
        if endpoint:
            command += ["--endpoint", endpoint]
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=max(120, args.max_videos * 30))
        if completed.returncode:
            raise RuntimeError(completed.stderr.strip() or "抖音 Chrome CDP 采集失败")
        payload = json.loads(completed.stdout)
        follower_count = metric_number(payload.get("follower_text"))
        likes_count = metric_number(payload.get("likes_text"))
        if not args.dry_run:
            db.request("PATCH", f"creators?id=eq.{creator['id']}", {"follower_count": follower_count, "total_likes_count": likes_count, "last_crawled_at": utc_now()})
            db.request("POST", "creator_metrics_snapshots", {"creator_id": creator["id"], "follower_count": follower_count, "total_likes_count": likes_count})
        for card in payload.get("cards") or []:
            aweme_id = str(card.get("aweme_id") or "")
            if not aweme_id:
                counters.skipped += 1
                continue
            existing = [] if args.dry_run else db.request("GET", f"videos?select=id&platform=eq.douyin&platform_video_id=eq.{urllib.parse.quote(aweme_id)}&limit=1")
            if existing and not args.force:
                counters.skipped += 1
                continue
            chapters = [
                {**chapter, "start_seconds": chapter_seconds(chapter.get("timestamp"))}
                for chapter in card.get("chapters") or []
            ]
            published = None
            published_text = card.get("published_text")
            if published_text:
                normalized = re.sub(r"[年/.]", "-", str(published_text)).replace("月", "-").replace("日", "")
                try:
                    published = datetime.fromisoformat(normalized).replace(tzinfo=timezone.utc).isoformat()
                except ValueError:
                    pass
            video = {
                "creator_id": creator["id"], "platform": "douyin", "platform_video_id": aweme_id,
                "title": card.get("title") or card.get("description") or aweme_id, "video_url": card.get("url") or f"https://www.douyin.com/video/{aweme_id}",
                "cover_url": card.get("cover_url"), "description": card.get("description"), "published_at": published,
                "chapters_json": chapters, "is_pinned": bool(card.get("is_pinned")), "last_crawled_at": utc_now(),
            }
            if args.dry_run:
                records.append({"action": "would_upsert", "video": video, "public_comment_samples": len(card.get("comments") or [])})
                counters.success += 1
                continue
            row = db.request("POST", "videos?on_conflict=platform,platform_video_id", video, "resolution=merge-duplicates,return=representation")[0]
            video_id = row["id"]
            for index, comment in enumerate(card.get("comments") or []):
                content = str(comment.get("content") or "").strip()
                if not content:
                    continue
                comment_key = hashlib.sha256(f"{aweme_id}:{index}:{content}".encode()).hexdigest()[:32]
                db.request(
                    "POST", "comments?on_conflict=video_id,platform_comment_id",
                    {"video_id": video_id, "platform_comment_id": comment_key, "author_name": comment.get("author"), "content": content,
                     "like_count": metric_number(comment.get("like_text")), "is_representative": True, "is_partial_public_sample": True},
                    "resolution=merge-duplicates",
                )
            counters.updated += int(bool(existing))
            counters.success += int(not existing)
            records.append({"action": "updated" if existing else "inserted", "aweme_id": aweme_id, "video_id": video_id})
    except Exception as exc:
        counters.failed += 1
        errors.append(str(exc))
    status = "succeeded" if not counters.failed else ("partially_succeeded" if counters.success or counters.updated else "failed")
    manifest = {
        "job_id": job and job["id"], "job_type": "douyin_crawl", "creator": creator, "started_at": started, "finished_at": utc_now(),
        "status": status, "counts": counters.__dict__, "errors": errors, "records": records,
        "comment_notice": "抖音评论来自页面公开可见片段，不是完整评论 API 数据。",
    }
    if job:
        path = Path(args.manifest_dir).expanduser().resolve() / f"douyin-{creator['platform_creator_id']}-{job['id']}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        db.request("PATCH", f"crawl_jobs?id=eq.{job['id']}", {"status": status, "finished_at": utc_now(), "success_count": counters.success,
                   "updated_count": counters.updated, "skipped_count": counters.skipped, "failed_count": counters.failed,
                   "error_summary": "\n".join(errors)[:4000] or None, "manifest_path": str(path)})
    return counters, manifest


def command_douyin(args: argparse.Namespace) -> int:
    db = open_db(args.retries)
    creators = db.tracked_creators("douyin", args.max_creators, args.creator_id)
    total = Counters()
    for creator in creators:
        counters, manifest = crawl_douyin_creator(db, creator, args)
        for field in total.__dict__:
            setattr(total, field, getattr(total, field) + getattr(counters, field))
        print(json.dumps({"creator": creator["name"], "status": manifest["status"], **counters.__dict__}, ensure_ascii=False))
    return 1 if total.failed and not (total.success or total.updated) else 0


def x_api(path: str, params: dict[str, Any], retries: int) -> dict[str, Any]:
    token = os.getenv("X_BEARER_TOKEN")
    if not token:
        raise RuntimeError("缺少本机 X_BEARER_TOKEN")
    url = f"https://api.x.com/2/{path.lstrip('/')}?{urllib.parse.urlencode(params)}"
    headers = {"Authorization": f"Bearer {token}", "User-Agent": "CreatorSignal/0.2"}
    for attempt in range(retries + 1):
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=45, context=TLS_CONTEXT) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:1000]
            if exc.code in {401, 403} or attempt >= retries:
                raise RuntimeError(f"X API {exc.code}: {detail}") from exc
            time.sleep(min(2 ** attempt, 5))
        except urllib.error.URLError:
            if attempt >= retries:
                raise
            time.sleep(min(2 ** attempt, 5))
    raise AssertionError("unreachable")


def crawl_x_creator(db: SupabaseRest, creator: dict[str, Any], args: argparse.Namespace, job: dict[str, Any] | None = None) -> tuple[Counters, dict[str, Any]]:
    started = (job or {}).get("started_at") or utc_now()
    counters = Counters()
    errors: list[str] = []
    records: list[dict[str, Any]] = []
    if not args.dry_run and not job:
        job = db.request("POST", "crawl_jobs", {
            "platform": "x", "creator_id": creator["id"], "job_type": "x_crawl", "status": "running", "started_at": started,
            "options_json": {"max_videos": args.max_videos, "force": args.force, "retries": args.retries},
        }, "return=representation")[0]
    try:
        username = creator["profile_url"].rstrip("/").split("/")[-1].lstrip("@") or creator["platform_creator_id"].lstrip("@")
        try:
            user_response = x_api(
                f"users/by/username/{urllib.parse.quote(username)}",
                {"user.fields": "id,name,username,description,profile_image_url,public_metrics"},
                args.retries,
            )
            user = user_response.get("data")
            if not user:
                raise RuntimeError(f"X 找不到 @{username}")
            user_id = user["id"]
            posts_response = x_api(
                f"users/{user_id}/tweets",
                {
                    "max_results": max(5, min(args.max_videos, 100)), "exclude": "replies",
                    "tweet.fields": "id,text,created_at,public_metrics,entities,attachments,referenced_tweets",
                    "expansions": "attachments.media_keys", "media.fields": "media_key,type,url,preview_image_url,width,height,duration_ms,alt_text",
                },
                args.retries,
            )
        except Exception as api_error:
            command = ["node", str(ROOT / "scripts" / "x_cdp.mjs"), "--url", creator["profile_url"], "--max-posts", str(args.max_videos)]
            completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=max(120, args.max_videos * 20))
            if completed.returncode:
                raise RuntimeError(f"X API 不可用；Chrome 页面采集也失败：{completed.stderr.strip() or api_error}") from api_error
            browser_data = json.loads(completed.stdout)
            user_id = browser_data.get("user_id") or creator["platform_creator_id"]
            user = {"id": user_id, "name": creator["name"], "username": browser_data.get("username") or username,
                    "public_metrics": {"followers_count": metric_number(browser_data.get("follower_text"))}}
            posts_response = {"data": [
                {"id": item["id"], "text": item["text"], "created_at": item.get("created_at"),
                 "public_metrics": {"impression_count": item.get("view_count"), "like_count": item.get("like_count"),
                                    "bookmark_count": item.get("bookmark_count"), "retweet_count": item.get("repost_count"), "reply_count": item.get("reply_count")},
                 "browser_cover_url": item.get("cover_url"), "browser_is_pinned": item.get("is_pinned", False)}
                for item in browser_data.get("posts") or []
            ]}
        metrics = user.get("public_metrics") or {}
        if not args.dry_run:
            db.request("PATCH", f"creators?id=eq.{creator['id']}", {
                "name": user.get("name") or creator["name"], "profile_url": f"https://x.com/{user.get('username') or username}",
                "platform_creator_id": user_id, "follower_count": metrics.get("followers_count"), "last_crawled_at": utc_now(),
            })
            db.request("POST", "creator_metrics_snapshots", {
                "creator_id": creator["id"], "follower_count": metrics.get("followers_count"), "total_likes_count": None,
            })
        media_by_key = {item["media_key"]: item for item in (posts_response.get("includes") or {}).get("media") or []}
        for post in (posts_response.get("data") or [])[:args.max_videos]:
            post_id = post["id"]
            public = post.get("public_metrics") or {}
            media = [media_by_key[key] for key in (post.get("attachments") or {}).get("media_keys") or [] if key in media_by_key]
            existing = [] if args.dry_run else db.request("GET", f"videos?select=id&platform=eq.x&platform_video_id=eq.{post_id}&limit=1")
            payload = {
                "creator_id": creator["id"], "platform": "x", "platform_video_id": post_id,
                "title": (post.get("text") or f"X Post {post_id}")[:160], "description": post.get("text") or None,
                "video_url": f"https://x.com/{user.get('username') or username}/status/{post_id}",
                "cover_url": post.get("browser_cover_url") or next((item.get("preview_image_url") or item.get("url") for item in media if item.get("preview_image_url") or item.get("url")), None),
                "published_at": post.get("created_at"), "parts_json": media,
                "is_pinned": post.get("browser_is_pinned"),
                "view_count": public.get("impression_count"), "like_count": public.get("like_count"),
                "favorite_count": public.get("bookmark_count"), "share_count": public.get("retweet_count"),
                "comment_count": public.get("reply_count"), "transcript_status": "skipped", "last_crawled_at": utc_now(),
            }
            if args.dry_run:
                counters.success += 1
                records.append({"action": "would_upsert", "post_id": post_id, "title": payload["title"]})
                continue
            row = db.request("POST", "videos?on_conflict=platform,platform_video_id", payload, "resolution=merge-duplicates,return=representation")[0]
            db.request("POST", "video_metrics_snapshots", {
                "video_id": row["id"], "view_count": payload["view_count"], "like_count": payload["like_count"],
                "favorite_count": payload["favorite_count"], "share_count": payload["share_count"], "comment_count": payload["comment_count"],
            })
            counters.updated += int(bool(existing))
            counters.success += int(not existing)
            records.append({"action": "updated" if existing else "inserted", "post_id": post_id, "video_id": row["id"]})
    except Exception as exc:
        counters.failed += 1
        errors.append(str(exc))
    status = "succeeded" if not counters.failed else ("partially_succeeded" if counters.success or counters.updated else "failed")
    manifest = {"job_id": job and job["id"], "job_type": "x_crawl", "creator": creator, "started_at": started, "finished_at": utc_now(),
                "status": status, "counts": counters.__dict__, "errors": errors, "records": records}
    if job:
        path = Path(args.manifest_dir).expanduser().resolve() / f"x-{creator['id']}-{job['id']}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        db.request("PATCH", f"crawl_jobs?id=eq.{job['id']}", {"status": status, "finished_at": utc_now(), "success_count": counters.success,
                   "updated_count": counters.updated, "skipped_count": counters.skipped, "failed_count": counters.failed,
                   "error_summary": "\n".join(errors)[:4000] or None, "manifest_path": str(path)})
    return counters, manifest


def command_x(args: argparse.Namespace) -> int:
    db = open_db(args.retries)
    creators = db.tracked_creators("x", args.max_creators, args.creator_id)
    total = Counters()
    for creator in creators:
        counters, manifest = crawl_x_creator(db, creator, args)
        for field in total.__dict__:
            setattr(total, field, getattr(total, field) + getattr(counters, field))
        print(json.dumps({"creator": creator["name"], "status": manifest["status"], **counters.__dict__, "errors": manifest["errors"]}, ensure_ascii=False))
    return 1 if total.failed and not (total.success or total.updated) else 0


def process_queued_creator_jobs(db: SupabaseRest, limit: int) -> dict[str, int]:
    jobs = db.request("GET", "crawl_jobs?select=*&status=eq.queued&job_type=in.(bilibili_crawl,douyin_crawl,x_crawl)"
                      f"&order=created_at.asc&limit={max(1, limit)}") or []
    counts = {"processed": 0, "succeeded": 0, "failed": 0}
    for job in jobs:
        started = utc_now()
        db.request("PATCH", f"crawl_jobs?id=eq.{job['id']}&status=eq.queued", {"status": "running", "started_at": started})
        job["started_at"] = started
        creator_rows = db.request("GET", f"creators?select=*&id=eq.{job['creator_id']}&limit=1") or []
        if not creator_rows:
            pipeline.finish_job(db, job, status="failed", failed=1, error="找不到关联博主")
            counts["processed"] += 1; counts["failed"] += 1
            continue
        options = job.get("options_json") or {}
        task_args = argparse.Namespace(
            dry_run=False, force=bool(options.get("force", False)), max_videos=int(options.get("max_videos", 3)),
            retries=int(options.get("retries", 3)), wait_ms=int(options.get("wait_ms", 3500)),
            manifest_dir=str(DEFAULT_MANIFEST_DIR),
        )
        try:
            if job["job_type"] == "bilibili_crawl":
                _, result = crawl_creator(db, creator_rows[0], task_args, DEFAULT_MANIFEST_DIR, job=job)
            elif job["job_type"] == "douyin_crawl":
                _, result = crawl_douyin_creator(db, creator_rows[0], task_args, job=job)
            else:
                _, result = crawl_x_creator(db, creator_rows[0], task_args, job=job)
            counts["processed"] += 1
            counts["succeeded" if result["status"] in {"succeeded", "partially_succeeded"} else "failed"] += 1
        except Exception as exc:
            pipeline.finish_job(db, job, status="failed", failed=1, error=str(exc))
            counts["processed"] += 1; counts["failed"] += 1
    return counts


def command_all(args: argparse.Namespace) -> int:
    values = dict(vars(args))
    values.update({"creator_id": None, "manifest_dir": args.manifest_dir})
    bili_args = argparse.Namespace(**values)
    bili_code = command_bilibili(bili_args)
    douyin_code = command_douyin(bili_args)
    x_code = command_x(bili_args)
    return 1 if bili_code and douyin_code and x_code else 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="creator-signal", description="Creator Signal local ingestion")
    commands = root.add_subparsers(dest="command", required=True)
    bilibili = commands.add_parser("bilibili", help="Collect latest Bilibili videos and metrics")
    bilibili.add_argument("--dry-run", action="store_true")
    bilibili.add_argument("--force", action="store_true")
    bilibili.add_argument("--max-creators", type=int)
    bilibili.add_argument("--creator-id", help="Run one creator by Creator Signal UUID")
    bilibili.add_argument("--max-videos", type=int, default=3)
    bilibili.add_argument("--retries", type=int, default=3)
    bilibili.add_argument("--manifest-dir", default=str(DEFAULT_MANIFEST_DIR))
    bilibili.set_defaults(handler=command_bilibili)

    comments = commands.add_parser("bilibili-comments", help="Collect representative Bilibili root comments")
    comments.add_argument("--video-id", help="Run one Creator Signal video UUID")
    comments.add_argument("--max-videos", type=int, default=10)
    comments.add_argument("--limit", type=int, default=30)
    comments.add_argument("--include-replies", action="store_true")
    comments.add_argument("--delay", type=float, default=1.0)
    comments.add_argument("--retries", type=int, default=3)
    comments.add_argument("--dry-run", action="store_true")
    comments.add_argument("--force", action="store_true", help="Accepted for consistent automation interfaces")
    comments.set_defaults(handler=command_comments)

    transcribe = commands.add_parser("transcribe", help="Read platform subtitles or transcribe locally")
    transcribe.add_argument("--video-id", help="Run one Creator Signal video UUID")
    transcribe.add_argument("--platform", choices=["bilibili", "douyin"])
    transcribe.add_argument("--max-videos", type=int, default=1)
    transcribe.add_argument("--model", choices=["small", "medium"], default="small")
    transcribe.add_argument("--max-duration", type=int, default=7200)
    transcribe.add_argument("--retries", type=int, default=3)
    transcribe.add_argument("--dry-run", action="store_true")
    transcribe.add_argument("--force", action="store_true")
    transcribe.set_defaults(handler=command_transcribe)

    worker = commands.add_parser("worker", help="Process jobs queued from the website")
    worker.add_argument("--once", action="store_true")
    worker.add_argument("--max-jobs", type=int, default=5)
    worker.add_argument("--poll-seconds", type=int, default=15)
    worker.add_argument("--retries", type=int, default=3)
    worker.set_defaults(handler=command_worker)

    douyin = commands.add_parser("douyin", help="Collect Douyin profiles and public page fragments through local Chrome CDP")
    douyin.add_argument("--dry-run", action="store_true")
    douyin.add_argument("--force", action="store_true")
    douyin.add_argument("--max-creators", type=int)
    douyin.add_argument("--creator-id")
    douyin.add_argument("--max-videos", type=int, default=3)
    douyin.add_argument("--retries", type=int, default=3)
    douyin.add_argument("--wait-ms", type=int, default=3500)
    douyin.add_argument("--manifest-dir", default=str(DEFAULT_MANIFEST_DIR))
    douyin.set_defaults(handler=command_douyin)

    x = commands.add_parser("x", help="Sync recent public X posts through the official API")
    x.add_argument("--dry-run", action="store_true")
    x.add_argument("--force", action="store_true")
    x.add_argument("--max-creators", type=int)
    x.add_argument("--creator-id")
    x.add_argument("--max-videos", type=int, default=10)
    x.add_argument("--retries", type=int, default=3)
    x.add_argument("--manifest-dir", default=str(DEFAULT_MANIFEST_DIR))
    x.set_defaults(handler=command_x)

    all_platforms = commands.add_parser("all", help="Run Bilibili, Douyin, and X collection once")
    all_platforms.add_argument("--dry-run", action="store_true")
    all_platforms.add_argument("--force", action="store_true")
    all_platforms.add_argument("--max-creators", type=int)
    all_platforms.add_argument("--max-videos", type=int, default=3)
    all_platforms.add_argument("--retries", type=int, default=3)
    all_platforms.add_argument("--wait-ms", type=int, default=3500)
    all_platforms.add_argument("--manifest-dir", default=str(DEFAULT_MANIFEST_DIR))
    all_platforms.set_defaults(handler=command_all)
    return root


def main() -> int:
    args = parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
