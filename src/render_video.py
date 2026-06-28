"""Renders a vertical 9:16 (1080x1920) TikTok video, ~80-110s long.

Pipeline:
  1. Background = a base montage of cinematic Pexels clips (hard cuts every ~2s +
     alternating Ken-Burns zoom). The base is looped to fill the whole video, so
     even a 100s video only encodes ~30s of montage once (fast on CI).
  2. Pillow renders one full-frame RGBA overlay per spoken caption group: a dark
     scrim, the film/series badge, a "FAKT n/5" pill for the current section, and
     the big animated caption synced to the voice.
  3. ffmpeg composites background + the overlay track (ONE concat-demuxer stream,
     not many enable-gated overlays — that keeps the render fast) + audio.

Uses only ffmpeg filters available without freetype/libass (overlay, scale, crop,
concat, zoompan), so it runs on the limited local build and Ubuntu CI alike.
"""
import subprocess
import re
import os
import math
import tempfile
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

from fetch_background import fetch_background_clips

VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
SEG = 2.0             # seconds per montage clip before a hard cut
BASE_TARGET = 34.0    # length of the base montage before it loops
ZOOM_PER_SEG = 0.14   # Ken-Burns push per clip

GOLD = (255, 210, 63)
INK = (11, 20, 55)

BOLD_FONTS = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/HelveticaNeue.ttc",
]

EMOJI_PATTERN = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]+",
    flags=re.UNICODE,
)


def _find_font(size: int) -> ImageFont.FreeTypeFont:
    for path in BOLD_FONTS:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _strip_emoji(text: str) -> str:
    return EMOJI_PATTERN.sub("", text or "").strip()


def _probe_duration(path: str) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path],
        capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def _wrap(draw, text, font, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


# ---------- caption grouping + section attribution ----------

def _group_captions(words: list[dict], sections: list[dict],
                    max_words: int = 3, total: float = None) -> list[dict]:
    groups, cur = [], []
    for w in words:
        cur.append(w)
        ends = w["text"] and w["text"][-1] in ".!?,;:"
        if len(cur) >= max_words or ends:
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)

    captions = []
    for g in groups:
        text = " ".join(x["text"] for x in g).strip().rstrip(",;:")
        captions.append({"text": text, "start": g[0]["start"], "end": g[-1]["end"]})

    for i in range(len(captions)):
        if i == 0:
            captions[i]["start"] = 0.0
        if i < len(captions) - 1:
            captions[i]["end"] = captions[i + 1]["start"]
        elif total:
            captions[i]["end"] = total
        # attribute to a narration section by midpoint
        mid = (captions[i]["start"] + captions[i]["end"]) / 2
        captions[i]["label"] = _label_at(mid, sections)
    return captions


def _label_at(t: float, sections: list[dict]) -> str:
    for s in sections:
        if s["start"] <= t < s["end"]:
            return s["label"]
    return sections[-1]["label"] if sections else "intro"


# ---------- PNG overlay frames (Pillow) ----------

def _gradient_png(top_rgb, bottom_rgb, path):
    base = Image.new("RGB", (VIDEO_WIDTH, VIDEO_HEIGHT), top_rgb)
    top = Image.new("RGB", (VIDEO_WIDTH, VIDEO_HEIGHT), bottom_rgb)
    mask = Image.new("L", (VIDEO_WIDTH, VIDEO_HEIGHT))
    mask.putdata([int(255 * (y / VIDEO_HEIGHT)) for y in range(VIDEO_HEIGHT) for _ in range(VIDEO_WIDTH)])
    base.paste(top, (0, 0), mask)
    base.save(path)
    return path


def _draw_scrim(d):
    d.rectangle([0, 0, VIDEO_WIDTH, VIDEO_HEIGHT], fill=(0, 0, 0, 90))
    d.rectangle([0, 0, VIDEO_WIDTH, 360], fill=(0, 0, 0, 80))
    d.rectangle([0, VIDEO_HEIGHT - 380, VIDEO_WIDTH, VIDEO_HEIGHT], fill=(0, 0, 0, 70))


def _pill(d, text, font, cx, top, fill=GOLD, fg=INK):
    w = d.textlength(text, font=font)
    pad_x, h = 30, font.size + 28
    d.rounded_rectangle([cx - w / 2 - pad_x, top, cx + w / 2 + pad_x, top + h],
                        radius=20, fill=fill)
    d.text((cx - w / 2, top + 12), text, font=font, fill=fg)
    return top + h


