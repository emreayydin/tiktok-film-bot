"""Persistent history of posted videos so the bot never repeats a film/series.

Stored as history.json in the repo root and committed back after each run by the
GitHub Actions workflow, so every run sees what previous runs already produced.
"""
import json
from pathlib import Path
from datetime import datetime

HISTORY_FILE = Path(__file__).resolve().parent.parent / "history.json"


def _load() -> list[dict]:
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text())
        except Exception:
            return []
    return []


def recent_titles(n: int = 60) -> list[str]:
    """Returns the subjects/titles of the last `n` posted videos."""
    items = _load()
    out = []
    for x in items[-n:]:
        # prefer the concrete film/series subject, fall back to the title
        val = x.get("subject") or x.get("title")
        if val:
            out.append(val)
    return out


def add_entry(subject: str, title: str, category: str = "") -> None:
    """Appends a posted item. Keeps the last 1000."""
    items = _load()
    items.append({
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "category": category,
        "subject": subject,
        "title": title,
    })
    HISTORY_FILE.write_text(json.dumps(items[-1000:], ensure_ascii=False, indent=2))


def avoid_block(titles: list[str]) -> str:
    """Builds a prompt snippet telling the model which films/series to avoid."""
    if not titles:
        return ""
    joined = "\n".join(f"- {t}" for t in titles[-40:])
    return ("\n\nDIESE FILME/SERIEN GAB ES SCHON — wähle einen KOMPLETT anderen Titel "
            f"(kein bereits behandelter Film, keine andere Staffel davon):\n{joined}\n")
