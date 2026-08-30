"""YouTube Data API v3 — OAuth2 연동, 업로드, 공개."""

from __future__ import annotations

import asyncio
import json
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.audio_fingerprint import assert_no_suno_fingerprint
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
PREVIEW_VIDEO_NAMES = {"preview_short.mp4", "preview_30s.mp4"}
UPLOAD_CHUNK = 8 * 1024 * 1024  # 8MiB, YouTube 256KiB 배수
_upload_jobs: dict[str, dict[str, Any]] = {}


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


def find_video_file(project_dir: Path, work_root: Path | None = None) -> Path | None:
    from app.services.editor_service import find_latest_video

    video = find_latest_video(project_dir, preview=False, work_root=work_root)
    if video and video.name.lower() not in PREVIEW_VIDEO_NAMES:
        return video
    return None


def describe_video_file(video_path: Path) -> dict[str, Any]:
    size = video_path.stat().st_size
    duration = 0.0
    try:
        from app.services.pipeline_service import probe_duration

        duration = float(probe_duration(video_path) or 0)
        if duration <= 1:
            duration = 0.0
    except Exception:
        duration = 0.0
    return {
        "name": video_path.name,
        "path": str(video_path),
        "size_bytes": size,
        "size_mb": round(size / (1024 * 1024), 1),
        "duration_sec": round(duration, 1) if duration else None,
    }


def _build_description(project_dir: Path, assets: dict) -> str:
    desc_file = project_dir / "youtube_description.txt"
    if desc_file.exists():
        text = desc_file.read_text(encoding="utf-8", errors="ignore").strip()
        if text:
            return text[:4900]

    parts: list[str] = []
    prompt_file = project_dir / "suno_prompt.txt"
    if prompt_file.exists():
        parts.append(prompt_file.read_text(encoding="utf-8", errors="ignore")[:2000])
    if assets.get("lyrics_ko"):
        parts.append("\n\n[가사]\n" + assets["lyrics_ko"][:3000])
    elif assets.get("lyrics_en"):
        parts.append("\n\n[Lyrics]\n" + assets["lyrics_en"][:3000])
    return "\n".join(parts).strip()[:4900] or "Suno Helper"


def _thumbnail_dirs(project_dir: Path) -> list[Path]:
    dirs: list[Path] = []
    marker = project_dir / "last_pipeline_output.json"
    if marker.is_file():
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
        out = Path(str(data.get("output_dir") or ""))
        if out.is_dir():
            dirs.append(out)
        video = Path(str(data.get("video") or ""))
        if video.is_file():
            dirs.append(video.parent)
    dirs.append(project_dir)
    unique: list[Path] = []
    seen: set[str] = set()
    for d in dirs:
        key = str(d)
        if key in seen:
            continue
        seen.add(key)
        unique.append(d)
    return unique


def _find_thumbnail(project_dir: Path) -> Path | None:
    names = ("thumbnail.jpg", "thumbnail.jpeg", "thumbnail.png", "thumbnail.webp")
    for folder in _thumbnail_dirs(project_dir):
        for name in names:
            p = folder / name
            if p.exists():
                return p
    assets = find_project_assets(project_dir)
    for img in assets.get("image_paths") or []:
        path = Path(img)
        if path.exists():
            return path
    return None


def _youtube_api_error(status: int, body: str) -> str:
    text = (body or "")[:500]
    lower = text.lower()
    if status == 403 and "youtube data api" in lower and ("not been used" in lower or "disabled" in lower):
        return (
            "YouTube Data API v3가 이 Google Cloud 프로젝트에서 꺼져 있습니다. "
            "https://console.cloud.google.com/apis/library/youtube.googleapis.com 에서 "
            "사용 설정한 뒤 몇 분 기다렸다가 다시 업로드하세요."
        )
    if status == 401 or "invalid_grant" in lower or "invalid credentials" in lower:
        return "YouTube 로그인이 만료됐습니다. 설정에서 다시 연결하세요."
    return f"업로드 세션 시작 실패 ({status}): {text[:300]}"


