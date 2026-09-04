"""Spotify Web API OAuth PKCE — Whick 검색·재생 (librespot Connect 디바이스)."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

from api import streaming_providers

SPOTIFY_CLIENT_ID = os.getenv("WHICK_SPOTIFY_CLIENT_ID", "").strip()
SPOTIFY_REDIRECT_URI = os.getenv(
    "WHICK_SPOTIFY_REDIRECT_URI",
    "http://127.0.0.1:8080/api/streaming/spotify/oauth/callback",
).strip()
SPOTIFY_SCOPES = os.getenv(
    "WHICK_SPOTIFY_SCOPES",
    "user-read-private user-read-playback-state user-modify-playback-state "
    "user-read-currently-playing",
)
OAUTH_PENDING = streaming_providers.PROVIDERS_DIR / "spotify-oauth-pending.json"
AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"


def oauth_configured() -> bool:
    return bool(SPOTIFY_CLIENT_ID)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _pkce_pair() -> tuple[str, str]:
    verifier = _b64url(secrets.token_bytes(32))
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge


def _load_pending() -> dict[str, Any]:
    if not OAUTH_PENDING.is_file():
        return {}
    try:
        return json.loads(OAUTH_PENDING.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_pending(data: dict[str, Any]) -> None:
    streaming_providers._ensure_dir()
    OAUTH_PENDING.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def web_api_connected() -> bool:
    from api import streaming_playback

    creds = streaming_playback._load_json(streaming_playback.SPOTIFY_CREDS)
    token = str(creds.get("access_token") or "")
    if not token or token == "lab-access-token":
        return False
    return True


def oauth_status() -> dict[str, Any]:
    pending = _load_pending()
    return {
        "oauth_available": oauth_configured(),
        "web_api_connected": web_api_connected(),
        "redirect_uri": SPOTIFY_REDIRECT_URI if oauth_configured() else None,
        "pending": bool(pending.get("state")),
    }


def oauth_start() -> dict[str, Any]:
    if not oauth_configured():
        return {
            "ok": False,
            "error": "WHICK_SPOTIFY_CLIENT_ID 미설정 — Spotify Developer Dashboard 앱 등록 필요",
        }
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)
    _save_pending(
        {
            "state": state,
            "code_verifier": verifier,
            "created_at": time.time(),
        }
    )
    params = {
        "client_id": SPOTIFY_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": SPOTIFY_REDIRECT_URI,
        "scope": SPOTIFY_SCOPES,
        "state": state,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
    }
    return {
        "ok": True,
        "auth_url": f"{AUTH_URL}?{urlencode(params)}",
        "state": state,
        "redirect_uri": SPOTIFY_REDIRECT_URI,
        "steps": [
            "아래 「Spotify 로그인」을 눌러 브라우저에서 승인하세요",
            "로그인 후 이 미니PC 주소로 자동 돌아옵니다",
            "완료되면 Whick에서 검색·재생이 가능합니다",
        ],
    }


async def _exchange_code(code: str, verifier: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": SPOTIFY_REDIRECT_URI,
                "client_id": SPOTIFY_CLIENT_ID,
                "code_verifier": verifier,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code >= 400:
            detail = resp.text[:300]
            raise ValueError(f"Spotify token exchange failed ({resp.status_code}): {detail}")
        return resp.json()


async def oauth_callback(code: str, state: str) -> tuple[bool, str]:
    pending = _load_pending()
    if not pending or pending.get("state") != state:
        return False, "OAuth state 불일치 — 연결 시작부터 다시 시도하세요"
    verifier = str(pending.get("code_verifier") or "")
    if not verifier:
        return False, "OAuth verifier 없음"
    try:
        token = await _exchange_code(code, verifier)
    except ValueError as exc:
        return False, str(exc)
    from api import streaming_playback

    streaming_playback.store_spotify_web_token(
        str(token.get("access_token") or ""),
        refresh_token=str(token.get("refresh_token") or ""),
        expires_in=int(token.get("expires_in") or 3600),
    )
    OAUTH_PENDING.unlink(missing_ok=True)
    return True, "Spotify Web API 연결 완료 · Whick 검색·재생을 사용할 수 있습니다"


async def refresh_access_token() -> str | None:
    from api import streaming_playback

    creds = streaming_playback._load_json(streaming_playback.SPOTIFY_CREDS)
    refresh = str(creds.get("refresh_token") or "")
    if not refresh or not oauth_configured():
        return None
    stored_at = creds.get("stored_at")
    expires_in = int(creds.get("expires_in") or 3600)
    if stored_at and creds.get("access_token"):
        try:
            from datetime import datetime

            ts = datetime.fromisoformat(str(stored_at).replace("Z", "+00:00")).timestamp()
            if time.time() < ts + expires_in - 120:
                return str(creds["access_token"])
        except (TypeError, ValueError):
            pass
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh,
                "client_id": SPOTIFY_CLIENT_ID,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code >= 400:
            return None
        data = resp.json()
        access = str(data.get("access_token") or "")
        if not access:
            return None
        streaming_playback.store_spotify_web_token(
            access,
            refresh_token=str(data.get("refresh_token") or refresh),
            expires_in=int(data.get("expires_in") or 3600),
        )
        return access


def oauth_success_html(message: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Whick · Spotify</title>
<style>body{{font-family:system-ui,sans-serif;background:#0b0b0f;color:#eee;display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0;padding:24px}}
.card{{max-width:420px;background:#16161d;border-radius:16px;padding:28px;text-align:center;border:1px solid #2a2a35}}
.ok{{color:#1DB954;font-size:2rem;margin-bottom:12px}}p{{line-height:1.5;color:#bbb}}</style></head>
<body><div class="card"><div class="ok">✓</div><h1>Spotify 연결됨</h1><p>{message}</p><p>Whick 리모컨으로 돌아가 검색·재생을 시도하세요.</p></div></body></html>"""


def oauth_error_html(message: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Whick · Spotify</title>
<style>body{{font-family:system-ui,sans-serif;background:#0b0b0f;color:#eee;display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0;padding:24px}}
.card{{max-width:420px;background:#16161d;border-radius:16px;padding:28px;text-align:center;border:1px solid #3a2020}}
.err{{color:#ff6b6b;font-size:2rem;margin-bottom:12px}}p{{line-height:1.5;color:#bbb}}</style></head>
<body><div class="card"><div class="err">✗</div><h1>연결 실패</h1><p>{message}</p><p>Whick 리모컨 → Spotify 연결에서 다시 시도하세요.</p></div></body></html>"""
