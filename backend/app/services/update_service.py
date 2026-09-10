"""업데이트 채널 — 앱 버전 조회 + whick.org 버전 메타데이터 확인.

Phase C 기본 구조:
- APP_VERSION: 백엔드 버전 SSOT (main.py 헬스체크·업데이트 체크가 참조)
- check_for_update(): 서버 메타데이터 {version, url, notes} 와 비교 (기기정보 미전송)
- 서버 미설정/오프라인이면 조용히 None — 앱 동작에 영향 없음
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from app.config import settings

APP_VERSION = "0.9.57"

# whick.org 업데이트 채널 (배포 시 확정 — env로 Override 가능)
UPDATE_CHECK_URL = os.environ.get(
    "SUNO_UPDATE_URL", "https://whick.org/api/suno/version"
)


def current_version() -> str:
    return APP_VERSION


def _version_tuple(v: str) -> tuple[int, ...]:
    parts = []
    for p in str(v).strip().lstrip("v").split("."):
        digits = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def is_newer(remote: str, local: str) -> bool:
    try:
        return _version_tuple(remote) > _version_tuple(local)
    except (TypeError, ValueError):
        return False


async def check_for_update(timeout: float = 4.0) -> dict[str, Any] | None:
    """새 버전 메타데이터 or None (오류는 전파하지 않는다)."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(UPDATE_CHECK_URL)
        if r.status_code != 200:
            return None
        data = r.json()
    except Exception:
        return None
    remote = str(data.get("version") or "").strip()
    if not remote or not is_newer(remote, APP_VERSION):
        return None
    return {
        "version": remote,
        "current": APP_VERSION,
        "notes": str(data.get("notes") or ""),
        "download_url": str(data.get("url") or ""),
    }
