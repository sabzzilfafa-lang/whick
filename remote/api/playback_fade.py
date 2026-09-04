"""곡 전환 시 볼륨 페이드 — 샘플레이트 변경 클릭 완화."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path

LAST_PLAYBACK = Path(os.getenv("WHICK_LAST_PLAYBACK", "/var/lib/whick/run/last-playback.json"))
FADE_MS = int(os.getenv("WHICK_PLAYBACK_FADE_MS", "120"))
FADE_STEPS = max(2, int(os.getenv("WHICK_PLAYBACK_FADE_STEPS", "6")))


def read_last_playback() -> dict:
    if not LAST_PLAYBACK.is_file():
        return {}
    try:
        return json.loads(LAST_PLAYBACK.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_last_playback(*, sample_rate: int, is_dsd: bool = False) -> None:
    LAST_PLAYBACK.parent.mkdir(parents=True, exist_ok=True)
    LAST_PLAYBACK.write_text(
        json.dumps({"sample_rate": sample_rate, "is_dsd": is_dsd}, ensure_ascii=False),
        encoding="utf-8",
    )


def _set_volume(vol: int) -> None:
    from api.alsa_device import set_playback_volume

    try:
        from api.music_api import effective_volume_gain_db

        rg = float(effective_volume_gain_db())
    except Exception:
        rg = 0.0
    set_playback_volume(max(0, min(100, vol)), replay_gain_db=rg)


async def _fade_to(target: int, *, from_vol: int | None = None) -> None:
    current = from_vol if from_vol is not None else target
    if current == target:
        return
    delay = (FADE_MS / 1000.0) / FADE_STEPS
    for i in range(1, FADE_STEPS + 1):
        v = int(current + (target - current) * i / FADE_STEPS)
        _set_volume(v)
        await asyncio.sleep(delay)


async def transition_if_rate_changed(
    *,
    new_sample_rate: int,
    is_dsd: bool,
    current_volume: int,
) -> None:
    """SR/DSD↔PCM 전환 시 짧은 페이드."""
    if FADE_MS <= 0:
        return
    last = read_last_playback()
    old_sr = int(last.get("sample_rate") or 0)
    old_dsd = bool(last.get("is_dsd"))
    if old_sr <= 0:
        write_last_playback(sample_rate=new_sample_rate, is_dsd=is_dsd)
        return
    if old_sr == new_sample_rate and old_dsd == is_dsd:
        return
    await _fade_to(0, from_vol=current_volume)
    subprocess.run(["mpc", "--quiet", "stop"], timeout=3, capture_output=True, check=False)
    await asyncio.sleep(0.05)
    await _fade_to(current_volume, from_vol=0)
    write_last_playback(sample_rate=new_sample_rate, is_dsd=is_dsd)
