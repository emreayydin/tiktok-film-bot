"""Generates a "5 Fakten über [Film/Serie]" script for a vertical TikTok video.

Output is structured into intro + 5 facts + outro so the narration runs ~80-110s
(comfortably over TikTok's 1-minute threshold) and the renderer can show a
"FAKT n/5" badge per section.
"""
import anthropic
import json
import random


# Genres / buckets used to steer the model toward variety
CATEGORIES = [
    "Blockbuster", "Sci-Fi", "Horror", "Marvel & Superhelden", "Animation & Disney",
    "Netflix-Serien", "Krimi & Thriller", "Fantasy", "Kult-Klassiker", "Action",
    "Comedy", "Drama-Serien",
]

# English Pexels search terms used as a fallback when the model gives none,
# keyed loosely by genre so the cinematic b-roll fits the mood.
GENRE_VISUALS = {
    "Sci-Fi": ["space", "futuristic city", "neon technology", "galaxy", "spaceship"],
    "Horror": ["dark forest", "abandoned house", "fog night", "candle dark", "storm"],
    "Marvel & Superhelden": ["city skyline", "explosion", "lightning", "skyscraper", "action"],
    "Animation & Disney": ["fairytale castle", "magic sparkle", "colorful clouds", "fantasy", "stars"],
    "Netflix-Serien": ["city night", "suburban street", "rain window", "cinematic room", "neon"],
    "Krimi & Thriller": ["dark alley", "rain city night", "police lights", "shadow", "detective"],
    "Fantasy": ["epic mountains", "ancient castle", "misty forest", "dragon fire", "medieval"],
    "Kult-Klassiker": ["old cinema", "film reel", "vintage", "retro projector", "spotlight"],
    "Action": ["explosion", "car chase", "fire", "helicopter", "city action"],
    "Comedy": ["confetti", "party lights", "colorful", "bright city", "fun"],
    "Drama-Serien": ["cinematic room", "rain window", "city dusk", "empty street", "sunset"],
    "Blockbuster": ["cinema", "red carpet", "movie premiere", "spotlight", "film reel"],
}
DEFAULT_VISUALS = ["cinema", "film reel", "movie theater", "spotlight", "popcorn cinematic"]


PROMPT_TEMPLATE = """Du bist Autor für virale TikTok-Videos im Bereich Film & Serien (deutscher Kanal).

Wähle EINEN bekannten Film oder EINE bekannte Serie aus dem Bereich: {category}
{avoid}
Erstelle dazu ein Skript im Format "5 Fakten über [Titel]". Es muss FESSELND, faktisch
korrekt und überraschend sein — echte Behind-the-Scenes-Fakten, Trivia, Easter Eggs,
Dreh-Anekdoten oder verblüffende Hintergründe, die echte Fans noch nicht alle kennen.

HOOK (intro) — die ersten 2 Sekunden entscheiden:
- Max 30 Wörter, sofortiger Pattern-Interrupt, erzeugt eine Wissenslücke
- Nenne den Titel im Hook, niemals "Wusstest du?"

FAKTEN — genau 5 Stück:
- Jeder Fakt 35-55 Wörter, in kurzen gesprochenen Sätzen, sofort auf den Punkt
- Überraschend & wahr; steigere die Spannung, der stärkste Fakt zuletzt
- "headline" = knackige Überschrift (max 38 Zeichen)

OUTRO — max 25 Wörter: Frage an die Zuschauer + Aufruf zu Folgen/Kommentieren.

Sprache: Deutsch, direkte Ansprache (du).

WICHTIG für gültiges JSON: KEINE doppelten Anführungszeichen (") innerhalb der Texte —
nutze einfache (') oder keine. Keine Zeilenumbrüche in Werten.

Antworte NUR mit einem JSON-Objekt (keine Erklärung, kein Markdown):
{{
  "subject": "Exakter Film-/Serientitel",
  "kind": "Film" oder "Serie",
  "title": "Clickbait-Titel mit dem Titel, max 70 Zeichen",
  "intro": "Hook-Text",
  "facts": [
    {{"headline": "kurze Überschrift", "text": "Fakt-Text 35-55 Wörter"}}
  ],
  "outro": "Outro-Text",
  "tags": ["film","serie","kino","tag4","tag5"],
  "visual_tags": ["englische","pexels","suchbegriffe","zum","mood"],
  "category": "{category}"
}}

Die "facts"-Liste muss GENAU 5 Einträge haben."""


def generate_content(category: str = None, avoid: list[str] = None, attempts: int = 3) -> dict:
    if category is None:
        category = random.choice(CATEGORIES)

    from history import avoid_block
    prompt = PROMPT_TEMPLATE.format(category=category, avoid=avoid_block(avoid or []))

    client = anthropic.Anthropic()
    last_err = None
    for attempt in range(attempts):
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        try:
            data = json.loads(raw.strip())
            if not data.get("facts") or len(data["facts"]) < 3:
                raise ValueError("Zu wenige Fakten generiert")
            data.setdefault("category", category)
            if not data.get("visual_tags"):
                data["visual_tags"] = GENRE_VISUALS.get(category, DEFAULT_VISUALS)
            return data
        except (json.JSONDecodeError, ValueError) as e:
            last_err = e
            print(f"Antwort ungültig (Versuch {attempt + 1}/{attempts}): {e} — wiederhole...")

    raise RuntimeError(f"Konnte nach {attempts} Versuchen kein gültiges Skript erzeugen: {last_err}")


if __name__ == "__main__":
    c = generate_content()
    print(f"Titel: {c['title']}  ({c['kind']}: {c['subject']})")
    for i, f in enumerate(c["facts"], 1):
        print(f"  {i}. {f['headline']}")
