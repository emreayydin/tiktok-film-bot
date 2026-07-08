"""AI visuals: Flux images (fal.ai) per fact + a Runway image2video hook clip.

Best price/performance: one on-theme Flux image per fact (~cents), animated for
free with Ken-Burns in the renderer; the hook gets a real Runway motion clip where
it matters most. Everything degrades gracefully — if a key is missing or a call
fails, the caller falls back to the free Pexels montage, so the bot never breaks.

Env:
  FAL_KEY          – fal.ai API key (Flux images)
  RUNWAY_API_KEY   – Runway API key (image->video hook); optional
  FLUX_HOOK_MODEL  – default fal-ai/flux-pro/v1.1  (best quality, for hook + last fact)
  FLUX_FACT_MODEL  – default fal-ai/flux/dev       (cheaper, for the other facts)
"""
import os
import time
import urllib.request
import requests

FAL_RUN = "https://fal.run"
RUNWAY_API = "https://api.dev.runwayml.com/v1"
RUNWAY_VERSION = "2024-11-06"

HOOK_MODEL = os.environ.get("FLUX_HOOK_MODEL", "fal-ai/flux-pro/v1.1")
FACT_MODEL = os.environ.get("FLUX_FACT_MODEL", "fal-ai/flux/dev")

STYLE = "cinematic, dramatic lighting, film still, highly detailed, 9:16 vertical"


def _download(url: str, path: str) -> str:
    with urllib.request.urlopen(url, timeout=120) as r, open(path, "wb") as f:
        f.write(r.read())
    return path


# ---------------- fal.ai Flux ----------------

def flux_image(prompt: str, out_path: str, model: str = FACT_MODEL) -> tuple[str, str]:
    """Generates a 9:16 image. Returns (local_path, hosted_url). Raises on failure."""
    key = os.environ["FAL_KEY"]
    body = {
        "prompt": f"{prompt}, {STYLE}",
        "image_size": "portrait_16_9",
        "num_images": 1,
        "enable_safety_checker": True,
    }
    r = requests.post(f"{FAL_RUN}/{model}", headers={
        "Authorization": f"Key {key}",
        "Content-Type": "application/json",
    }, json=body, timeout=180)
    if r.status_code != 200:
        raise RuntimeError(f"fal {model} {r.status_code}: {r.text[:300]}")
    url = r.json()["images"][0]["url"]
    _download(url, out_path)
    return out_path, url


# ---------------- fal.ai image -> video (stay on one provider) ----------------

FAL_QUEUE = "https://queue.fal.run"


def fal_image_to_video(image_url: str, prompt: str, out_path: str, model: str) -> str:
    """Animates an image into a vertical clip via a fal.ai video model (queue API)."""
    key = os.environ["FAL_KEY"]
    headers = {"Authorization": f"Key {key}", "Content-Type": "application/json"}
    body = {"prompt": prompt, "image_url": image_url, "aspect_ratio": "9:16", "duration": "5"}
    r = requests.post(f"{FAL_QUEUE}/{model}", headers=headers, json=body, timeout=60)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"fal i2v init {r.status_code}: {r.text[:300]}")
    j = r.json()
    status_url, response_url = j["status_url"], j["response_url"]

    deadline = time.time() + 300
    while time.time() < deadline:
        time.sleep(6)
        st = requests.get(status_url, headers=headers, timeout=30).json()
        if st.get("status") == "COMPLETED":
            res = requests.get(response_url, headers=headers, timeout=60).json()
            url = res.get("video", {}).get("url") or res["video"]["url"]
            return _download(url, out_path)
        if st.get("status") in ("FAILED", "ERROR"):
            raise RuntimeError(f"fal i2v {st}")
    raise RuntimeError("fal i2v timeout")


# ---------------- Runway image -> video ----------------

