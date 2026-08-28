"""YouTube Data API v3 — OAuth2 연동, 업로드, 공개."""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.settings_service import get_setting, set_setting
from app.services.workflow_service import find_project_assets

YOUTUBE_SCOPES = (
    "https://www.googleapis.com/auth/youtube.upload "
    "https://www.googleapis.com/auth/youtube.readonly"
)
OAUTH_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
YOUTUBE_API = "https://www.googleapis.com/youtube/v3"
YOUTUBE_UPLOAD = "https://www.googleapis.com/upload/youtube/v3/videos"

SETTING_CLIENT_ID = "youtube_client_id"
SETTING_CLIENT_SECRET = "youtube_client_secret"
SETTING_REFRESH_TOKEN = "youtube_refresh_token"
SETTING_ACCESS_TOKEN = "youtube_access_token"
SETTING_TOKEN_EXPIRY = "youtube_token_expiry"
SETTING_CHANNEL_ID = "youtube_channel_id"
SETTING_CHANNEL_TITLE = "youtube_channel_title"
SETTING_OAUTH_STATE = "youtube_oauth_state"
SETTING_REDIRECT_HOST = "youtube_redirect_host"  # localhost | 127.0.0.1

VIDEO_ID_FILE = "youtube_video_id.txt"
META_FILE = "youtube_upload.json"


def redirect_uri(host: str | None = None) -> str:
    h = host or "127.0.0.1"
    return f"http://{h}:{settings.port}/api/youtube/callback"


async def get_redirect_host(db: AsyncSession) -> str:
    stored = await get_setting(db, SETTING_REDIRECT_HOST)
    if stored in ("localhost", "127.0.0.1"):
        return stored
    return "127.0.0.1"


async def get_youtube_public_status(db: AsyncSession) -> dict[str, Any]:
    client_id = await get_setting(db, SETTING_CLIENT_ID)
    client_secret = await get_setting(db, SETTING_CLIENT_SECRET)
    refresh = await get_setting(db, SETTING_REFRESH_TOKEN)
    channel_title = await get_setting(db, SETTING_CHANNEL_TITLE)
    channel_id = await get_setting(db, SETTING_CHANNEL_ID)
    redirect_host = await get_redirect_host(db)
    return {
        "client_id": client_id,
        "client_secret_set": bool(client_secret),
        "client_secret_masked": _mask(client_secret),
        "connected": bool(refresh),
        "channel_title": channel_title or None,
        "channel_id": channel_id or None,
        "redirect_uri": redirect_uri(redirect_host),
        "redirect_host": redirect_host,
        "redirect_uris_hint": [
            redirect_uri("127.0.0.1"),
            redirect_uri("localhost"),
        ],
    }


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "****"
    return "****" + value[-4:]


