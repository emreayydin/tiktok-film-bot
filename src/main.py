"""Main entry point: generate a "5 Fakten über [Film/Serie]" script, narrate it,
render a vertical 9:16 video (>60s), and direct-post it to TikTok.
"""
import os
import sys
import json
import logging
import argparse
from pathlib import Path
from datetime import datetime

# Load .env so ANTHROPIC_API_KEY / TIKTOK_* are picked up automatically
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

from generate_content import generate_content
from text_to_speech import build_narration
from render_video import render_video, make_cover


def _get_uploader(name: str):
    """Selects the upload backend. 'postiz' posts publicly via the Postiz partner
    (recommended); 'tiktok' uses our own TikTok app (Sandbox/private only)."""
    if name == "tiktok":
        from upload_tiktok import upload_video
    else:
        from upload_postiz import upload_video
    return upload_video

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

OUTPUT_DIR = Path("output")


def _build_caption(content: dict) -> str:
    """TikTok caption: hook + film name + hashtags."""
    tags = content.get("tags", []) or ["film", "serie", "kino", "movie", "fyp"]
    base_tags = ["fyp", "filmtok", "film", "serie", "kino", "movie", "netflix"]
    seen, hashtags = set(), []
    for t in [t.lstrip("#").replace(" ", "") for t in (tags + base_tags)]:
        tl = t.lower()
        if tl and tl not in seen:
            seen.add(tl)
            hashtags.append(f"#{t}")
    return f"{content['title']}\n\n" + " ".join(hashtags[:12])


def run(category: str = None, dry_run: bool = False, privacy: str = None,
        uploader: str = "tiktok"):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    OUTPUT_DIR.mkdir(exist_ok=True)

    # 1. Generate script (avoiding previously posted films/series)
    log.info("Generiere Film-/Serien-Skript...")
    import history
    content = generate_content(category, avoid=history.recent_titles(60))
    log.info(f"Thema: {content['title']}  ({content['kind']}: {content['subject']})")
    (OUTPUT_DIR / f"content_{ts}.json").write_text(
        json.dumps(content, ensure_ascii=False, indent=2))

    # 2. Narration: intro + 5 facts + outro -> one audio track with timing
    segments = [("intro", content["intro"])]
    for i, f in enumerate(content["facts"], 1):
        segments.append((f"fact_{i}", f"{f['headline']}. {f['text']}"))
    segments.append(("outro", content["outro"]))

    log.info("Erzeuge Sprachausgabe...")
    audio_path = str(OUTPUT_DIR / f"audio_{ts}.mp3")
    words, sections = build_narration(segments, audio_path)
    dur = max(s["end"] for s in sections)
    log.info(f"Audio: {audio_path} ({dur:.0f}s, {len(words)} Wörter)")
    if dur < 60:
        log.warning(f"Video nur {dur:.0f}s — unter der 1-Minuten-Grenze. Wird trotzdem gerendert.")

    # 3. Render vertical video (9:16) with synced captions + FAKT badges
    log.info("Rendere Video (9:16)...")
    video_path = str(OUTPUT_DIR / f"video_{ts}.mp4")
    render_video(content, audio_path, sections, words, video_path)
    log.info(f"Video: {video_path}")

    # Optional eye-catching cover (upload as TikTok cover for more taps)
    cover_path = str(OUTPUT_DIR / f"cover_{ts}.png")
    try:
        make_cover(content, cover_path)
        log.info(f"Cover: {cover_path}")
    except Exception as e:
        log.warning(f"Cover konnte nicht erstellt werden: {e}")

    if dry_run:
        log.info(f"[DRY RUN] Nicht hochgeladen. Gespeichert: {video_path}")
        return video_path

    # 4. Upload to TikTok (via Postiz by default, or our own TikTok app)
    caption = _build_caption(content)
    upload_video = _get_uploader(uploader)
    log.info(f"Lade zu TikTok hoch (via {uploader})...")
    result = upload_video(video_path, caption, privacy=privacy)
    # Only record actually-posted videos so the film is avoided next time
    history.add_entry(content["subject"], content["title"], content.get("category", ""))
    log.info(f"Fertig! {result}")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TikTok Film & Serien Bot")
    parser.add_argument("--category", type=str, default=None, help="Genre (leer = zufällig)")
    parser.add_argument("--dry-run", action="store_true", help="Kein Upload, nur lokale Ausgabe")
    parser.add_argument("--privacy", type=str, default=os.environ.get("TIKTOK_PRIVACY"),
                        help="PUBLIC_TO_EVERYONE | SELF_ONLY | ... (Standard: Postiz -> public)")
    parser.add_argument("--uploader", type=str, default=os.environ.get("UPLOADER", "tiktok"),
                        choices=["postiz", "tiktok"],
                        help="tiktok = eigene App, Inbox/Entwürfe (kostenlos, du postest per Tap); "
                             "postiz = öffentlich über Partner (kostenpflichtig)")
    args = parser.parse_args()
    run(category=args.category, dry_run=args.dry_run, privacy=args.privacy,
        uploader=args.uploader)
