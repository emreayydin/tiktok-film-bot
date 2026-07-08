"""Generates a "5 Fakten über [Film/Serie]" script for a vertical TikTok video.

Uses Claude with the web-search tool to pick a film/series that is CURRENTLY hyped
(new releases, Netflix top 10, viral shows) so the video rides existing attention.
Output is structured into intro + 5 facts + outro so the narration runs ~80-110s.
"""
import anthropic
import json
import random
from datetime import datetime

MODEL = "claude-sonnet-4-6"

# Genres used only as a soft hint / for the no-web fallback
CATEGORIES = [
    "Blockbuster", "Sci-Fi", "Horror", "Marvel & Superhelden", "Animation & Disney",
    "Netflix-Serien", "Krimi & Thriller", "Fantasy", "Kult-Klassiker", "Action",
]
DEFAULT_VISUALS = ["cinema", "film reel", "movie theater", "spotlight", "popcorn cinematic"]


_RULES = """Erstelle ein Skript im Format "5 Fakten über [Titel]". Es muss FESSELND,
faktisch korrekt und überraschend sein — echte Behind-the-Scenes-Fakten, Trivia,
Easter Eggs, Dreh-Anekdoten oder verblüffende Hintergründe.

HOOK (intro) — die ersten 2 Sekunden entscheiden über alles:
- Max 25 Wörter, sofortiger Pattern-Interrupt (schockierende Zahl, scheinbarer
  Widerspruch, "Niemand hat gemerkt, dass…"), nenne den Titel
- Kündige den stärksten Fakt an ("Der letzte Fakt lässt dich [Titel] neu sehen")
- Niemals "Wusstest du?"

FAKTEN — genau 5 Stück:
- Jeder Fakt 35-55 Wörter, kurze gesprochene Sätze, sofort auf den Punkt
- Überraschend & wahr; nach Wucht sortiert — der KRASSESTE Fakt kommt ZULETZT
- "headline" = knackige Überschrift (max 38 Zeichen)

OUTRO — max 25 Wörter: eine zugespitzte Frage, die zum KOMMENTIEREN provoziert
(z.B. "Welcher Fakt war für dich neu? Schreib die Nummer!") + "Folge für mehr".

Sprache: Deutsch, direkte Ansprache (du).

WICHTIG für gültiges JSON: KEINE doppelten Anführungszeichen (") in den Texten —
nutze einfache (') oder keine. Keine Zeilenumbrüche in Werten.

Antworte am ENDE mit NUR EINEM JSON-Objekt (keine Erklärung danach):
{{
  "subject": "Exakter Film-/Serientitel",
  "kind": "Film" oder "Serie",
  "title": "Clickbait-Titel mit dem Titel, max 70 Zeichen",
  "intro": "Hook-Text",
  "facts": [{{"headline": "kurze Überschrift", "text": "Fakt-Text 35-55 Wörter"}}],
  "outro": "Outro-Text",
  "tags": ["film","serie","kino","tag4","tag5"],
  "visual_tags": ["englische","pexels","suchbegriffe","zum","mood"],
  "category": "Genre"
}}
Die "facts"-Liste muss GENAU 5 Einträge haben."""

TREND_PROMPT = """Du bist Autor für virale TikTok-Videos im Bereich Film & Serien (deutscher Kanal).

Suche zuerst im Web, welche Filme und Serien GERADE JETZT (Stand {date}) besonders
angesagt/gehypt sind — z.B. aktuelle Netflix/Prime/Disney+ Top 10 in Deutschland,
neue Kinostarts, gerade virale Serien. Wähle daraus EINEN populären Titel, der
möglichst viel aktuelle Aufmerksamkeit hat.
{avoid}
{rules}"""

PLAIN_PROMPT = """Du bist Autor für virale TikTok-Videos im Bereich Film & Serien (deutscher Kanal).

Wähle EINEN bekannten, populären Film oder EINE Serie aus dem Bereich: {category}
{avoid}
{rules}"""


def _extract_json(text: str) -> dict:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("Kein JSON in der Antwort gefunden")
    return json.loads(text[start:end + 1])


def _text_blocks(message) -> str:
    """Concatenates all text blocks of a (possibly tool-using) response."""
    parts = [b.text for b in message.content if getattr(b, "type", None) == "text"]
    return "\n".join(parts).strip()


def _finalize(data: dict, category: str) -> dict:
    data.setdefault("category", category or "Film & Serien")
    if not data.get("visual_tags"):
        data["visual_tags"] = DEFAULT_VISUALS
    return data


def generate_content(category: str = None, avoid: list[str] = None, attempts: int = 3) -> dict:
    from history import avoid_block
    client = anthropic.Anthropic()
    avoid_txt = avoid_block(avoid or [])
    date_str = datetime.now().strftime("%d.%m.%Y")
    last_err = None

    # --- Preferred: web search for currently trending titles ---
    prompt = TREND_PROMPT.format(date=date_str, avoid=avoid_txt, rules=_RULES)
    for attempt in range(attempts):
        try:
            msg = client.messages.create(
                model=MODEL,
                max_tokens=2500,
                tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 4}],
                messages=[{"role": "user", "content": prompt}],
            )
            data = _extract_json(_text_blocks(msg))
            if not data.get("facts") or len(data["facts"]) < 3:
                raise ValueError("Zu wenige Fakten")
            print(f"[web] Aktueller Titel gewählt: {data.get('subject')}")
            return _finalize(data, category)
        except Exception as e:  # web search unavailable / bad JSON -> fall back
            last_err = e
            print(f"Web-Trend-Versuch {attempt + 1}/{attempts} fehlgeschlagen: {e}")

    # --- Fallback: no web search, genre-based pick ---
    print("Fallback: ohne Web-Suche, zufälliges Genre.")
    cat = category or random.choice(CATEGORIES)
    prompt = PLAIN_PROMPT.format(category=cat, avoid=avoid_txt, rules=_RULES)
    for attempt in range(attempts):
        try:
            msg = client.messages.create(
                model=MODEL, max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            )
            data = _extract_json(_text_blocks(msg))
            if not data.get("facts") or len(data["facts"]) < 3:
                raise ValueError("Zu wenige Fakten")
            return _finalize(data, cat)
        except Exception as e:
            last_err = e
            print(f"Fallback-Versuch {attempt + 1}/{attempts} fehlgeschlagen: {e}")

    raise RuntimeError(f"Konnte kein gültiges Skript erzeugen: {last_err}")


if __name__ == "__main__":
    c = generate_content()
    print(f"Titel: {c['title']}  ({c['kind']}: {c['subject']})")
    for i, f in enumerate(c["facts"], 1):
        print(f"  {i}. {f['headline']}")