def runway_hook(image_url: str, prompt: str, out_path: str, duration: int = 5) -> str:
    """Animates an image into a vertical motion clip. Returns local path. Raises on failure."""
    key = os.environ["RUNWAY_API_KEY"]
    headers = {"Authorization": f"Bearer {key}", "X-Runway-Version": RUNWAY_VERSION,
               "Content-Type": "application/json"}
    r = requests.post(f"{RUNWAY_API}/image_to_video", headers=headers, json={
        "model": "gen4_turbo",
        "promptImage": image_url,
        "promptText": prompt,
        "ratio": "720:1280",
        "duration": duration,
    }, timeout=60)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Runway init {r.status_code}: {r.text[:300]}")
    task_id = r.json()["id"]

    deadline = time.time() + 300
    while time.time() < deadline:
        time.sleep(6)
        t = requests.get(f"{RUNWAY_API}/tasks/{task_id}", headers=headers, timeout=30).json()
        status = t.get("status")
        if status == "SUCCEEDED":
            return _download(t["output"][0], out_path)
        if status in ("FAILED", "CANCELLED"):
            raise RuntimeError(f"Runway task {status}: {t.get('failure', '')}")
    raise RuntimeError("Runway timeout")


# ---------------- orchestration ----------------

def build_visuals(content: dict, work_dir: str) -> dict | None:
    """Builds per-section visuals: {'intro': {...}, 'fact_1': {...}, ...}.

    Each value is {'type': 'video'|'image', 'path': str}. Returns None if no FAL_KEY
    (caller then uses the Pexels montage). Individual failures fall back to None for
    that section, which the renderer fills from Pexels.
    """
    if not os.environ.get("FAL_KEY"):
        return None
    os.makedirs(work_dir, exist_ok=True)
    facts = content.get("facts", [])
    n = len(facts)
    visuals = {}

    # Fact images (last fact = hero -> best model)
    for i, f in enumerate(facts, 1):
        prompt = f.get("image_prompt") or f.get("headline") or content.get("subject", "")
        model = HOOK_MODEL if i == n else FACT_MODEL
        try:
            p, _ = flux_image(prompt, os.path.join(work_dir, f"fact_{i}.png"), model=model)
            visuals[f"fact_{i}"] = {"type": "image", "path": p}
            print(f"Flux Bild fact_{i} ✓")
        except Exception as e:
            print(f"Flux fact_{i} fehlgeschlagen: {e}")

    # Hook: Flux image (best model) -> Runway motion clip (if RUNWAY_API_KEY set)
    hook_prompt = content.get("hook_visual") or content.get("subject", "")
    try:
        hp, hook_url = flux_image(hook_prompt, os.path.join(work_dir, "hook.png"),
                                  model=HOOK_MODEL)
        motion = f"slow cinematic camera push, {hook_prompt}"
        fal_i2v = os.environ.get("FAL_HOOK_VIDEO_MODEL")  # e.g. fal-ai/ltx-video-13b-098/image-to-video
        visuals["intro"] = {"type": "image", "path": hp}   # default: animated still
        if os.environ.get("RUNWAY_API_KEY"):
            try:
                clip = runway_hook(hook_url, motion, os.path.join(work_dir, "hook.mp4"))
                visuals["intro"] = {"type": "video", "path": clip}
                print("Runway Hook-Clip ✓")
            except Exception as e:
                print(f"Runway Hook fehlgeschlagen ({e}) — nutze Standbild-Hook")
        elif fal_i2v:
            try:
                clip = fal_image_to_video(hook_url, motion,
                                          os.path.join(work_dir, "hook.mp4"), fal_i2v)
                visuals["intro"] = {"type": "video", "path": clip}
                print("fal.ai Hook-Clip ✓")
            except Exception as e:
                print(f"fal.ai Hook-Video fehlgeschlagen ({e}) — nutze Standbild-Hook")
    except Exception as e:
        print(f"Hook-Bild fehlgeschlagen: {e}")

    return visuals or None
