"""Fetches free vertical stock videos from Pexels for the background montage.

Requires a free Pexels API key in env var PEXELS_API_KEY. We can't legally
auto-source actual movie clips, so we use cinematic, mood-fitting b-roll instead
(cinema, film reel, the film's genre/setting). If no key/results, returns [] and
the renderer falls back to an animated gradient.
"""
import os
import json
import urllib.request
import urllib.parse
from pathlib import Path


# Generic cinematic terms always mixed in so every video feels "film-like"
CINEMATIC_BASE = ["cinema", "film reel", "movie theater", "spotlight", "cinematic light"]

_HEADERS_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) TikTokFilmBot/1.0"


def _search_pexels(query: str, api_key: str, limit: int = 8,
                   orientation: str = "portrait") -> list[str]:
    """Returns up to `limit` video file URLs for the query in the given orientation."""
    params = urllib.parse.urlencode({
        "query": query,
        "orientation": orientation,
        "size": "medium",
        "per_page": 15,
    })
    url = f"https://api.pexels.com/videos/search?{params}"
    req = urllib.request.Request(url, headers={
        "Authorization": api_key,
        "User-Agent": _HEADERS_UA,
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        print(f"Pexels-Suche fehlgeschlagen ('{query}'): {e}")
        return []

    portrait = orientation == "portrait"
    urls = []
    for video in data.get("videos", []):
        if portrait:
            candidates = [f for f in video.get("video_files", [])
                          if f.get("height", 0) >= 1280 and f.get("width", 1) < f.get("height", 1)]
        else:
            candidates = [f for f in video.get("video_files", [])
                          if f.get("height", 0) >= 720 and f.get("width", 1) > f.get("height", 1)]
        if candidates:
            best = min(candidates, key=lambda f: f["height"])  # smallest HD = fast DL
            urls.append(best["link"])
        if len(urls) >= limit:
            break
    return urls


def _download(url: str, output_path: str) -> str | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _HEADERS_UA})
        with urllib.request.urlopen(req, timeout=60) as resp, open(output_path, "wb") as f:
            f.write(resp.read())
        return output_path
    except Exception as e:
        print(f"Download fehlgeschlagen: {e}")
        return None


def fetch_background_clips(visual_tags: list[str], output_dir: str, count: int = 10,
                          orientation: str = "portrait") -> list[str]:
    """
    Downloads up to `count` distinct clips matching the visual tags (+ cinematic
    base terms) in the given orientation. Returns local file paths (maybe empty).
    """
    api_key = os.environ.get("PEXELS_API_KEY")
    if not api_key:
        return []

    queries = list(visual_tags or []) + CINEMATIC_BASE

    seen, urls = set(), []
    for q in queries:
        for u in _search_pexels(q, api_key, orientation=orientation):
            if u not in seen:
                seen.add(u)
                urls.append(u)
        if len(urls) >= count:
            break

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    paths = []
    for i, u in enumerate(urls[:count]):
        dest = str(Path(output_dir) / f"clip_{i}.mp4")
        if _download(u, dest):
            paths.append(dest)
    if paths:
        print(f"{len(paths)} Hintergrund-Clips geladen")
    return paths


if __name__ == "__main__":
    clips = fetch_background_clips(["space", "futuristic city"], "/tmp/bgclips", count=6)
    print("Clips:", clips)
