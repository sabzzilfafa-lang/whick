"""미니PC player — 리모컨 device_token (선택적)."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import HTTPException, Request, WebSocket

TOKEN_PATH = Path(os.getenv("WHICK_DEVICE_TOKEN_PATH", "/var/lib/whick/remote-device-token"))
_cached: str | None = None


def load_device_token() -> str | None:
    global _cached
    if _cached is not None:
        return _cached or None
    tok = os.getenv("WHICK_PLAYER_DEVICE_TOKEN", "").strip()
    if not tok and TOKEN_PATH.is_file():
        tok = TOKEN_PATH.read_text(encoding="utf-8").strip()
    _cached = tok or ""
    return tok or None


def auth_enabled() -> bool:
    if os.getenv("WHICK_PLAYER_AUTH_REQUIRED", "0") != "1":
        return False
    return bool(load_device_token())


def token_from_request(request: Request) -> str | None:
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.query_params.get("token")


def token_from_ws(ws: WebSocket) -> str | None:
    return ws.query_params.get("token")


def verify_token(got: str | None) -> None:
    expected = load_device_token()
    if not expected:
        return
    if got != expected:
        raise HTTPException(status_code=401, detail="device_token invalid or missing")


def verify_http(request: Request) -> None:
    verify_token(token_from_request(request))


def verify_destructive(request: Request) -> None:
    """파일시스템 파괴 경로 검증 — token 미설정 시에도 차단 (소유자만 쓰기)."""
    expected = load_device_token()
    if not expected:
        raise HTTPException(status_code=403, detail="device_token not configured — owner setup required")
    got = token_from_request(request)
    if got != expected:
        raise HTTPException(status_code=401, detail="device_token invalid — owner only")


def verify_ws(ws: WebSocket) -> None:
    expected = load_device_token()
    if not expected:
        return
    got = token_from_ws(ws)
    if got != expected:
        raise HTTPException(status_code=401, detail="device_token invalid or missing")


def ensure_token_file() -> str:
    """entrypoint — 토큰 파일 없으면 생성."""
    existing = load_device_token()
    if existing:
        return existing
    import secrets

    tok = f"devtok_{secrets.token_hex(24)}"
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(tok + "\n", encoding="utf-8")
    global _cached
    _cached = tok
    os.environ["WHICK_PLAYER_DEVICE_TOKEN"] = tok
    return tok
