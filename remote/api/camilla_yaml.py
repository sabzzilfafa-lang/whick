from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from api.dac_preprocess import (
    dac_preprocess_enabled,
    dac_preprocess_filter_yaml_lines,
    dac_preprocess_pipeline_ids,
    ensure_fir_coefficient_files,
)
PIPE_BASE_RATE = int(os.getenv("WHICK_DSP_WORKING_RATE", "48000"))


def resolve_camilla_base_rate(profile: dict[str, Any]) -> int:
    """DSP 처리 샘플레이트. 전처리 ON이어도 DAC 한도 밖 OS는 쓰지 않는다."""
    capture_hz = _capture_rate_hz(profile)
    if dac_preprocess_enabled(profile):
        from api.dac_preprocess import dac_os_rate

        os_hz = dac_os_rate(profile=profile)
        if os_hz > capture_hz:
            return os_hz
    return capture_hz


def _capture_rate_hz(profile: dict[str, Any]) -> int:
    try:
        from api.camilla_loopback import transport_mode
        from api.playback_config import dsp_pipe_rate_hz, sync_dsp_pipe_env

        if transport_mode() == "fifo":
            sync_dsp_pipe_env(profile)
            return dsp_pipe_rate_hz(profile)
        from api.camilla_loopback import loop_rate_hz

        return loop_rate_hz()
    except Exception:
        return PIPE_BASE_RATE


def _alsa_capture_playback_devices() -> tuple[str, str]:
    from api.alsa_device import plughw_to_hw, resolve_direct_alsa_device, resolve_dsp_alsa_device
    from api.camilla_loopback import loopback_capture_device, transport_mode

    capture = loopback_capture_device()
    if transport_mode() == "fifo":
        playback = resolve_dsp_alsa_device() or resolve_direct_alsa_device()
    else:
        playback = plughw_to_hw(resolve_direct_alsa_device()) or resolve_direct_alsa_device()
    return capture, playback


def _alsa_capture_format() -> str:
    """Loopback/MPD 입력 포맷 — aloop capture는 S32LE 고정. DAC 비트와 무관."""
    return "S32LE"


def _alsa_playback_format(playback_device: str = "") -> str:
    """DAC hw_params에 있는 포맷만. USB DB·16bit 바닥으로 열지 않는다."""
    explicit = (os.getenv("WHICK_CAMILLA_ALSA_FORMAT") or "").strip()
    if explicit:
        return explicit
    try:
        from api.alsa_device import pick_playback_camilla_format
        from api.dac_capability import load_dac_capability

        preferred = str(load_dac_capability().get("probed_alsa_format") or "").strip() or None
        return pick_playback_camilla_format(playback_device, preferred=preferred)
    except Exception:
        return "S32LE"


def pipe_base_yaml(profile: dict[str, Any]) -> str:
    """상주 Camilla devices — 전처리 ON/OFF 공통. 전처리는 필터만 추가."""
    from api.camilla_loopback import transport_mode

    capture_hz = _capture_rate_hz(profile)
    process_hz = resolve_camilla_base_rate(profile)
    capture, playback = _alsa_capture_playback_devices()
    play_fmt = _alsa_playback_format(playback)
    cap_fmt = _alsa_capture_format()
    mode = transport_mode()
    resample = process_hz != capture_hz
    extra = ""
    if resample:
        extra = f"""  capture_samplerate: {capture_hz}
  resampler:
    type: Synchronous
"""
    if mode == "fifo":
        return f"""devices:
  samplerate: {process_hz}
  chunksize: 1024
  queuelimit: 4
{extra}  capture:
    type: Stdin
    channels: 2
    format: FLOAT32LE
    read_bytes: 0
  playback:
    type: Alsa
    channels: 2
    device: "{playback}"
    format: {play_fmt}
"""
    return f"""devices:
  samplerate: {process_hz}
  chunksize: 1024
  queuelimit: 4
{extra}  capture:
    type: Alsa
    channels: 2
    device: "{capture}"
    format: {cap_fmt}
  playback:
    type: Alsa
    channels: 2
    device: "{playback}"
    format: {play_fmt}
"""

SWAP_MIXER_YAML = """mixers:
  whick_swap_lr:
    channels:
      in: 2
      out: 2
    mapping:
      - dest: 0
        sources:
          - channel: 1
            gain: 0.0
      - dest: 1
        sources:
          - channel: 0
            gain: 0.0
"""

IDENTITY_MIXER_YAML = """mixers:
  whick_swap_lr:
    channels:
      in: 2
      out: 2
    mapping:
      - dest: 0
        sources:
          - channel: 0
            gain: 0.0
      - dest: 1
        sources:
          - channel: 1
            gain: 0.0
"""

# 상주 Camilla WS — 필터·mixer·pipeline 슬롯 고정 (토글 시 SetConfig만)
_RESIDENT_EQ_BANDS = [
    {"freq": 60, "q": 1.0},
    {"freq": 120, "q": 1.0},
    {"freq": 250, "q": 1.0},
    {"freq": 500, "q": 1.1},
    {"freq": 1000, "q": 1.0},
    {"freq": 2000, "q": 1.0},
    {"freq": 5000, "q": 0.9},
    {"freq": 10000, "q": 0.8},
]


