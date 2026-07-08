# TikTok Film & Serien Bot 🎬

Vollautomatischer deutscher TikTok-Kanal im Format **"5 Fakten über [Film/Serie]"**.
Claude schreibt das Skript → edge-tts spricht es → cinematische Pexels-Montage +
wortsynchrone Captions (Pillow + ffmpeg) → vertikales 9:16-Video (**> 1 Minute**) →
Upload über TikToks offizielle Content Posting API. Läuft auf GitHub-Actions-Autopilot.

Schwesterprojekt des YouTube-Shorts-Bots „Faktastisch", gleiche Bauweise.

## Pipeline

| Schritt | Datei |
|--------|-------|
| Skript (5 Fakten über einen Film/Serie) | `src/generate_content.py` |
| Sprachausgabe + Wort-Timing | `src/text_to_speech.py` |
| Hintergrund-Clips (Pexels, cinematisch) | `src/fetch_background.py` |
| Vertikaler Render (9:16, Captions, FAKT-Badges) | `src/render_video.py` |
| TikTok-Upload (Content Posting API) | `src/upload_tiktok.py` |
| Anti-Repeat-Verlauf | `src/history.py` |
| Orchestrierung | `src/main.py` |

## Lokales Setup

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# ffmpeg muss installiert sein (brew install ffmpeg)
```

`.env` anlegen:

```
ANTHROPIC_API_KEY=sk-ant-...
PEXELS_API_KEY=...
TIKTOK_CLIENT_KEY=...
TIKTOK_CLIENT_SECRET=...
TIKTOK_REFRESH_TOKEN=...     # via OAuth-Login (siehe unten)
```

Test ohne Upload:

```bash
cd src && python main.py --dry-run
```

## Öffentliches Posten via Postiz (empfohlener Weg)

TikTok erlaubt über die eigene Content Posting API **kein** vollautomatisches
öffentliches Posten für private Nutzung (Apps für Eigengebrauch werden abgelehnt).
Lösung: der Bot postet über **[Postiz](https://postiz.com)** — einen von TikTok
zugelassenen Scheduler. Du verbindest dein TikTok-Konto einmal in Postiz, der Bot
lädt die Videos per Postiz-CLI hoch und plant sie öffentlich.

**Einrichtung (einmalig):**
1. Konto auf <https://postiz.com> anlegen.
2. **Channels → Add channel → TikTok** → dein TikTok-Konto verbinden.
3. **Settings → API/Public API** → API-Key erzeugen.
4. Lokal: `export POSTIZ_API_KEY=...` (oder in `.env`), dann testen:
   ```bash
   npm install -g postiz
   cd src && python upload_postiz.py     # listet verbundene Kanäle
   python main.py                        # rendert + postet öffentlich via Postiz
   ```

Der Uploader ist umschaltbar: `--uploader postiz` (Standard, öffentlich) oder
`--uploader tiktok` (eigene TikTok-App, nur privat/Sandbox — siehe unten).

## GitHub-Actions-Autopilot

Secrets im Repo (`Settings → Secrets and variables → Actions`):

- `ANTHROPIC_API_KEY`
- `PEXELS_API_KEY`
- `POSTIZ_API_KEY`
- optionale Variablen: `POSTIZ_TIKTOK_ID` (sonst Auto-Discovery),
  `TIKTOK_PRIVACY` (Standard `PUBLIC_TO_EVERYONE`)

Der Workflow `daily_tiktok.yml` läuft 2×/Tag (17:00 & 21:00 Uhr DE), installiert
die Postiz-CLI, rendert + postet öffentlich und committet `history.json` zurück,
damit kein Film doppelt vorkommt. Manueller Start + Dry-Run über
**Actions → Run workflow**.

## Alternative: eigene TikTok-App (nur privat/Sandbox)

`src/upload_tiktok.py` postet direkt über eine eigene TikTok-App. Damit sind aber
nur **private** Videos möglich (`SELF_ONLY`), da TikTok Privat-Apps nicht für
öffentliches Posten freigibt. Nutzung: `--uploader tiktok`. OAuth-Login einmalig
via `python upload_tiktok.py` (Redirect-URI
`https://emreayydin.github.io/tiktok-film-bot/callback.html`).

## Wartung
- **Postiz-TikTok-Verbindung** gelegentlich prüfen (Token laufen ab → in Postiz
  neu verbinden).
- Echte Filmausschnitte sind urheberrechtlich geschützt und werden NICHT
  automatisch genutzt — der Hintergrund ist generischer cinematischer B-Roll,
  passend zum Genre/Mood des jeweiligen Films.
