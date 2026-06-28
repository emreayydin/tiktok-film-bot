"""Uploads a video to TikTok via the official Content Posting API (v2).

Flow used here (Direct Post, FILE_UPLOAD source):
  1. Refresh the long-lived refresh token into a short-lived access token.
  2. Query creator info (REQUIRED by TikTok before a direct post) to learn which
     privacy levels the account/app may use.
  3. init the post -> receive publish_id + upload_url.
  4. PUT the video bytes to upload_url (single or multi-chunk).
  5. Poll the publish status until it completes.

IMPORTANT — app audit: an UNAUDITED TikTok app can only post privately
(privacy_level = SELF_ONLY); the video lands on your profile visible to you only.
Once your app passes TikTok's audit, query_creator_info() will start returning
PUBLIC_TO_EVERYONE and the bot will post publicly automatically (set
TIKTOK_PRIVACY=PUBLIC_TO_EVERYONE). The code always picks the requested privacy
if it's allowed, otherwise the safest allowed option.

Secrets (env vars):
  TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET, TIKTOK_REFRESH_TOKEN
Run this file directly once locally to perform the OAuth login and obtain the
refresh token to store as the TIKTOK_REFRESH_TOKEN secret.
"""
import os
import json
import time
import requests
from pathlib import Path

API = "https://open.tiktokapis.com/v2"
AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = f"{API}/oauth/token/"

# video.publish = direct post; user.info.basic = required to query creator info
SCOPES = "user.info.basic,video.publish"
# TikTok requires an HTTPS redirect URI (http://localhost is rejected), so we use
# a static callback page on the already-verified GitHub Pages domain. The page just
# shows the login code for the user to paste back into this script.
REDIRECT_URI = os.environ.get(
    "TIKTOK_REDIRECT_URI",
    "https://emreayydin.github.io/tiktok-film-bot/callback.html")
TOKEN_FILE = Path(__file__).resolve().parent / "tiktok_token.json"

MAX_SINGLE_CHUNK = 64 * 1024 * 1024   # 64 MB — bigger files must be chunked
CHUNK_SIZE = 10 * 1024 * 1024         # 10 MB per chunk when chunking


# ---------------- access token ----------------

def get_access_token() -> str:
    """Exchanges the long-lived refresh token for a short-lived access token."""
    client_key = os.environ["TIKTOK_CLIENT_KEY"]
    client_secret = os.environ["TIKTOK_CLIENT_SECRET"]
    refresh_token = os.environ.get("TIKTOK_REFRESH_TOKEN")

    if not refresh_token and TOKEN_FILE.exists():
        refresh_token = json.loads(TOKEN_FILE.read_text()).get("refresh_token")
    if not refresh_token:
        raise RuntimeError("Kein TIKTOK_REFRESH_TOKEN gesetzt. Führe `python upload_tiktok.py` "
                           "einmal lokal aus, um dich anzumelden.")

    resp = requests.post(TOKEN_URL, headers={
        "Content-Type": "application/x-www-form-urlencoded",
    }, data={
        "client_key": client_key,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }, timeout=30)
    data = resp.json()
    if "access_token" not in data:
        raise RuntimeError(f"Token-Refresh fehlgeschlagen: {data}")

    # TikTok rotates the refresh token on each refresh — persist it locally so a
    # manual run never invalidates the secret unexpectedly.
    if data.get("refresh_token"):
        try:
            TOKEN_FILE.write_text(json.dumps(data, indent=2))
        except Exception:
            pass
    return data["access_token"]


# ---------------- creator info ----------------

def query_creator_info(access_token: str) -> dict:
    """Required before a direct post. Returns allowed privacy levels etc."""
    resp = requests.post(f"{API}/post/publish/creator_info/query/", headers={
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
    }, timeout=30)
    data = resp.json()
    if data.get("error", {}).get("code") not in (None, "ok"):
        raise RuntimeError(f"creator_info fehlgeschlagen: {data}")
    return data.get("data", {})


def _pick_privacy(requested: str, options: list[str]) -> str:
    if requested in options:
        return requested
    for safe in ("SELF_ONLY", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR",
                 "PUBLIC_TO_EVERYONE"):
        if safe in options:
            return safe
    return options[0] if options else "SELF_ONLY"


# ---------------- upload ----------------