def _overlay_frame(content, label, total_facts, fact_idx, caption_text, path):
    """One full-frame RGBA overlay: scrim + branding + FAKT pill + caption."""
    img = Image.new("RGBA", (VIDEO_WIDTH, VIDEO_HEIGHT), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    _draw_scrim(d)

    cx = VIDEO_WIDTH / 2
    subject = _strip_emoji(content.get("subject", "")).upper()

    # ----- top branding -----
    if label == "intro":
        # bigger title treatment for the hook
        kind_f = _find_font(40)
        _pill(d, f"{content.get('kind', 'FILM').upper()} · 5 FAKTEN", kind_f, cx, 120)
        title_f = _find_font(66)
        y = 230
        for line in _wrap(d, subject, title_f, VIDEO_WIDTH - 140):
            w = d.textlength(line, font=title_f)
            d.text((cx - w / 2, y), line, font=title_f, fill=(255, 255, 255),
                   stroke_width=5, stroke_fill=(0, 0, 0))
            y += 80
    else:
        # persistent small subject badge at top
        sub_f = _find_font(40)
        bottom = _pill(d, subject[:34], sub_f, cx, 120)
        if label.startswith("fact_") and fact_idx:
            num_f = _find_font(44)
            _pill(d, f"FAKT {fact_idx}/{total_facts}", num_f, cx, bottom + 18,
                  fill=(255, 255, 255), fg=INK)

    # ----- big watermark fact number (subtle) -----
    if label.startswith("fact_") and fact_idx:
        big_f = _find_font(520)
        num = str(fact_idx)
        nw = d.textlength(num, font=big_f)
        d.text((cx - nw / 2, VIDEO_HEIGHT / 2 - 360), num, font=big_f,
               fill=(255, 255, 255, 26))

    # ----- center caption -----
    if caption_text:
        font = _find_font(84)
        lines = _wrap(d, caption_text.upper(), font, VIDEO_WIDTH - 160)
        line_h = 100
        y = (VIDEO_HEIGHT - len(lines) * line_h) / 2 + 60
        for line in lines:
            w = d.textlength(line, font=font)
            d.text((cx - w / 2, y), line, font=font, fill=(255, 255, 255),
                   stroke_width=9, stroke_fill=(0, 0, 0))
            y += line_h

    # ----- outro CTA -----
    if label == "outro":
        cta_f = _find_font(48)
        _pill(d, "FOLGEN FÜR MEHR FILM-FAKTEN", cta_f, cx, VIDEO_HEIGHT - 470)

    img.save(path)
    return path


# ---------- background montage ----------

def _build_base_montage(clips: list[str], out_path: str) -> str:
    """Builds a varied base montage (~BASE_TARGET s) with fast cuts + zoom-push.

    Cycles through clips with varied start points so the same clip never shows the
    same moment twice; the renderer loops this base to fill the full video.
    """
    durations = {c: _probe_duration(c) for c in clips}
    clips = [c for c in clips if durations[c] >= 1.0] or clips

    n_segments = max(len(clips), math.ceil(BASE_TARGET / SEG))
    seg_frames = max(1, int(SEG * 30))
    zin = ZOOM_PER_SEG / seg_frames
    usage = {c: 0 for c in clips}

    inputs, filters, labels = [], [], []
    for i in range(n_segments):
        clip = clips[i % len(clips)]
        dur = durations.get(clip, 0) or SEG
        max_start = max(0.0, dur - SEG)
        start = (usage[clip] * SEG) % (max_start + 0.001) if max_start > 0 else 0.0
        usage[clip] += 1

        inputs += ["-ss", f"{start:.2f}", "-t", f"{SEG:.2f}", "-i", clip]
        if i % 2 == 0:
            zexpr = f"min(zoom+{zin:.5f},{1 + ZOOM_PER_SEG:.3f})"
        else:
            zexpr = f"if(eq(on,0),{1 + ZOOM_PER_SEG:.3f},max(zoom-{zin:.5f},1.0))"
        filters.append(
            f"[{i}:v]fps=30,"  # normalize fps FIRST so each segment is exactly SEG seconds
            f"scale={int(VIDEO_WIDTH*1.25)}:{int(VIDEO_HEIGHT*1.25)}:force_original_aspect_ratio=increase,"
            f"crop={int(VIDEO_WIDTH*1.25)}:{int(VIDEO_HEIGHT*1.25)},"
            f"zoompan=z='{zexpr}':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:fps=30,"
            f"setsar=1,format=yuv420p[v{i}]")
        labels.append(f"[v{i}]")

    concat = "".join(labels) + f"concat=n={n_segments}:v=1:a=0[bg]"
    cmd = ["ffmpeg", "-y"] + inputs + [
        "-filter_complex", ";".join(filters + [concat]), "-map", "[bg]",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-r", "30", "-an", "-threads", "0", out_path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"Montage failed:\n{r.stderr[-2000:]}")
    return out_path


# ---------- compose ----------

def render_video(content: dict, audio_path: str, sections: list[dict],
                 words: list[dict], output_path: str) -> str:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="tt_"))

    total = (max(s["end"] for s in sections) + 0.6) if sections else _probe_duration(audio_path)
    if total <= 0:
        total = 80.0

    # ----- background -----
    clips = fetch_background_clips(content.get("visual_tags", []), str(work / "clips"),
                                   count=12, orientation="portrait")
    if clips:
        base = _build_base_montage(clips, str(work / "base.mp4"))
        bg_input = ["-stream_loop", "-1", "-i", base]
        bg_filter = f"[0:v]scale={VIDEO_WIDTH}:{VIDEO_HEIGHT},setsar=1[bg]"
    else:
        grad = _gradient_png((10, 12, 28), (28, 30, 60), str(work / "grad.png"))
        bg_input = ["-loop", "1", "-t", f"{total:.2f}", "-i", grad]
        bg_filter = (
            f"[0:v]scale={int(VIDEO_WIDTH*1.2)}:{int(VIDEO_HEIGHT*1.2)},"
            f"crop={VIDEO_WIDTH}:{VIDEO_HEIGHT}:"
            f"x='(in_w-{VIDEO_WIDTH})/2+sin(t/5)*60':"
            f"y='(in_h-{VIDEO_HEIGHT})/2+cos(t/6)*60',setsar=1[bg]"
        )

    # ----- overlay track (scrim + branding + captions) as ONE timed image stream -----
    total_facts = len(content.get("facts", [])) or 5
    captions = _group_captions(words or [], sections or [], total=total)
    if not captions:
        captions = [{"text": "", "start": 0.0, "end": total, "label": "intro"}]

    frames = []
    for i, c in enumerate(captions):
        fact_idx = None
        if c["label"].startswith("fact_"):
            try:
                fact_idx = int(c["label"].split("_")[1])
            except (IndexError, ValueError):
                fact_idx = None
        p = _overlay_frame(content, c["label"], total_facts, fact_idx,
                           c["text"], str(work / f"ov_{i}.png"))
        dur = max(0.1, c["end"] - c["start"])
        frames.append((p, dur))

    # concat-demuxer list (last entry repeated so its duration applies)
    list_path = work / "frames.txt"
    lines = []
    for p, dur in frames:
        lines.append(f"file '{p}'")
        lines.append(f"duration {dur:.3f}")
    lines.append(f"file '{frames[-1][0]}'")  # required final repeat
    list_path.write_text("\n".join(lines))

    # ----- final compose: background + overlay track + audio (only 3 inputs) -----
    cmd = ["ffmpeg", "-y"] + bg_input
    cmd += ["-f", "concat", "-safe", "0", "-i", str(list_path)]   # 1: overlay frames
    cmd += ["-i", audio_path]                                     # 2: audio

    filter_complex = (
        bg_filter
        + ";[1:v]fps=30,format=rgba,setsar=1[ov]"
        + ";[bg][ov]overlay=eof_action=pass:format=auto[v]"
    )

    cmd += [
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "2:a",
        # veryfast+crf26 keeps the final file well under TikTok's 64MB single-chunk
        # limit while staying fast enough on GitHub's 2-core runner.
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-maxrate", "6M",
        "-bufsize", "12M", "-profile:v", "high", "-level", "4.1",
        "-c:a", "aac", "-b:a", "128k",
        "-pix_fmt", "yuv420p", "-r", "30", "-threads", "0",
        "-t", f"{total:.2f}", "-shortest",
        output_path,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{r.stderr[-2500:]}")
    return output_path


if __name__ == "__main__":
    from text_to_speech import build_narration
    sample = {
        "subject": "Inception", "kind": "Film", "category": "Sci-Fi",
        "title": "5 Fakten über Inception", "visual_tags": ["dream", "city", "spinning top"],
        "facts": [{"headline": f"Fakt {i}", "text": f"Test Fakt Nummer {i}."} for i in range(1, 6)],
    }
    segs = [("intro", "Inception hat ein Geheimnis das kaum jemand kennt.")]
    for i, f in enumerate(sample["facts"], 1):
        segs.append((f"fact_{i}", f"{f['headline']}. {f['text']}"))
    segs.append(("outro", "Welcher Fakt hat dich überrascht? Folge für mehr."))
    w, s = build_narration(segs, "/tmp/tt_audio.mp3")
    render_video(sample, "/tmp/tt_audio.mp3", s, w, "/tmp/tt_video.mp4")
    print("Video: /tmp/tt_video.mp4")
