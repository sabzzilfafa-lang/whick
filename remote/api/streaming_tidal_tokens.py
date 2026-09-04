"""Tidal OAuth 토큰 갱신 · OpenAPI 헤더."""
from __future__ import annotations

import json
import os
import time
from typing import Any

import httpx

from api import streaming_providers

TIDAL_CLIENT_ID = os.getenv("WHICK_TIDAL_CLIENT_ID", "").strip()
TIDAL_AUTH_BASE = os.getenv("WHICK_TIDAL_AUTH_BASE", "https://auth.tidal.com/v1").rstrip("/")
TIDAL_OPENAPI = os.getenv("WHICK_TIDAL_OPENAPI_BASE", "https://openapi.tidal.com").rstrip("/")


def country_code() -> str:
    """Tidal 계정 카탈로그 지역 (ISO 3166-1 alpha-2). WHICK_TIDAL_COUNTRY_CODE 로 설정."""
    return (os.getenv("WHICK_TIDAL_COUNTRY_CODE", "US").strip() or "US").upper()


def _load_creds() -> dict[str, Any]:
    try:
        return json.loads(streaming_providers.TIDAL_CREDS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_creds(data: dict[str, Any]) -> None:
    streaming_providers._ensure_dir()
    streaming_providers.TIDAL_CREDS.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def is_lab_token(token: str | None) -> bool:
    return not token or token == "lab"


async def valid_access_token() -> str | None:
    creds = _load_creds()
    token = str(creds.get("access_token") or "")
    if is_lab_token(token):
        return None
    expires_in = int(creds.get("expires_in") or 0)
    stored = creds.get("stored_at") or creds.get("connected_at")
    if expires_in and stored:
        try:
            from datetime import datetime

            ts = datetime.fromisoformat(str(stored).replace("Z", "+00:00")).timestamp()
            if time.time() < ts + expires_in - 120:
                return token
        except (TypeError, ValueError):
            return token
    elif token and not creds.get("refresh_token"):
        return token

    refresh = str(creds.get("refresh_token") or "")
    if not refresh or not TIDAL_CLIENT_ID:
        return token or None

    url = f"{TIDAL_AUTH_BASE}/oauth2/token"
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            url,
            data={
                "client_id": TIDAL_CLIENT_ID,
                "refresh_token": refresh,
                "grant_type": "refresh_token",
            },
        )
        if resp.status_code >= 400:
            return token or None
        data = resp.json()
        access = str(data.get("access_token") or "")
        if not access:
            return token or None
        creds.update(data)
        creds["stored_at"] = streaming_providers._utc_now()
        _save_creds(creds)
        return access


def openapi_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.api+json",
    }


def v1_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/vnd.tidal.v1+json",
    }
