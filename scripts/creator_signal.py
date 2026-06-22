#!/usr/bin/env python3
"""Local Creator Signal ingestion CLI.

Phase 2 currently implements Bilibili creator/video metadata ingestion only.
It never downloads video media.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
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
    if nav.get("code") != 0:
        raise RuntimeError(f"Bilibili nav failed: {nav.get('message')}")
    wbi = nav["data"]["wbi_img"]
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
) -> tuple[Counters, dict[str, Any]]:
    started_at = utc_now()
    job_id: str | None = None
    manifest_path: Path | None = None
    counters = Counters()
    errors: list[str] = []
    warnings: list[str] = []
    records: list[dict[str, Any]] = []

    if not args.dry_run:
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
    load_dotenv(ROOT / ".env.local")
    load_dotenv(ROOT / ".env")
    url = os.getenv("NEXT_PUBLIC_SUPABASE_URL") or os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise SystemExit("Missing NEXT_PUBLIC_SUPABASE_URL/SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
    db = SupabaseRest(url, key, retries=args.retries)
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
    return root


def main() -> int:
    args = parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
