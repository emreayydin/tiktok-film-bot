"""Uploads a video to TikTok (public) via Postiz.

Postiz is a social-media scheduler that is an approved TikTok partner, so posting
publicly through it does NOT require our own audited TikTok app — you just connect
your TikTok account inside Postiz once. This module drives the official Postiz CLI:

    postiz upload <video>            -> uploads media, returns a verified URL
    postiz posts:create ... -i <id>  -> schedules/publishes the post to TikTok

Env vars:
  POSTIZ_API_KEY   (required)  – from your Postiz account (Settings → API)
  POSTIZ_API_URL   (optional)  – only for self-hosted Postiz
  POSTIZ_TIKTOK_ID (optional)  – TikTok integration id; auto-discovered if unset
  TIKTOK_PRIVACY   (optional)  – default PUBLIC_TO_EVERYONE
"""
import os
import json
import shutil
import subprocess
from datetime import datetime, timedelta, timezone


def _postiz_bin() -> list[str]:
    """Returns how to invoke the Postiz CLI (global binary or via npx)."""
    if shutil.which("postiz"):
        return ["postiz"]
    return ["npx", "-y", "postiz"]


def _run(args: list[str]) -> str:
    if not os.environ.get("POSTIZ_API_KEY"):
        raise RuntimeError("POSTIZ_API_KEY ist nicht gesetzt. Hol dir den Key in Postiz "
                           "(Settings → API) und trag ihn in .env / als GitHub-Secret ein.")
    r = subprocess.run(_postiz_bin() + args, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"postiz {args[0]} fehlgeschlagen:\n{(r.stderr or r.stdout)[-1500:]}")
    return r.stdout.strip()


def _extract_json(out: str):
    """Postiz commands print JSON; tolerate leading/trailing log lines."""
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        start = min((i for i in (out.find("{"), out.find("[")) if i != -1), default=-1)
        end = max(out.rfind("}"), out.rfind("]"))
        if start != -1 and end != -1:
            return json.loads(out[start:end + 1])
        raise


def _tiktok_integration_id() -> str:
    tid = os.environ.get("POSTIZ_TIKTOK_ID")
    if tid:
        return tid
    data = _extract_json(_run(["integrations:list"]))
    for it in (data if isinstance(data, list) else data.get("output", [])):
        if it.get("identifier") == "tiktok":
            return it["id"]
    raise RuntimeError("Keine TikTok-Integration in Postiz gefunden. Verbinde zuerst dein "
                       "TikTok-Konto in Postiz (Channels → Add channel → TikTok).")


def upload_video(video_path: str, caption: str, when: str = None,
                 privacy: str = None) -> str:
    """Uploads and schedules a public TikTok post via Postiz. Returns CLI output."""
    tid = _tiktok_integration_id()

    up = _extract_json(_run(["upload", video_path]))
    media_url = up["path"] if isinstance(up, dict) else up[0]["path"]
    print(f"Postiz-Upload OK: {media_url}")

    if when is None:
        # Postiz requires a schedule date; a few minutes out = "post shortly".
        when = (datetime.now(timezone.utc) + timedelta(minutes=3)).strftime("%Y-%m-%dT%H:%M:%SZ")

    privacy = privacy or os.environ.get("TIKTOK_PRIVACY", "PUBLIC_TO_EVERYONE")
    settings = json.dumps({
        "privacy": privacy,
        "duet": True,
        "stitch": True,
        "comment": True,
    })

    out = _run(["posts:create", "-c", caption, "-m", media_url,
                "-s", when, "--settings", settings, "-i", tid])
    print(f"Post geplant für {when} (TikTok, {privacy})")
    return out


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv
        from pathlib import Path
        load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    except ImportError:
        pass
    # Quick check: list connected integrations
    print(_run(["integrations:list"]))
