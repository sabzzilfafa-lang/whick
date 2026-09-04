"""Camilla 입력 경로 — ALSA Loopback 우선, 없으면 FIFO 상주 폴백."""
from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Literal

from api.asound import asound_root

DEFAULT_LOOP_RATE = 48000
DEFAULT_LOOP_BITS = 32
Transport = Literal["aloop", "fifo"]

FIFO_PATH = Path(os.getenv("WHICK_CAMILLA_FIFO", "/var/lib/whick/run/camilla-in.pcm"))

# resolve_transport()는 설정 변경·다음곡마다 여러 번 호출된다. aloop 미탑재 환경에서
# 매번 modprobe 재시도(~1초 실패)를 반복하면 필터 교체 1건에 6초 이상이 누적된다.
# 프로세스 캐시로 실패를 기억하고, DAC hotplug 재바인딩 시에만 재probe한다.
_transport_cache: tuple[Transport, dict[str, Any]] | None = None


def invalidate_transport_cache() -> None:
    """DAC hotplug 재바인딩 등 실제 하드웨어 변화 시에만 호출."""
    global _transport_cache
    _transport_cache = None


def loop_rate_hz() -> int:
    try:
        return int(os.getenv("WHICK_CAMILLA_LOOP_RATE", str(DEFAULT_LOOP_RATE)))
    except ValueError:
        return DEFAULT_LOOP_RATE


def loop_bits() -> int:
    try:
        return int(os.getenv("WHICK_CAMILLA_LOOP_BITS", str(DEFAULT_LOOP_BITS)))
    except ValueError:
        return DEFAULT_LOOP_BITS


def loop_mpd_format() -> str:
    return f"{loop_rate_hz()}:{loop_bits()}:2"


def _cards_text() -> str:
    cards = asound_root() / "cards"
    try:
        return cards.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def loopback_card_name() -> str | None:
    explicit = (os.getenv("WHICK_LOOPBACK_CARD") or "").strip()
    if explicit:
        # 강제 카드명 — 실제 존재 여부는 호출측에서 cards로 확인 가능
        if explicit in _cards_text() or f"[{explicit}" in _cards_text():
            return explicit
        if "Loopback" in _cards_text():
            return "Loopback"
    text = _cards_text()
    for line in text.splitlines():
        m = re.match(r"\s*\d+\s+\[([^\]]+)\]\s*:\s*Loopback", line)
        if m:
            return m.group(1).strip()
        if "Loopback" in line:
            m2 = re.search(r"\[([^\]]+)\]", line)
            if m2:
                return m2.group(1).strip()
    return None


def ensure_aloop() -> dict[str, Any]:
    if loopback_card_name():
        return {"ok": True, "card": loopback_card_name(), "loaded": False}
    script = Path("/app/docker/ensure-aloop.sh")
    detail = ""
    try:
        if script.is_file():
            proc = subprocess.run(
                ["sh", str(script)],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            detail = ((proc.stdout or "") + (proc.stderr or "")).strip()
        else:
            proc = subprocess.run(
                ["modprobe", "snd-aloop", "index=10", "id=Loopback", "pcm_substreams=4"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            detail = ((proc.stdout or "") + (proc.stderr or "")).strip()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    for _ in range(10):
        name = loopback_card_name()
        if name:
            return {"ok": True, "card": name, "loaded": True, "detail": detail}
        time.sleep(0.1)
    return {
        "ok": False,
        "error": "Loopback card not found after modprobe",
        "detail": detail,
    }


def ensure_fifo() -> dict[str, Any]:
    try:
        FIFO_PATH.parent.mkdir(parents=True, exist_ok=True)
        if FIFO_PATH.exists():
            if not FIFO_PATH.is_fifo():
                FIFO_PATH.unlink()
                os.mkfifo(FIFO_PATH, 0o666)
        else:
            os.mkfifo(FIFO_PATH, 0o666)
        try:
            os.chmod(FIFO_PATH, 0o666)
        except OSError:
            pass
        return {"ok": True, "path": str(FIFO_PATH)}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "path": str(FIFO_PATH)}


def resolve_transport() -> tuple[Transport, dict[str, Any]]:
    """강제 env → aloop. fifo는 명시(WHICK_CAMILLA_TRANSPORT=fifo)일 때만.

    과거: aloop 실패 시 자동 fifo 폴백 → MPD pipe hang(목록 OK·재생 불가) 반복.
    현재: 자동 fifo 폴백 금지. aloop 실패는 호출측(entrypoint)이 DSP off·direct ALSA.
    """
    global _transport_cache
    if _transport_cache is not None:
        return _transport_cache

    forced = (os.getenv("WHICK_CAMILLA_TRANSPORT") or "").strip().lower()
    if forced == "fifo":
        result: tuple[Transport, dict[str, Any]] = ("fifo", ensure_fifo())
    else:
        # forced==aloop 또는 auto — aloop만 시도 (실패해도 fifo로 내리지 않음)
        aloop = ensure_aloop()
        result = ("aloop", aloop)

    _transport_cache = result
    return result


def transport_mode() -> Transport:
    mode, _ = resolve_transport()
    return mode


def loopback_feed_device() -> str:
    explicit = (os.getenv("WHICK_LOOPBACK_FEED") or "").strip()
    if explicit:
        return explicit
    card = loopback_card_name() or "Loopback"
    return f"plughw:CARD={card},DEV=0"


def loopback_capture_device() -> str:
    explicit = (os.getenv("WHICK_LOOPBACK_CAPTURE") or "").strip()
    if explicit:
        return explicit
    card = loopback_card_name() or "Loopback"
    return f"hw:CARD={card},DEV=1"


def camilla_fifo_path() -> Path:
    return FIFO_PATH
