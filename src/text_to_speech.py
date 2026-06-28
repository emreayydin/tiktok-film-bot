"""Text to speech via edge-tts (free Microsoft neural voices).

Also extracts word-level timing (WordBoundary events) so the video renderer can
draw animated captions synced to the voice.
"""
import asyncio
import subprocess
import tempfile
import edge_tts
from pathlib import Path


# German neural voices (natural-sounding)
VOICES = [
    "de-DE-KillianNeural",   # male, deep
    "de-DE-ConradNeural",    # male, clear
    "de-DE-AmalaNeural",     # female, clear
]


async def _synthesize(text: str, output_path: str, voice: str, rate: str):
    """Streams TTS, saving audio and collecting word timings."""
    communicate = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
    words = []
    with open(output_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                # offset/duration are in 100-nanosecond ticks
                start = chunk["offset"] / 10_000_000
                duration = chunk["duration"] / 10_000_000
                words.append({
                    "text": chunk["text"],
                    "start": start,
                    "end": start + duration,
                })
    return words


def generate_audio(text: str, output_path: str, voice: str = VOICES[0], rate: str = "+8%"):
    """
    Generates an MP3 and returns word-level timing.
    Returns: list of {"text", "start", "end"} dicts.
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    return asyncio.run(_synthesize(text, output_path, voice, rate))


def _probe_duration(path: str) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path],
        capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def build_narration(segments: list[tuple[str, str]], output_path: str,
                    voice: str = VOICES[0], rate: str = "+8%") -> tuple[list[dict], list[dict]]:
    """
    Synthesizes multiple labelled text segments into one audio file.

    segments: list of (label, text) — e.g. [("intro", "..."), ("fact_1", "..."), ...]
    Returns (words, sections):
      words    = global word timings [{text, start, end}] across the whole audio
      sections = [{label, start, end}] marking where each segment plays
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="narr_"))

    seg_files, words, sections = [], [], []
    offset = 0.0
    for i, (label, text) in enumerate(segments):
        seg_path = str(work / f"seg_{i}.mp3")
        seg_words = generate_audio(text, seg_path, voice=voice, rate=rate)
        dur = _probe_duration(seg_path)
        if dur <= 0 and seg_words:
            dur = max(w["end"] for w in seg_words) + 0.3

        for w in seg_words:
            words.append({"text": w["text"],
                          "start": w["start"] + offset,
                          "end": w["end"] + offset})
        sections.append({"label": label, "start": offset, "end": offset + dur})
        seg_files.append(seg_path)
        offset += dur

    # Concatenate all segment audios into one track
    inputs = []
    for f in seg_files:
        inputs += ["-i", f]
    n = len(seg_files)
    filt = "".join(f"[{i}:a]" for i in range(n)) + f"concat=n={n}:v=0:a=1[a]"
    cmd = ["ffmpeg", "-y"] + inputs + [
        "-filter_complex", filt, "-map", "[a]",
        "-c:a", "libmp3lame", "-b:a", "192k", output_path,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"Audio-Concat fehlgeschlagen:\n{r.stderr[-1500:]}")

    return words, sections


if __name__ == "__main__":
    words = generate_audio(
        "Christopher Nolan drehte die rotierende Flur-Szene in einem echten Kreisel-Set.",
        "/tmp/test_audio.mp3",
    )
    print(f"{len(words)} Wörter mit Timing erfasst")
    for w in words[:5]:
        print(f"  {w['start']:.2f}s - {w['end']:.2f}s: {w['text']}")
