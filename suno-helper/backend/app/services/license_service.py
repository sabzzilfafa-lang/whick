"""라이선스 서비스 — whick.org 발급 RS256 라이선스 검증·활성화·갱신 (Phase A).

구조:
- 공개키 내장 (서버 개인키로만 서명 가능 — 위조 불가)
- machine_id: Windows MachineGuid 해시 (재설치 시 동일, 개인정보 아님)
- data/license.json: 발급 라이선스 보관
- 상태: valid | grace(만료+유예) | expired(잠금) | none(미활성)
- 만료 7일 전부터 온라인이면 자동 갱신 (기기정보 전송 없음 — 라이선스+machine_id만)
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from app.config import settings

LICENSE_FILE = "license.json"
PRODUCT = "suno-helper"
GRACE_DAYS = 30
RENEW_BEFORE_DAYS = 7

ACTIVATE_URL = os.environ.get("SUNO_ACTIVATE_URL", "https://whick.org/api/suno/activate")
RENEW_URL = os.environ.get("SUNO_RENEW_URL", "https://whick.org/api/suno/renew")

# whick.org 서버 공개키 — 서버 설치 시 교체 (server_license/README.md 5단계)
LICENSE_PUBLIC_PEM = os.environ.get("SUNO_LICENSE_PUBKEY", "") or """-----BEGIN PUBLIC KEY-----
REPLACE_WITH_SERVER_PUBLIC_KEY
-----END PUBLIC KEY-----"""


# ---------------------------------------------------------------------------
# machine_id
# ---------------------------------------------------------------------------
_machine_id_cache: str | None = None


def machine_id() -> str:
    """기기 고유 ID — Windows MachineGuid의 SHA256 해시. 개인정보 아님(되돌릴 수 없음)."""
    global _machine_id_cache
    if _machine_id_cache:
        return _machine_id_cache
    raw = ""
    if os.name == "nt":
        try:
            r = subprocess.run(
                ["reg", "query", r"HKLM\SOFTWARE\Microsoft\Cryptography", "/v", "MachineGuid"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
            )
            for line in (r.stdout or "").splitlines():
                if "MachineGuid" in line:
                    raw = line.split()[-1]
                    break
        except Exception:
            raw = ""
    if not raw:
        raw = f"fallback-{os.getcwd()}"
    import hashlib

    _machine_id_cache = hashlib.sha256(raw.encode()).hexdigest()[:32]
    return _machine_id_cache


# ---------------------------------------------------------------------------
# license.json I/O
# ---------------------------------------------------------------------------
def license_path() -> Path:
    d = settings.data_dir
    d.mkdir(parents=True, exist_ok=True)
    return d / LICENSE_FILE


def _load_saved() -> dict[str, Any]:
    p = license_path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_saved(data: dict[str, Any]) -> None:
    license_path().write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# JWT 검증 (의존성 최소화 — 표준 라이브러리만으로 RS256 verify)
# ---------------------------------------------------------------------------
def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def verify_license(token: str) -> dict[str, Any] | None:
    """RS256 서명 검증 + 클레임 확인. 유효하면 payload 반환, 아니면 None."""
    if not token or token.count(".") != 2:
        return None
    try:
        h_b64, p_b64, s_b64 = token.split(".")
        header = json.loads(_b64url_decode(h_b64))
        if header.get("alg") != "RS256":
            return None
        payload = json.loads(_b64url_decode(p_b64))
        sig = _b64url_decode(s_b64)
        signing_input = f"{h_b64}.{p_b64}".encode()

        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding

        pub = serialization.load_pem_public_key(LICENSE_PUBLIC_PEM.encode())
        pub.verify(sig, signing_input, padding.PKCS1v15(), hashes.SHA256())
    except Exception:
        return None
    if payload.get("product") != PRODUCT:
        return None
    if payload.get("iss") != "whick.org" or payload.get("aud") != PRODUCT:
        return None
    exp = payload.get("exp")
    if not exp or time.time() > float(exp):
        return None
    return payload


def _jwt_expiry(token: str) -> float | None:
    try:
        payload = json.loads(_b64url_decode(token.split(".")[1]))
        return float(payload.get("exp") or 0)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 상태
# ---------------------------------------------------------------------------
def license_status() -> dict[str, Any]:
    """현재 라이선스 상태 — 파이프라인 게이트와 UI가 참조."""
    saved = _load_saved()
    token = (saved.get("license") or "").strip()
    if not token:
        return {"state": "none", "email": "", "plan": "", "expires_at": "", "grace_until": ""}
    payload = verify_license(token)
    if payload is None:
        return {"state": "none", "email": "", "plan": "", "expires_at": "", "grace_until": ""}
    if payload.get("machine_id") != machine_id():
        return {"state": "mismatch", "email": payload.get("email", ""), "plan": payload.get("plan", ""), "expires_at": "", "grace_until": ""}
    exp = float(payload.get("exp") or 0)
    exp_dt = datetime.fromtimestamp(exp, tz=timezone.utc)
    now = datetime.now(tz=timezone.utc)
    grace_until = exp_dt + timedelta(days=GRACE_DAYS)
    if now <= exp_dt:
        state = "valid"
    elif now <= grace_until:
        state = "grace"
    else:
        state = "expired"
    return {
        "state": state,
        "email": payload.get("email", ""),
        "plan": payload.get("plan", ""),
        "expires_at": exp_dt.strftime("%Y-%m-%d"),
        "grace_until": grace_until.strftime("%Y-%m-%d"),
    }


def license_allows_new_jobs() -> bool:
    """새 인코딩/AI 작업 허용 여부 — 만료+유예 경과 시 잠금."""
    return license_status()["state"] in ("valid", "grace")


# ---------------------------------------------------------------------------
# 활성화 / 갱신
# ---------------------------------------------------------------------------
async def activate(install_token: str) -> dict[str, Any]:
    """활성화 토큰으로 라이선스 발급받아 저장."""
    mid = machine_id()
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.post(
            ACTIVATE_URL,
            json={"install_token": install_token.strip(), "machine_id": mid},
        )
    if r.status_code != 200:
        try:
            detail = r.json().get("message") or r.text[:200]
        except Exception:
            detail = r.text[:200]
        raise ValueError(f"활성화 실패 ({r.status_code}): {detail}")
    data = r.json().get("data") or r.json()
    license_token = (data.get("license") or "").strip()
    if not verify_license(license_token):
        raise ValueError("서버가 발급한 라이선스가 유효하지 않습니다")
    _save_saved({
        "license": license_token,
        "activated_at": datetime.now(tz=timezone.utc).isoformat(),
        "machine_id": mid,
    })
    return license_status()


async def renew() -> dict[str, Any]:
    """기존 라이선스로 갱신 (온라인 1회). 실패 시 기존 상태 유지."""
    saved = _load_saved()
    token = (saved.get("license") or "").strip()
    if not token:
        raise ValueError("갱신할 라이선스가 없습니다")
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.post(RENEW_URL, json={"license": token})
    if r.status_code != 200:
        raise ValueError(f"갱신 실패 ({r.status_code})")
    data = r.json().get("data") or r.json()
    new_token = (data.get("license") or "").strip()
    if not verify_license(new_token):
        raise ValueError("갱신된 라이선스가 유효하지 않습니다")
    _save_saved({**saved, "license": new_token, "renewed_at": datetime.now(tz=timezone.utc).isoformat()})
    return license_status()


async def maybe_auto_renew() -> dict[str, Any]:
    """만료 임박(7일 전)이면 자동 갱신 시도 — 백그라운드/시작 시 호출. 오류는 조용히 무시."""
    st = license_status()
    if st["state"] not in ("valid", "grace"):
        return st
    saved = _load_saved()
    exp = _jwt_expiry(saved.get("license") or "")
    if exp is None:
        return st
    days_left = (exp - time.time()) / 86400
    if days_left > RENEW_BEFORE_DAYS:
        return st
    try:
        return await renew()
    except Exception:
        return st


def deactivate_local() -> None:
    """로컬 라이선스 제거 (기기 이전 전 웹에서 해지 후 사용)."""
    p = license_path()
    if p.is_file():
        p.unlink()