def swap_mixer_yaml(swap_channels: bool) -> str:
    return SWAP_MIXER_YAML if swap_channels else IDENTITY_MIXER_YAML


def _normalize_resident_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """DSP OFF — gain만 0으로, yaml 구조는 유지."""
    if profile.get("enabled") is not False:
        return profile
    return {
        **profile,
        "eqEnabled": False,
        "dacPreprocessEnabled": False,
        "swapChannels": False,
        "peaking": [],
        "userPeaking": [],
        "roomPeaking": [],
        "balanceDb": {"left": 0, "right": 0},
        "masterGainDb": 0.0,
    }


def _stable_peaking_bands(profile: dict[str, Any], *, eq_on: bool) -> list[dict[str, Any]]:
    """8밴드 UI 슬롯 + 룸보정 등 그리드 밖 peaking 을 모두 Camilla 로 보낸다.

    예전에는 resident 8주파수만 내보내 100/125/200Hz 룸컷이 yaml 에서 사라졌다.
    peaking 에 없는 room 주파수만 보완한다(user EQ merge 는 peaking 유지).
    """
    src = list(profile.get("peaking") or [])
    if not src:
        src = list(profile.get("userPeaking") or [])
    room = list(profile.get("roomPeaking") or [])
    by_freq: dict[int, dict[str, Any]] = {}
    for band in src:
        freq = int(band.get("freq") or 0)
        if freq <= 0:
            continue
        by_freq[freq] = {
            "freq": freq,
            "q": float(band.get("q") or 1),
            "gainDb": float(band.get("gainDb") or 0),
        }
    for band in room:
        freq = int(band.get("freq") or 0)
        if freq <= 0 or freq in by_freq:
            continue
        by_freq[freq] = {
            "freq": freq,
            "q": float(band.get("q") or 1),
            "gainDb": float(band.get("gainDb") or 0),
        }

    bands: list[dict[str, Any]] = []
    resident = {int(d["freq"]) for d in _RESIDENT_EQ_BANDS}
    for defn in _RESIDENT_EQ_BANDS:
        freq = int(defn["freq"])
        band = by_freq.get(freq) or defn
        gain = float(band.get("gainDb") or 0) if eq_on else 0.0
        bands.append(
            {
                "freq": freq,
                "q": float(band.get("q") or defn["q"]),
                "gainDb": gain,
            }
        )
    extras: list[dict[str, Any]] = []
    for freq, band in sorted(by_freq.items()):
        if freq in resident:
            continue
        gain = float(band.get("gainDb") or 0) if eq_on else 0.0
        if abs(gain) < 0.05:
            continue
        extras.append(
            {
                "freq": freq,
                "q": float(band.get("q") or 1),
                "gainDb": gain,
            }
        )
    return bands + extras


def _eq_active(profile: dict[str, Any]) -> bool:
    if profile.get("enabled") is False:
        return False
    if profile.get("eqEnabled") is False:
        # peaking 배열만 있고 gain이 전부 0이면 EQ 비활성
        peaking = profile.get("peaking") or profile.get("userPeaking") or []
        if any(abs(float(b.get("gainDb") or 0)) >= 0.05 for b in peaking):
            return True
        balance = profile.get("balanceDb") or {"left": 0, "right": 0}
        left = float(balance.get("left") or 0)
        right = float(balance.get("right") or 0)
        return left > 0.05 or right > 0.05
    return True