async def build_auth_url(db: AsyncSession) -> str:
    client_id = await get_setting(db, SETTING_CLIENT_ID)
    client_secret = await get_setting(db, SETTING_CLIENT_SECRET)
    if not client_id or not client_secret:
        raise ValueError("YouTube OAuth 클라이언트 ID와 보안 비밀을 먼저 저장하세요.")

    state = secrets.token_urlsafe(24)
    await set_setting(db, SETTING_OAUTH_STATE, state)
    redirect_host = await get_redirect_host(db)
    redirect = redirect_uri(redirect_host)

    params = {
        "client_id": client_id,
        "redirect_uri": redirect,
        "response_type": "code",
        "scope": YOUTUBE_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"{OAUTH_AUTH_URL}?{urlencode(params)}"


async def handle_oauth_callback(db: AsyncSession, code: str, state: str) -> dict[str, str]:
    saved_state = await get_setting(db, SETTING_OAUTH_STATE)
    if not saved_state or saved_state != state:
        raise ValueError("OAuth state가 일치하지 않습니다. 다시 연결해 주세요.")

    client_id = await get_setting(db, SETTING_CLIENT_ID)
    client_secret = await get_setting(db, SETTING_CLIENT_SECRET)
    redirect_host = await get_redirect_host(db)
    redirect = redirect_uri(redirect_host)

    async with httpx.AsyncClient(timeout=30.0) as client:
        token_resp = await client.post(
            OAUTH_TOKEN_URL,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect,
                "grant_type": "authorization_code",
            },
        )
        if token_resp.status_code != 200:
            detail = token_resp.text[:300]
            raise ValueError(f"토큰 발급 실패: {detail}")

        tokens = token_resp.json()
        refresh_token = tokens.get("refresh_token")
        access_token = tokens.get("access_token")
        expires_in = int(tokens.get("expires_in", 3600))

        if not refresh_token:
            raise ValueError(
                "refresh token을 받지 못했습니다. Google 계정 연결을 해제한 뒤 "
                "다시 연결하거나 prompt=consent로 재시도하세요."
            )

        await set_setting(db, SETTING_REFRESH_TOKEN, refresh_token)
        await _store_access_token(db, access_token, expires_in)

        channel = await _fetch_my_channel(access_token)
        if channel:
            await set_setting(db, SETTING_CHANNEL_ID, channel["id"])
            await set_setting(db, SETTING_CHANNEL_TITLE, channel["title"])

        await set_setting(db, SETTING_OAUTH_STATE, "")

    return {
        "channel_title": channel["title"] if channel else "",
        "channel_id": channel["id"] if channel else "",
    }


async def disconnect_youtube(db: AsyncSession) -> None:
    for key in (
        SETTING_REFRESH_TOKEN,
        SETTING_ACCESS_TOKEN,
        SETTING_TOKEN_EXPIRY,
        SETTING_CHANNEL_ID,
        SETTING_CHANNEL_TITLE,
        SETTING_OAUTH_STATE,
    ):
        await set_setting(db, key, "")


async def _store_access_token(db: AsyncSession, access_token: str, expires_in: int) -> None:
    expiry = datetime.now(timezone.utc) + timedelta(seconds=max(expires_in - 60, 60))
    await set_setting(db, SETTING_ACCESS_TOKEN, access_token)
    await set_setting(db, SETTING_TOKEN_EXPIRY, expiry.isoformat())


async def get_access_token(db: AsyncSession) -> str:
    refresh_token = await get_setting(db, SETTING_REFRESH_TOKEN)
    if not refresh_token:
        raise ValueError("YouTube 채널이 연결되어 있지 않습니다. 설정에서 연결하세요.")

    access_token = await get_setting(db, SETTING_ACCESS_TOKEN)
    expiry_raw = await get_setting(db, SETTING_TOKEN_EXPIRY)
    if access_token and expiry_raw:
        try:
            expiry = datetime.fromisoformat(expiry_raw)
            if expiry > datetime.now(timezone.utc):
                return access_token
        except ValueError:
            pass

    client_id = await get_setting(db, SETTING_CLIENT_ID)
    client_secret = await get_setting(db, SETTING_CLIENT_SECRET)

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            OAUTH_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
        if resp.status_code != 200:
            raise ValueError(f"YouTube 토큰 갱신 실패: {resp.text[:200]}")
        data = resp.json()
        access_token = data["access_token"]
        await _store_access_token(db, access_token, int(data.get("expires_in", 3600)))
        return access_token


async def _fetch_my_channel(access_token: str) -> dict[str, str] | None:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{YOUTUBE_API}/channels",
            params={"part": "snippet", "mine": "true"},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if resp.status_code != 200:
            return None
        items = resp.json().get("items", [])
        if not items:
            return None
        item = items[0]
        return {
            "id": item["id"],
            "title": item["snippet"]["title"],
        }