def _set_youtube_thumbnail_sync(
    client: httpx.Client,
    access_token: str,
    video_id: str,
    thumb_path: Path,
) -> None:
    data = thumb_path.read_bytes()
    suffix = thumb_path.suffix.lower()
    mime = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(suffix, "image/jpeg")
    resp = client.post(
        f"{YOUTUBE_API}/thumbnails/set",
        params={"videoId": video_id},
        headers={"Authorization": f"Bearer {access_token}"},
        files={"media": (thumb_path.name, data, mime)},
    )
    if resp.status_code not in (200, 201):
        raise ValueError(f"썸네일 설정 실패: {resp.text[:200]}")


def _upload_media_sync(
    access_token: str,
    metadata: dict[str, Any],
    video_path: Path,
    file_size: int,
    thumb_path: Path | None,
    on_progress: Callable[[int, int], None] | None = None,
) -> tuple[dict[str, Any], bool]:
    """YouTube resumable upload — 청크 전송으로 진행률 갱신."""

    def _progress(sent: int) -> None:
        if on_progress:
            on_progress(sent, file_size)

    with httpx.Client(timeout=180.0, follow_redirects=False) as client:
        init_resp = client.post(
            YOUTUBE_UPLOAD,
            params={"uploadType": "resumable", "part": "snippet,status"},
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Length": str(file_size),
                "X-Upload-Content-Type": "video/mp4",
            },
            json=metadata,
        )
        if init_resp.status_code not in (200, 201):
            raise ValueError(_youtube_api_error(init_resp.status_code, init_resp.text))

        upload_url = init_resp.headers.get("Location")
        if not upload_url:
            raise ValueError("YouTube 업로드 URL을 받지 못했습니다.")

        result: dict[str, Any] | None = None
        sent = 0
        _progress(0)
        with video_path.open("rb") as fh:
            while sent < file_size:
                chunk = fh.read(UPLOAD_CHUNK)
                if not chunk:
                    break
                end = sent + len(chunk) - 1
                upload_resp = client.put(
                    upload_url,
                    headers={
                        "Content-Type": "video/mp4",
                        "Content-Length": str(len(chunk)),
                        "Content-Range": f"bytes {sent}-{end}/{file_size}",
                    },
                    content=chunk,
                )
                if upload_resp.status_code in (200, 201):
                    result = upload_resp.json()
                    sent = file_size
                    _progress(sent)
                    break
                if upload_resp.status_code == 308:
                    range_hdr = upload_resp.headers.get("Range") or ""
                    if "=" in range_hdr:
                        try:
                            sent = int(range_hdr.split("-")[-1]) + 1
                        except ValueError:
                            sent = end + 1
                    else:
                        sent = end + 1
                    _progress(min(sent, file_size))
                    continue
                raise ValueError(f"영상 업로드 실패: {upload_resp.text[:300]}")
        if not result:
            raise ValueError("영상 업로드가 끝나지 않았습니다.")

        video_id = result.get("id", "")
        thumb_ok = False
        if video_id and thumb_path:
            try:
                _set_youtube_thumbnail_sync(client, access_token, video_id, thumb_path)
                thumb_ok = True
            except Exception:
                thumb_ok = False
        return result, thumb_ok


