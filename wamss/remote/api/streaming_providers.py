"""Spotify · Tidal 연동 상태 — 미니PC headless (CamillaDSP 경로 후속)."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

PROVIDERS_DIR = Path(os.getenv("WHICK_PROVIDERS_DIR", "/var/lib/whick/providers"))
STATE_FILE = PROVIDERS_DIR / "streaming-state.json"
SPOTIFY_CACHE = PROVIDERS_DIR / "spotify"
TIDAL_CREDS = PROVIDERS_DIR / "tidal-credentials.json"
LIBRESPOT_BIN = os.getenv("WHICK_LIBRESPOT_BIN", "librespot")
LIBRESPOT_CAMILLA_CMD = os.getenv("WHICK_LIBRESPOT_CAMILLA_CMD", "/app/docker/librespot-camilla.sh")
SPOTIFY_DEVICE_NAME = os.getenv("WHICK_SPOTIFY_DEVICE_NAME", "Whick Player")
TIDAL_CLIENT_ID = os.getenv("WHICK_TIDAL_CLIENT_ID", "").strip()
TIDAL_AUTH_BASE = os.getenv("WHICK_TIDAL_AUTH_BASE", "https://auth.tidal.com/v1").rstrip("/")

DEFAULT_STATE: dict[str, Any] = {
    "spotify": {
        "status": "disconnected",
        "device_name": SPOTIFY_DEVICE_NAME,
        "account_label": "",
        "connected_at": None,
        "message": "",
    },
    "tidal": {
        "status": "disconnected",
        "account_label": "",
        "connected_at": None,
        "user_code": "",
        "verification_uri": "https://link.tidal.com",
        "verification_uri_complete": "",
        "device_code": "",
        "expires_in": 0,
        "poll_interval": 5,
        "message": "",
    },
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _ensure_dir() -> None:
    PROVIDERS_DIR.mkdir(parents=True, exist_ok=True)
    SPOTIFY_CACHE.mkdir(parents=True, exist_ok=True)


def _load_state() -> dict[str, Any]:
    _ensure_dir()
    if not STATE_FILE.is_file():
        return json.loads(json.dumps(DEFAULT_STATE))
    try:
        raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return json.loads(json.dumps(DEFAULT_STATE))
    merged = json.loads(json.dumps(DEFAULT_STATE))
    for key in ("spotify", "tidal"):
        if isinstance(raw.get(key), dict):
            merged[key].update(raw[key])
    merged["spotify"]["device_name"] = SPOTIFY_DEVICE_NAME
    return merged


def _save_state(state: dict[str, Any]) -> None:
    _ensure_dir()
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _spotify_cache_connected() -> tuple[bool, str]:
    """librespot credential cache 존재 여부."""
    if not SPOTIFY_CACHE.is_dir():
        return False, ""
    for path in SPOTIFY_CACHE.rglob("*"):
        if path.is_file() and path.stat().st_size > 32:
            name = path.name
            if "credentials" in name.lower() or name.endswith(".json"):
                return True, "Spotify Premium"
    # generic: any non-empty cache file
    for path in SPOTIFY_CACHE.iterdir():
        if path.is_file() and path.stat().st_size > 64:
            return True, "Spotify Premium"
    return False, ""


def _librespot_running() -> bool:
    try:
        out = subprocess.run(
            ["pgrep", "-f", "librespot"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        return out.returncode == 0 and bool(out.stdout.strip())
    except Exception:
        return False


def _librespot_argv() -> list[str]:
    return [
        LIBRESPOT_BIN,
        "--name",
        SPOTIFY_DEVICE_NAME,
        "--cache",
        str(SPOTIFY_CACHE),
        "--zeroconf-port",
        "0",
        "--backend",
        os.getenv("WHICK_LIBRESPOT_BACKEND", "subprocess"),
        "--device",
        os.getenv("WHICK_LIBRESPOT_DEVICE", LIBRESPOT_CAMILLA_CMD),
        "--format",
        os.getenv("WHICK_LIBRESPOT_FORMAT", "S16"),
    ]


def _start_librespot_zeroconf() -> str | None:
    if not shutil.which(LIBRESPOT_BIN):
        return None
    if _librespot_running():
        return None
    log = Path(os.getenv("WHICK_LIBRESPOT_LOG", "/var/lib/whick/run/librespot.log"))
    log.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(log, "a", encoding="utf-8") as logf:
            subprocess.Popen(
                _librespot_argv(),
                stdout=logf,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        return None
    except OSError as exc:
        return str(exc)


def _sync_spotify_state(state: dict[str, Any]) -> None:
    sp = state["spotify"]
    connected, label = _spotify_cache_connected()
    if connected:
        sp["status"] = "connected"
        sp["account_label"] = label or sp.get("account_label") or "Spotify Premium"
        sp["connected_at"] = sp.get("connected_at") or _utc_now()
        sp["message"] = "Spotify Connect 연결됨 · 재생은 librespot → CamillaDSP 경로"
        from api import streaming_playback

        if os.getenv("WHICK_STREAMING_LAB", "0") == "1" and not streaming_playback.SPOTIFY_CREDS.is_file():
            streaming_playback.store_spotify_web_token("lab-access-token")
    elif sp.get("status") == "awaiting_connect":
        sp["message"] = (
            f"Spotify 앱 → 기기 연결 → 「{SPOTIFY_DEVICE_NAME}」을 선택하세요"
        )
    elif sp.get("status") != "connected":
        sp["status"] = "disconnected"
        sp["message"] = ""


def get_streaming_status() -> dict[str, Any]:
    state = _load_state()
    _sync_spotify_state(state)
    _save_state(state)
    from api import streaming_spotify_oauth

    oauth = streaming_spotify_oauth.oauth_status()
    return {
        "ok": True,
        "providers": {
            "spotify": {
                **state["spotify"],
                "web_api_connected": oauth["web_api_connected"],
                "oauth_available": oauth["oauth_available"],
            },
            "tidal": _public_tidal(state["tidal"]),
        },
        "spotify_device_name": SPOTIFY_DEVICE_NAME,
        "librespot_available": bool(shutil.which(LIBRESPOT_BIN)),
        "librespot_running": _librespot_running(),
        "spotify_oauth": oauth,
    }


def _public_tidal(tidal: dict[str, Any]) -> dict[str, Any]:
    out = dict(tidal)
    out.pop("device_code", None)
    return out


async def spotify_connect_start() -> dict[str, Any]:
    state = _load_state()
    sp = state["spotify"]
    connected, label = _spotify_cache_connected()
    if connected:
        sp["status"] = "connected"
        sp["account_label"] = label or "Spotify Premium"
        sp["connected_at"] = sp.get("connected_at") or _utc_now()
        sp["message"] = "이미 연결되어 있습니다"
        _save_state(state)
        return {"ok": True, "already_connected": True, "spotify": sp}

    sp["status"] = "awaiting_connect"
    sp["connected_at"] = None
    sp["account_label"] = ""
    err = _start_librespot_zeroconf()
    if err:
        sp["message"] = (
            f"Spotify 앱 → 기기 연결 → 「{SPOTIFY_DEVICE_NAME}」 선택 "
            f"(librespot: {err})"
        )
    else:
        sp["message"] = f"Spotify 앱 → 기기 연결 → 「{SPOTIFY_DEVICE_NAME}」을 선택하세요"
    _save_state(state)
    return {
        "ok": True,
        "spotify": sp,
        "steps": [
            "폰에서 Spotify 앱을 여세요",
            "재생 중인 곡 화면에서 「기기로 재생」(Connect) 아이콘을 탭하세요",
            f"목록에서 「{SPOTIFY_DEVICE_NAME}」을 선택하세요",
            "아래 「연결 확인」을 눌러 완료하세요",
        ],
    }


def spotify_connect_complete() -> dict[str, Any]:
    state = _load_state()
    sp = state["spotify"]
    connected, label = _spotify_cache_connected()
    if connected:
        sp["status"] = "connected"
        sp["account_label"] = label or "Spotify Premium"
        sp["connected_at"] = _utc_now()
        sp["message"] = "Spotify 연결 완료"
        _save_state(state)
        return {"ok": True, "connected": True, "spotify": sp}

    # lab: awaiting_connect 상태에서 수동 완료 허용 (데몬 없는 PoC)
    if sp.get("status") == "awaiting_connect" and os.getenv("WHICK_STREAMING_LAB", "0") == "1" and os.getenv("WHICK_STREAMING_LAB_COMPLETE", "1") == "1":
        marker = SPOTIFY_CACHE / "lab-connected.json"
        marker.write_text(json.dumps({"connected_at": _utc_now()}), encoding="utf-8")
        sp["status"] = "connected"
        sp["account_label"] = "Spotify (lab)"
        sp["connected_at"] = _utc_now()
        sp["message"] = "Spotify 연결 완료 (lab)"
        _save_state(state)
        from api import streaming_playback

        streaming_playback.store_spotify_web_token("lab-access-token")
        return {"ok": True, "connected": True, "lab": True, "spotify": sp}

    sp["message"] = "아직 연결되지 않았습니다 · Spotify 앱에서 Whick Player를 선택했는지 확인하세요"
    _save_state(state)
    return {"ok": False, "connected": False, "spotify": sp, "message": sp["message"]}


def spotify_disconnect() -> dict[str, Any]:
    state = _load_state()
    state["spotify"] = json.loads(json.dumps(DEFAULT_STATE["spotify"]))
    state["spotify"]["device_name"] = SPOTIFY_DEVICE_NAME
    if SPOTIFY_CACHE.is_dir():
        shutil.rmtree(SPOTIFY_CACHE, ignore_errors=True)
        SPOTIFY_CACHE.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(["pkill", "-f", "librespot"], timeout=3, check=False)
    except Exception:
        pass
    from api import streaming_playback

    streaming_playback.clear_spotify_web_token()
    from api.streaming_spotify_oauth import OAUTH_PENDING

    OAUTH_PENDING.unlink(missing_ok=True)
    _save_state(state)
    return {"ok": True, "spotify": state["spotify"]}


def _format_user_code(raw: str) -> str:
    raw = re.sub(r"[^A-Za-z0-9]", "", raw.upper())
    if len(raw) >= 8:
        return f"{raw[:4]}-{raw[4:8]}"
    return raw


def _tidal_mock_device() -> dict[str, Any]:
    suffix = hex(int(time.time()) % 0xFFFF)[2:].upper().zfill(4)
    user_code = f"WHCK-{suffix}"
    return {
        "device_code": f"lab-device-{suffix.lower()}",
        "user_code": user_code,
        "verification_uri": "https://link.tidal.com",
        "verification_uri_complete": f"https://link.tidal.com/{user_code}",
        "expires_in": 900,
        "interval": 5,
        "lab": True,
    }


def _lab_mode() -> bool:
    return os.getenv("WHICK_STREAMING_LAB", "0") == "1"


async def _tidal_request_device_code() -> dict[str, Any]:
    if not TIDAL_CLIENT_ID:
        if _lab_mode():
            return _tidal_mock_device()
        raise ValueError("WHICK_TIDAL_CLIENT_ID 미설정")
    url = f"{TIDAL_AUTH_BASE}/oauth2/device_authorization"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            url,
            data={"client_id": TIDAL_CLIENT_ID, "scope": "r_usr w_usr playback"},
        )
        if resp.status_code >= 400:
            detail = (resp.text or "")[:200]
            if _lab_mode():
                return _tidal_mock_device()
            raise ValueError(f"Tidal device authorization failed ({resp.status_code}): {detail}")
        data = resp.json()
        data["lab"] = False
        if "user_code" in data:
            data["user_code"] = _format_user_code(str(data["user_code"]))
        return data


async def tidal_connect_start() -> dict[str, Any]:
    state = _load_state()
    td = state["tidal"]
    if td.get("status") == "connected" and TIDAL_CREDS.is_file():
        return {"ok": True, "already_connected": True, "tidal": _public_tidal(td)}

    try:
        device = await _tidal_request_device_code()
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "tidal": _public_tidal(td)}
    td["status"] = "awaiting_code"
    td["device_code"] = device["device_code"]
    td["user_code"] = device.get("user_code", "")
    td["verification_uri"] = device.get("verification_uri", "https://link.tidal.com")
    td["verification_uri_complete"] = device.get(
        "verification_uri_complete",
        f"{td['verification_uri']}/{td['user_code']}",
    )
    td["expires_in"] = int(device.get("expires_in", 900))
    td["poll_interval"] = int(device.get("interval", 5))
    td["connected_at"] = None
    td["account_label"] = ""
    td["message"] = "link.tidal.com 에서 코드를 입력하세요"
    td["_started_at"] = time.time()
    td["_lab"] = bool(device.get("lab"))
    _save_state(state)

    creds_pending = PROVIDERS_DIR / "tidal-pending.json"
    creds_pending.write_text(
        json.dumps(
            {
                "device_code": td["device_code"],
                "lab": td["_lab"],
                "started_at": td["_started_at"],
            }
        ),
        encoding="utf-8",
    )

    return {
        "ok": True,
        "tidal": _public_tidal(td),
        "steps": [
            "아래 코드를 메모하거나 「링크 열기」를 누르세요",
            "브라우저에서 Tidal 계정으로 로그인하세요",
            "화면 안내에 따라 코드를 입력하세요",
            "승인하면 이 화면이 자동으로 완료됩니다",
        ],
    }


async def _tidal_poll_token(device_code: str, lab: bool) -> dict[str, Any] | None:
    if lab or (not TIDAL_CLIENT_ID and _lab_mode()):
        pending = PROVIDERS_DIR / "tidal-pending.json"
        approved = PROVIDERS_DIR / "tidal-lab-approved.json"
        if approved.is_file():
            try:
                return json.loads(approved.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return {"access_token": "lab", "user_id": "lab"}
        if pending.is_file() and os.getenv("WHICK_TIDAL_LAB_AUTO_APPROVE", "0") == "1":
            try:
                meta = json.loads(pending.read_text(encoding="utf-8"))
                if time.time() - float(meta.get("started_at", 0)) > 120:
                    return {"access_token": "lab", "user_id": "lab"}
            except (json.JSONDecodeError, TypeError):
                pass
        return None

    if not TIDAL_CLIENT_ID:
        return {"error": "missing_client_id"}

    url = f"{TIDAL_AUTH_BASE}/oauth2/token"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            url,
            data={
                "client_id": TIDAL_CLIENT_ID,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
        )
        if resp.status_code == 200:
            return resp.json()
        data = resp.json() if resp.content else {}
        err = data.get("error") or ""
        if err == "authorization_pending":
            return None
        if err == "slow_down":
            return {"slow_down": True}
        if err:
            return {"error": err, "error_description": data.get("error_description", "")}
        return None


async def tidal_connect_poll() -> dict[str, Any]:
    state = _load_state()
    td = state["tidal"]
    if td.get("status") == "connected":
        return {"ok": True, "connected": True, "tidal": _public_tidal(td)}

    device_code = td.get("device_code") or ""
    if not device_code:
        raise ValueError("Tidal device code 없음 — connect/start 먼저 호출")

    token = await _tidal_poll_token(device_code, bool(td.get("_lab")))
    if not token:
        return {
            "ok": True,
            "connected": False,
            "pending": True,
            "tidal": _public_tidal(td),
        }

    if token.get("slow_down"):
        td["poll_interval"] = min(int(td.get("poll_interval", 5)) + 2, 15)
        _save_state(state)
        return {"ok": True, "connected": False, "pending": True, "slow_down": True, "tidal": _public_tidal(td)}

    if token.get("error"):
        msg = str(token.get("error_description") or token.get("error") or "tidal auth failed")
        td["status"] = "disconnected"
        td["message"] = msg
        _save_state(state)
        return {"ok": False, "connected": False, "error": msg, "tidal": _public_tidal(td)}

    TIDAL_CREDS.write_text(
        json.dumps({**token, "stored_at": _utc_now()}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    td["status"] = "connected"
    td["account_label"] = token.get("user_id") or "Tidal HiFi"
    td["connected_at"] = _utc_now()
    td["message"] = "Tidal 연결 완료"
    td.pop("device_code", None)
    td.pop("_lab", None)
    td.pop("_started_at", None)
    _save_state(state)
    for p in (PROVIDERS_DIR / "tidal-pending.json", PROVIDERS_DIR / "tidal-lab-approved.json"):
        p.unlink(missing_ok=True)
    return {"ok": True, "connected": True, "tidal": _public_tidal(td)}


def tidal_lab_approve() -> dict[str, Any]:
    """E2E: lab Tidal 승인 시뮬레이션."""
    _ensure_dir()
    (PROVIDERS_DIR / "tidal-lab-approved.json").write_text(
        json.dumps({"access_token": "lab", "user_id": "lab-user"}),
        encoding="utf-8",
    )
    return {"ok": True}


def tidal_disconnect() -> dict[str, Any]:
    state = _load_state()
    state["tidal"] = json.loads(json.dumps(DEFAULT_STATE["tidal"]))
    for p in (
        TIDAL_CREDS,
        PROVIDERS_DIR / "tidal-pending.json",
        PROVIDERS_DIR / "tidal-lab-approved.json",
    ):
        p.unlink(missing_ok=True)
    _save_state(state)
    return {"ok": True, "tidal": state["tidal"]}
