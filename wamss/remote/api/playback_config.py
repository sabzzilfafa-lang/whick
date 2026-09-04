"""재생 설정 SSOT — DSP pipe rate · env 동기화."""
from __future__ import annotations

import os
from typing import Any

# 48/96: DAC 실측이 낮은 장비용. 192/384: 고성능 DAC (probe 후 clamp로만 도달).
ALLOWED_DSP_PIPE_RATES_KHZ = (48, 96, 192, 384)
# probe 전 기본은 안전 바닥 — 어떤 DAC든 일단 동작
DEFAULT_DSP_PIPE_RATE_KHZ = 48
DEFAULT_DSP_PIPE_BITS = 32


def normalize_dsp_pipe_rate_khz(value: Any) -> int:
    """허용 pipe rate(kHz)로 정규화."""
    if value is None:
        return DEFAULT_DSP_PIPE_RATE_KHZ
    if isinstance(value, str):
        value = value.strip().lower().replace("khz", "").replace("k", "")
    try:
        n = int(float(value))
    except (TypeError, ValueError):
        return DEFAULT_DSP_PIPE_RATE_KHZ
    if n >= 1000:
        n = n // 1000
    if n in ALLOWED_DSP_PIPE_RATES_KHZ:
        return n
    # 가장 가까운 허용값 이하로 내림 (DAC 클램프용)
    below = [r for r in ALLOWED_DSP_PIPE_RATES_KHZ if r <= n]
    return below[-1] if below else ALLOWED_DSP_PIPE_RATES_KHZ[0]


def _dac_max_pipe_rate_khz() -> int | None:
    """effective DAC PCM 상한(kHz). probe 전엔 안전 바닥."""
    try:
        from api.dac_capability import effective_pcm_max_rate_hz

        return max(1, effective_pcm_max_rate_hz() // 1000)
    except Exception:
        return None


def dsp_pipe_rate_hz(profile: dict[str, Any] | None = None) -> int:
    """프로필 희망 rate → DAC 한도로 clamp. 음질 감쇄가 아니라 DAC가 받을 수 있는 최선."""
    chosen = DEFAULT_DSP_PIPE_RATE_KHZ
    if profile:
        khz = profile.get("dspPipeRateKhz")
        if khz is not None:
            chosen = normalize_dsp_pipe_rate_khz(khz)
        else:
            env = (os.getenv("WHICK_DSP_PIPE_RATE") or "").strip()
            if env:
                try:
                    hz = int(env)
                    chosen = normalize_dsp_pipe_rate_khz(hz // 1000 if hz >= 1000 else hz)
                except ValueError:
                    pass
    else:
        env = (os.getenv("WHICK_DSP_PIPE_RATE") or "").strip()
        if env:
            try:
                hz = int(env)
                chosen = normalize_dsp_pipe_rate_khz(hz // 1000 if hz >= 1000 else hz)
            except ValueError:
                pass
    dac_max = _dac_max_pipe_rate_khz()
    if dac_max is not None and chosen > dac_max:
        chosen = normalize_dsp_pipe_rate_khz(dac_max)
    return chosen * 1000


def dsp_pipe_bits() -> int:
    try:
        return int(os.getenv("WHICK_DSP_PIPE_BITS", str(DEFAULT_DSP_PIPE_BITS)))
    except ValueError:
        return DEFAULT_DSP_PIPE_BITS


def dsp_pipe_format(profile: dict[str, Any] | None = None) -> str:
    return f"{dsp_pipe_rate_hz(profile)}:{dsp_pipe_bits()}:2"


def sync_dsp_pipe_env(profile: dict[str, Any] | None = None) -> int:
    """pipe 스크립트·MPD·상주 Camilla FIFO rate env (프로세스 내)."""
    hz = dsp_pipe_rate_hz(profile)
    os.environ["WHICK_DSP_PIPE_RATE"] = str(hz)
    os.environ["WHICK_DSP_PIPE_BITS"] = str(dsp_pipe_bits())
    # fifo 상주: MPD pipe·Camilla stdin·DAC playback rate 일치 (48k 고정 시 DAC EINVAL)
    os.environ["WHICK_CAMILLA_LOOP_RATE"] = str(hz)
    os.environ["WHICK_CAMILLA_LOOP_BITS"] = str(dsp_pipe_bits())
    return hz


def playback_config_summary(profile: dict[str, Any] | None = None) -> dict[str, Any]:
    khz = dsp_pipe_rate_hz(profile) // 1000
    return {
        "dspPipeRateKhz": khz,
        "dspPipeRateHz": khz * 1000,
        "allowedDspPipeRatesKhz": list(ALLOWED_DSP_PIPE_RATES_KHZ),
        "dspPipeFormat": dsp_pipe_format(profile),
    }