async def upload_project_video(
    db: AsyncSession,
    project_dir: Path,
    privacy_status: str = "private",
    title: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
    work_root: Path | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    if privacy_status not in ("private", "unlisted", "public"):
        raise ValueError("공개 설정은 private, unlisted, public 중 하나여야 합니다.")

    video_path = find_video_file(project_dir, work_root=work_root)
    if not video_path:
        raise ValueError(
            "업로드할 완성 영상이 없습니다. 미리보기(preview_*.mp4)는 올리지 않습니다. "
            "영상 인코딩을 먼저 실행하세요."
        )

    from app.services.editor_service import load_editor_config

    editor = load_editor_config(project_dir)
    if editor.get("remaster", {}).get("strip_fingerprint", True):
        assert_no_suno_fingerprint(video_path)
        remastered = project_dir / "remastered.m4a"
        if remastered.exists():
            assert_no_suno_fingerprint(remastered)

    assets = find_project_assets(project_dir)
    title_file = project_dir / "title.txt"
    file_title = (
        title_file.read_text(encoding="utf-8", errors="ignore").strip()
        if title_file.exists()
        else ""
    )
    video_title = (title or file_title or assets.get("track_title") or project_dir.name)[:100]
    video_description = description or _build_description(project_dir, assets)
    if not tags:
        from app.services.editor_service import DEFAULT_EDITOR_CONFIG

        tags = list(DEFAULT_EDITOR_CONFIG["youtube"]["tags"])
    video_tags = tags[:30]

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

    file_info = describe_video_file(video_path)
    file_size = int(file_info["size_bytes"])
    thumb = _find_thumbnail(project_dir)
    result, thumb_ok = await asyncio.to_thread(
        _upload_media_sync,
        access_token,
        metadata,
        video_path,
        file_size,
        thumb,
        on_progress,
    )

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
                "thumbnail_set": thumb_ok,
                "file_name": file_info["name"],
                "file_size_bytes": file_size,
                "duration_sec": file_info.get("duration_sec"),
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
        "thumbnail_set": thumb_ok,
        "file_name": file_info["name"],
        "file_size_mb": file_info["size_mb"],
        "duration_sec": file_info.get("duration_sec"),
    }


def get_upload_job(job_id: str) -> dict[str, Any] | None:
    job = _upload_jobs.get(job_id)
    if not job:
        return None
    return dict(job)


def start_upload_job(
    *,
    project: Path,
    work_root: Path,
    privacy_status: str = "private",
    title: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
    move_to_stage: str | None = None,
) -> dict[str, Any]:
    video = find_video_file(project, work_root=work_root)
    if not video:
        raise ValueError(
            "업로드할 완성 영상이 없습니다. 미리보기(preview_*.mp4)는 올리지 않습니다. "
            "영상 인코딩을 먼저 실행하세요."
        )
    info = describe_video_file(video)
    job_id = secrets.token_hex(8)
    job = {
        "id": job_id,
        "status": "running",
        "bytes_sent": 0,
        "size_bytes": info["size_bytes"],
        "percent": 0,
        "file_name": info["name"],
        "result": None,
        "error": None,
    }
    _upload_jobs[job_id] = job
    asyncio.create_task(
        _run_upload_job(
            job_id,
            project,
            work_root,
            privacy_status,
            title,
            description,
            tags,
            move_to_stage,
        )
    )
    return dict(job)


def _job_progress(job_id: str, sent: int, total: int) -> None:
    job = _upload_jobs.get(job_id)
    if not job:
        return
    job["bytes_sent"] = sent
    job["size_bytes"] = total
    job["percent"] = min(100, int(sent * 100 / total)) if total else 0


async def _run_upload_job(
    job_id: str,
    project: Path,
    work_root: Path,
    privacy_status: str,
    title: str | None,
    description: str | None,
    tags: list[str] | None,
    move_to_stage: str | None,
) -> None:
    from app.database import async_session

    job = _upload_jobs.get(job_id)
    if not job:
        return
    try:
        async with async_session() as db:
            result = await upload_project_video(
                db,
                project,
                privacy_status=privacy_status,
                title=title,
                description=description,
                tags=tags,
                work_root=work_root,
                on_progress=lambda sent, total: _job_progress(job_id, sent, total),
            )
        if move_to_stage:
            from app.services.workflow_service import WORKFLOW_STAGES, move_project

            stage = next((s for s in WORKFLOW_STAGES if s["id"] == move_to_stage), None)
            if stage:
                dest_parent = work_root / stage["folder"]
                try:
                    move_project(project, dest_parent)
                    result["moved_to"] = str(dest_parent / project.name)
                except FileNotFoundError:
                    pass
        job["bytes_sent"] = job.get("size_bytes") or 0
        job["percent"] = 100
        job["status"] = "completed"
        job["result"] = result
    except Exception as e:
        job["status"] = "failed"
        job["error"] = str(e)[:400]


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
