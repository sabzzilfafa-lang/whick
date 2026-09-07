"""로컬 실행·설치 상태 API — whick.org 웹 대시보드가 참조.

GET /api/local/status  → 설치 여부·버전·실행 허용(웹 실행 플래그)·라이선스 요약
GET /api/local/launch  → suno-helper:// 프로토콜이 이 응답을 받아 UI 오픈용 토큰 수령
CORS 전체 허용(whick.org 페이지에서 fetch 가능).
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from app.services import license_service
from app.services.update_service import APP_VERSION

router = APIRouter()

# 웹 실행 잠금 해제 플래그 파일 (install.bat이 웹 설치 흐름에서 생성)
WEB_LAUNCH_FLAG = "web_launch.lock"
# 프로토콜 핸드셰이크 토큰 수명 (초)
LAUNCH_TOKEN_TTL = 60

_launch_token: dict[str, Any] = {"token": "", "issued_at": 0.0}


def _flag_path() -> Path:
    from app.config import settings

    return Path(settings.data_dir) / WEB_LAUNCH_FLAG


def web_launch_enabled() -> bool:
    """웹 설치 흐름으로 설치된 경우에만 웹 실행 버튼 동작."""
    return _flag_path().is_file()


@router.get("/local/status")
async def api_local_status() -> dict[str, Any]:
    lic = license_service.license_status()
    return {
        "installed": True,  # 이 API에 접근 가능 == 설치됨
        "version": APP_VERSION,
        "web_launch": web_launch_enabled(),
        "license_state": lic.get("state", "none"),
        "email": lic.get("email", ""),
    }


@router.get("/local/launch")
async def api_local_launch() -> dict[str, Any]:
    """suno-helper:// 콜백 → 일회용 토큰 발급 (짧은 수명)."""
    if not web_launch_enabled():
        return {"ok": False, "error": "web_launch_disabled"}
    _launch_token["token"] = os.urandom(16).hex()
    _launch_token["issued_at"] = time.time()
    return {
        "ok": True,
        "token": _launch_token["token"],
        "version": APP_VERSION,
        "expires_in": LAUNCH_TOKEN_TTL,
    }