def profile_to_camilla_yaml(
    profile: dict[str, Any],
    *,
    swap_channels: bool = False,
    profile_path: Path | None = None,
    stable_pipeline: bool = False,
) -> str:
    dac_on = dac_preprocess_enabled(profile) if profile.get("enabled") is not False else False
    eq_on = _eq_active(profile)
    if stable_pipeline:
        peaking = _stable_peaking_bands(profile, eq_on=eq_on and profile.get("enabled") is not False)
        balance = profile.get("balanceDb") or {"left": 0, "right": 0}
        if not eq_on or profile.get("enabled") is False:
            balance = {"left": 0, "right": 0}
    elif not dac_on and not eq_on and not swap_channels:
        return "# whick passthrough\n"
    else:
        peaking = profile.get("peaking") or [] if eq_on else []
        balance = profile.get("balanceDb") or {"left": 0, "right": 0}
    updated = profile.get("updatedAt") or datetime.now(timezone.utc).isoformat()
    lines = [
        "# Whick 청취 · CamillaDSP",
        f"# updated: {updated}",
        "filters:",
    ]
    filter_ids: list[str] = []
    dac_ids: list[str] = []

    if dac_on:
        dac_ids = dac_preprocess_pipeline_ids()
        lines.extend(dac_preprocess_filter_yaml_lines(profile, profile_path))

    for i, band in enumerate(peaking):
        gain = float(band.get("gainDb") or 0)
        if not stable_pipeline and abs(gain) < 0.05:
            continue
        fid = f"whick_eq_{i}"
        filter_ids.append(fid)
        lines.extend(
            [
                f"  {fid}:",
                "    type: Biquad",
                "    parameters:",
                "      type: Peaking",
                f"      freq: {int(band.get('freq') or 0)}",
                f"      q: {float(band.get('q') or 1)}",
                f"      gain: {gain:.2f}",
            ]
        )

    left = float(balance.get("left") or 0)
    right = float(balance.get("right") or 0)
    master = max(-12.0, min(12.0, float(profile.get("masterGainDb") or 0)))
    if profile.get("enabled") is False:
        master = 0.0
    if stable_pipeline or abs(master) >= 0.05:
        filter_ids.append("whick_master_l")
        lines.extend(
            [
                "  whick_master_l:",
                "    type: Gain",
                "    parameters:",
                f"      gain: {master:.2f}",
            ]
        )
        filter_ids.append("whick_master_r")
        lines.extend(
            [
                "  whick_master_r:",
                "    type: Gain",
                "    parameters:",
                f"      gain: {master:.2f}",
            ]
        )
    if stable_pipeline or left > 0.05:
        filter_ids.append("whick_balance_l")
        lines.extend(
            [
                "  whick_balance_l:",
                "    type: Gain",
                "    parameters:",
                f"      gain: {left:.2f}",
            ]
        )
    if stable_pipeline or right > 0.05:
        filter_ids.append("whick_balance_r")
        lines.extend(
            [
                "  whick_balance_r:",
                "    type: Gain",
                "    parameters:",
                f"      gain: {right:.2f}",
            ]
        )

    if not stable_pipeline and not (swap_channels or dac_ids or filter_ids):
        return "# whick passthrough\n"

    lines.append("")
    lines.append("pipeline:")
    if stable_pipeline or swap_channels:
        lines.extend(["  - type: Mixer", "    name: whick_swap_lr"])
    if stable_pipeline or dac_ids or filter_ids:
        for ch in (0, 1):
            ch_filters: list[str] = []
            for fid in dac_ids:
                ch_filters.append(fid)
            for fid in filter_ids:
                if fid == "whick_balance_l" and ch != 0:
                    continue
                if fid == "whick_balance_r" and ch != 1:
                    continue
                if fid == "whick_master_l" and ch != 0:
                    continue
                if fid == "whick_master_r" and ch != 1:
                    continue
                ch_filters.append(fid)
            if not ch_filters:
                continue
            lines.extend(["  - type: Filter", f"    channel: {ch}", "    names:"])
            for fid in ch_filters:
                lines.append(f"      - {fid}")

    return "\n".join(lines) + "\n"


def devices_yaml(profile: dict[str, Any]) -> str:
    """전처리 ON/OFF 동일 devices 계약. 전처리는 pipeline 필터만 추가."""
    return pipe_base_yaml(profile).rstrip()


def full_camilla_config(profile: dict[str, Any]) -> str:
    import os

    profile = _normalize_resident_profile(profile)
    if dac_preprocess_enabled(profile):
        ensure_fir_coefficient_files(profile=profile)
    profile_path = Path(os.getenv("WHICK_CAMILLA_PROFILE", "/var/lib/whick/camilla/profile.yml"))
    swap = bool(profile.get("swapChannels"))
    parts = [
        "---",
        devices_yaml(profile).rstrip(),
        swap_mixer_yaml(swap).rstrip(),
        profile_to_camilla_yaml(
            profile,
            swap_channels=True,
            profile_path=profile_path,
            stable_pipeline=True,
        ).rstrip(),
    ]
    return "\n".join(parts) + "\n"


def ws_camilla_config(profile: dict[str, Any]) -> str:
    """websocket SetConfig용 — document marker 제거, pipeline 슬롯 고정."""
    profile = _normalize_resident_profile(profile)
    swap = bool(profile.get("swapChannels"))
    profile_path = Path(os.getenv("WHICK_CAMILLA_PROFILE", "/var/lib/whick/camilla/profile.yml"))
    parts = [
        devices_yaml(profile).rstrip(),
        swap_mixer_yaml(swap).rstrip(),
        profile_to_camilla_yaml(
            profile,
            swap_channels=True,
            profile_path=profile_path,
            stable_pipeline=True,
        ).rstrip(),
    ]
    return "\n".join(parts) + "\n"


def ws_camilla_filters_config(profile: dict[str, Any]) -> str:
    """EQ/좌우반전 등 필터·믹서만 — Camilla 2.x PatchConfig용 (devices 생략).

    apply_profile이 PatchConfig로 보내고, 실패 시에만 SetConfig(full)로 폴백한다.
    """
    profile = _normalize_resident_profile(profile)
    swap = bool(profile.get("swapChannels"))
    profile_path = Path(os.getenv("WHICK_CAMILLA_PROFILE", "/var/lib/whick/camilla/profile.yml"))
    parts = [
        swap_mixer_yaml(swap).rstrip(),
        profile_to_camilla_yaml(
            profile,
            swap_channels=True,
            profile_path=profile_path,
            stable_pipeline=True,
        ).rstrip(),
    ]
    return "\n".join(parts) + "\n"