def find_video_file(project_dir: Path) -> Path | None:
    result_file = project_dir / "pipeline_result.json"
    if result_file.exists():
        try:
            meta = json.loads(result_file.read_text(encoding="utf-8"))
            vp = Path(meta.get("video_output", ""))
            if vp.is_file():
                return vp
        except (json.JSONDecodeError, OSError):
            pass

    mp4s = sorted(project_dir.rglob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
    return mp4s[0] if mp4s else None


def _build_description(project_dir: Path, assets: dict) -> str:
    parts: list[str] = []
    prompt_file = project_dir / "suno_prompt.txt"
    if prompt_file.exists():
        parts.append(prompt_file.read_text(encoding="utf-8", errors="ignore")[:2000])
    if assets.get("lyrics_ko"):
        parts.append("\n\n[가사]\n" + assets["lyrics_ko"][:3000])
    elif assets.get("lyrics_en"):
        parts.append("\n\n[Lyrics]\n" + assets["lyrics_en"][:3000])
    return "\n".join(parts).strip()[:4900] or "Suno Helper"


async def upload_project_video(
    db: AsyncSession,
    project_dir: Path,
    privacy_status: str = "private",
    title: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    if privacy_status not in ("private", "unlisted", "public"):
        raise ValueError("공개 설정은 private, unlisted, public 중 하나여야 합니다.")

    video_path = find_video_file(project_dir)
    if not video_path:
        raise ValueError("업로드할 mp4 영상이 없습니다. 먼저 파이프라인으로 영상을 생성하세요.")

    assets = find_project_assets(project_dir)
    video_title = (title or assets.get("track_title") or project_dir.name)[:100]
    video_description = description or _build_description(project_dir, assets)
    video_tags = (tags or ["Suno", "AI Music", "Music"])[:30]

    access_token = await get_access_token(db)

    metadata = {
        "snippet": {
            "title": video_title,
            "description": video_description,
            "tags": video_tags,
            "categoryId": "10",
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False,
        },
    }

    file_size = video_path.stat().st_size
    video_bytes = video_path.read_bytes()

    async with httpx.AsyncClient(timeout=900.0) as client:
        init_resp = await client.post(
            YOUTUBE_UPLOAD,
            params={"uploadType": "resumable", "part": "snippet,status"},
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            json=metadata,
        )
        if init_resp.status_code not in (200, 201):
            raise ValueError(f"업로드 세션 시작 실패: {init_resp.text[:300]}")

        upload_url = init_resp.headers.get("Location")
        if not upload_url:
            raise ValueError("YouTube 업로드 URL을 받지 못했습니다.")

        upload_resp = await client.put(
            upload_url,
            headers={
                "Content-Type": "video/*",
                "Content-Length": str(file_size),
            },
            content=video_bytes,
        )
        if upload_resp.status_code not in (200, 201):
            raise ValueError(f"영상 업로드 실패: {upload_resp.text[:300]}")

        result = upload_resp.json()

    video_id = result.get("id", "")
    (project_dir / VIDEO_ID_FILE).write_text(video_id, encoding="utf-8")
    (project_dir / META_FILE).write_text(
        json.dumps(
            {
                "video_id": video_id,
                "title": video_title,
                "privacy_status": privacy_status,
                "uploaded_at": datetime.now(timezone.utc).isoformat(),
                "url": f"https://www.youtube.com/watch?v={video_id}",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return {
        "video_id": video_id,
        "title": video_title,
        "privacy_status": privacy_status,
        "url": f"https://www.youtube.com/watch?v={video_id}",
    }


async def publish_video(db: AsyncSession, video_id: str) -> dict[str, Any]:
    access_token = await get_access_token(db)
    body = {"id": video_id, "status": {"privacyStatus": "public"}}

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.put(
            f"{YOUTUBE_API}/videos",
            params={"part": "status"},
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json=body,
        )
        if resp.status_code != 200:
            raise ValueError(f"공개 전환 실패: {resp.text[:300]}")
        return resp.json()


def get_stored_video_id(project_dir: Path) -> str | None:
    f = project_dir / VIDEO_ID_FILE
    if f.exists():
        vid = f.read_text(encoding="utf-8").strip()
        return vid or None
    return None