def upload_video(video_path: str, caption: str,
                 privacy: str = None) -> str:
    """Direct-posts a video. Returns the publish_id. Raises on failure."""
    access_token = get_access_token()
    info = query_creator_info(access_token)
    options = info.get("privacy_level_options", []) or ["SELF_ONLY"]

    requested = privacy or os.environ.get("TIKTOK_PRIVACY", "SELF_ONLY")
    privacy_level = _pick_privacy(requested, options)
    print(f"Privacy: {privacy_level} (erlaubt: {options})")

    size = os.path.getsize(video_path)
    if size <= MAX_SINGLE_CHUNK:
        chunk_size, total_chunks = size, 1
    else:
        chunk_size = CHUNK_SIZE
        total_chunks = size // chunk_size  # last chunk absorbs the remainder

    init_body = {
        "post_info": {
            "title": caption[:2200],
            "privacy_level": privacy_level,
            "disable_duet": False,
            "disable_comment": False,
            "disable_stitch": False,
            "video_cover_timestamp_ms": 1000,
        },
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": size,
            "chunk_size": chunk_size,
            "total_chunk_count": total_chunks,
        },
    }
    resp = requests.post(f"{API}/post/publish/video/init/", headers={
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
    }, data=json.dumps(init_body), timeout=30)
    data = resp.json()
    if data.get("error", {}).get("code") not in (None, "ok"):
        raise RuntimeError(f"init fehlgeschlagen: {data}")

    publish_id = data["data"]["publish_id"]
    upload_url = data["data"]["upload_url"]
    print(f"Init OK, publish_id={publish_id}")

    _put_chunks(upload_url, video_path, size, chunk_size, total_chunks)
    _wait_for_publish(access_token, publish_id)
    return publish_id


def _put_chunks(upload_url, video_path, size, chunk_size, total_chunks):
    with open(video_path, "rb") as f:
        for i in range(total_chunks):
            start = i * chunk_size
            # last chunk takes everything that's left
            end = size - 1 if i == total_chunks - 1 else start + chunk_size - 1
            f.seek(start)
            chunk = f.read(end - start + 1)
            headers = {
                "Content-Type": "video/mp4",
                "Content-Length": str(len(chunk)),
                "Content-Range": f"bytes {start}-{end}/{size}",
            }
            r = requests.put(upload_url, headers=headers, data=chunk, timeout=300)
            if r.status_code not in (200, 201, 206):
                raise RuntimeError(f"Chunk-Upload {i+1}/{total_chunks} fehlgeschlagen: "
                                   f"{r.status_code} {r.text[:300]}")
            print(f"Chunk {i+1}/{total_chunks} hochgeladen ({r.status_code})")


def _wait_for_publish(access_token, publish_id, timeout=300):
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = requests.post(f"{API}/post/publish/status/fetch/", headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        }, data=json.dumps({"publish_id": publish_id}), timeout=30)
        data = resp.json().get("data", {})
        status = data.get("status")
        print(f"Status: {status}")
        if status in ("PUBLISH_COMPLETE", "SEND_TO_USER_INBOX"):
            return
        if status in ("FAILED",):
            raise RuntimeError(f"Veröffentlichung fehlgeschlagen: {data}")
        time.sleep(5)
    print("Hinweis: Zeitlimit beim Status-Polling erreicht — Upload läuft ggf. noch weiter.")


# ---------------- one-time local OAuth ----------------

def authorize():
    """One-time OAuth flow to obtain the long-lived refresh token.

    Opens the TikTok login in the browser; after approving, the browser lands on
    the HTTPS callback page (GitHub Pages) which shows the login code. Paste that
    code back here and it's exchanged for the refresh token.
    """
    import secrets
    import urllib.parse
    import webbrowser

    client_key = os.environ["TIKTOK_CLIENT_KEY"]
    client_secret = os.environ["TIKTOK_CLIENT_SECRET"]
    state = secrets.token_urlsafe(16)

    params = urllib.parse.urlencode({
        "client_key": client_key,
        "scope": SCOPES,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "state": state,
    })
    url = f"{AUTH_URL}?{params}"
    print(f"\nÖffne im Browser zum Anmelden:\n{url}\n")
    webbrowser.open(url)

    code = input("Füge hier den Code von der Callback-Seite ein und drücke Enter:\n> ").strip()
    if not code:
        raise RuntimeError("Kein Code eingegeben.")
    # TikTok URL-encodes the code (it often ends with '*' as %2A) — normalize it.
    code = urllib.parse.unquote(code)

    resp = requests.post(TOKEN_URL, headers={
        "Content-Type": "application/x-www-form-urlencoded",
    }, data={
        "client_key": client_key,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
    }, timeout=30)
    data = resp.json()
    if "refresh_token" not in data:
        raise RuntimeError(f"Token-Austausch fehlgeschlagen: {data}")

    TOKEN_FILE.write_text(json.dumps(data, indent=2))
    print(f"\nGespeichert in {TOKEN_FILE}")
    print("\nFüge diesen Wert als GitHub-Secret TIKTOK_REFRESH_TOKEN hinzu:\n")
    print(data["refresh_token"])
    print(f"\n(refresh_token gültig ~{data.get('refresh_expires_in', 0)//86400} Tage)")


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    except ImportError:
        pass
    authorize()
