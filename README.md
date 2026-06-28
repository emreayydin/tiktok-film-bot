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

## TikTok einrichten (einmalig)

1. **Developer-App** erstellen auf <https://developers.tiktok.com/> → neue App.
2. Produkt **"Content Posting API"** aktivieren, **Direct Post** einschalten.
3. Scopes hinzufügen: `user.info.basic`, `video.publish`.
4. Redirect-URI eintragen (TikTok verlangt HTTPS):
   `https://emreayydin.github.io/tiktok-film-bot/callback.html`
5. `TIKTOK_CLIENT_KEY` + `TIKTOK_CLIENT_SECRET` aus der App in `.env` setzen.
6. Einmalig anmelden, um den Refresh-Token zu holen:
   ```bash
   cd src && python upload_tiktok.py
   ```
   Browser öffnet sich → einloggen → der ausgegebene `refresh_token` kommt als
   GitHub-Secret `TIKTOK_REFRESH_TOKEN`.

### ⚠️ App-Audit (wichtig)
Eine **ungeprüfte** App darf nur **privat** posten (`SELF_ONLY`) — das Video liegt
sichtbar nur für dich auf deinem Profil. Erst nach dem **TikTok-Audit** der App
(im Developer-Portal beantragen) ist öffentliches Posten erlaubt. Danach
Repo-Variable `TIKTOK_PRIVACY=PUBLIC_TO_EVERYONE` setzen — der Bot postet dann
automatisch öffentlich. Der Code wählt automatisch die jeweils erlaubte Stufe.

## GitHub-Actions-Autopilot

Secrets im Repo (`Settings → Secrets and variables → Actions`):

- `ANTHROPIC_API_KEY`
- `PEXELS_API_KEY`
- `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `TIKTOK_REFRESH_TOKEN`
- optionale Variable `TIKTOK_PRIVACY` (Standard `SELF_ONLY`)

Der Workflow `daily_tiktok.yml` läuft 2×/Tag (17:00 & 21:00 Uhr DE) und committet
`history.json` zurück, damit kein Film doppelt vorkommt. Manueller Start +
Dry-Run über **Actions → Run workflow**.

## Wartung
- **TikTok-Refresh-Token** ist ~365 Tage gültig → einmal jährlich `python
  upload_tiktok.py` neu ausführen und Secret aktualisieren.
- Echte Filmausschnitte sind urheberrechtlich geschützt und werden NICHT
  automatisch genutzt — der Hintergrund ist generischer cinematischer B-Roll,
  passend zum Genre/Mood des jeweiligen Films.
