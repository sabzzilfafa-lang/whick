"""DAC CPU 전처리 — 미니PC에서 가능한 디지털 구간 전부 (DAC 칩 내부 제외).

PCM → Digital Filter → Oversampling → Interpolation → Noise Shaping → ΔΣ Modulator
→ (DAC Core · Analog LPF · Output Buffer · 아날로그 출력은 하드웨어)

오버샘플링: RAM 32GB+ → 8× · 그 미만(16GB급) → 4× (자동). UI/API로 수동 4×/8× 가능.
"""
from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any

BASE_RATE = int(os.getenv("WHICK_DAC_BASE_RATE", "48000"))
RAM_GB_FOR_8X = int(os.getenv("WHICK_DAC_RAM_GB_8X", "32"))
RAM_GB_FOR_4X = int(os.getenv("WHICK_DAC_RAM_GB_4X", "16"))
OS_FACTORS = (4, 8)

DIG_FIR_TAPS = 384
OS_FIR_TAPS = 256
INTERP_FIR_TAPS = 128

DIG_CUTOFF_HZ = 22000.0
OS_CUTOFF_HZ = 20000.0
INTERP_CUTOFF_HZ = 18000.0

DSM_OUTPUT_BITS = 24


def dac_preprocess_enabled(profile: dict[str, Any]) -> bool:
    return profile.get("dacPreprocessEnabled", False) is not False


def detect_system_ram_gb() -> float | None:
    raw = os.getenv("WHICK_DEVICE_RAM_GB", "").strip()
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    return kb / (1024 * 1024)
    except OSError:
        pass
    return None


def recommended_dac_os_factor(ram_gb: float | None = None) -> int:
    """RAM 32GB+ → 8×, 16GB급(32GB 미만) → 4×."""
    ram = ram_gb if ram_gb is not None else detect_system_ram_gb()
    if ram is None:
        return 4
    return 8 if ram >= RAM_GB_FOR_8X else 4


def _normalize_os_factor(value: Any) -> int:
    return 8 if int(value or 0) == 8 else 4


def resolve_dac_os_factor(profile: dict[str, Any]) -> int:
    env = os.getenv("WHICK_DAC_OS_FACTOR", "").strip()
    if env in ("4", "8"):
        return int(env)
    if profile.get("dacOsFactorAuto", True) is False:
        return _normalize_os_factor(profile.get("dacOsFactor"))
    return recommended_dac_os_factor()


def dac_os_rate(os_factor: int | None = None, profile: dict[str, Any] | None = None) -> int:
    """희망 OS rate — 반드시 DAC PCM 한도 이하. 한도 밖이면 factor를 내려 맞춤 (사망 금지)."""
    factor = os_factor if os_factor in OS_FACTORS else resolve_dac_os_factor(profile or {})
    desired = BASE_RATE * factor
    try:
        from api.dac_capability import effective_pcm_max_rate_hz

        max_hz = effective_pcm_max_rate_hz()
    except Exception:
        max_hz = BASE_RATE
    if desired <= max_hz:
        return desired
    # 4×/8×가 DAC 한도 초과 → 허용 가능한 최대 factor (1×=BASE_RATE)
    for f in (8, 4, 1):
        cand = BASE_RATE * f
        if cand <= max_hz:
            return cand
    return max(BASE_RATE, min(desired, max_hz))


def dac_os_factor_info(profile: dict[str, Any]) -> dict[str, Any]:
    ram = detect_system_ram_gb()
    effective = resolve_dac_os_factor(profile)
    auto = profile.get("dacOsFactorAuto", True) is not False
    rate = dac_os_rate(effective, profile)
    clamped = rate < (BASE_RATE * effective)
    try:
        from api.dac_capability import effective_pcm_max_rate_hz

        max_hz = int(effective_pcm_max_rate_hz())
    except Exception:
        max_hz = BASE_RATE
    # UI: DAC 한도보다 큰 배수 칩은 숨기지 않고 disabled (서버는 이미 clamp)
    available = [f for f in OS_FACTORS if (BASE_RATE * f) <= max_hz]
    max_factor = max(available) if available else 1
    return {
        "dacOsFactor": effective,
        "dacOsFactorAuto": auto,
        "dacOsFactorManual": profile.get("dacOsFactor"),
        "dacOsRateHz": rate,
        "dacOsRateClamped": clamped,
        "dacPcmMaxRateHz": max_hz,
        "dacOsFactorsAvailable": available,
        "dacOsMaxFactor": max_factor,
        "recommendedOsFactor": recommended_dac_os_factor(ram),
        "systemRamGb": round(ram, 1) if ram is not None else None,
        "ramBaseline4xGb": RAM_GB_FOR_4X,
        "ramBaseline8xGb": RAM_GB_FOR_8X,
    }


def camilla_dir() -> Path:
    return Path(os.getenv("WHICK_CAMILLA_DIR", "/var/lib/whick/camilla"))


def fir_dir() -> Path:
    return camilla_dir() / "fir"


def _blackman(n: int, i: int) -> float:
    if n <= 1:
        return 1.0
    return 0.42 - 0.5 * math.cos(2 * math.pi * i / (n - 1)) + 0.08 * math.cos(4 * math.pi * i / (n - 1))


def windowed_sinc_lowpass(taps: int, cutoff_hz: float, sample_rate: float) -> list[float]:
    fc = cutoff_hz / sample_rate
    m = taps - 1
    out: list[float] = []
    for n in range(taps):
        x = n - m / 2.0
        if abs(x) < 1e-12:
            s = 2.0 * fc
        else:
            s = math.sin(2.0 * math.pi * fc * x) / (math.pi * x)
        out.append(s * _blackman(taps, n))
    norm = sum(out) or 1.0
    return [v / norm for v in out]


def write_fir_text(path: Path, coeffs: list[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(f"{v:.18e}" for v in coeffs) + "\n", encoding="utf-8")


def _process_rate_hz(profile: dict[str, Any]) -> int:
    """Camilla 실제 처리 샘플레이트 — FIR 계수는 반드시 이 rate에 맞춘다.

    resolve_camilla_base_rate 는 os_hz(희망 OS rate)가 capture_hz 보다 클 때만
    os_hz 를 쓰고, 아니면 capture_hz 로 떨어진다. FIR 계수를 dac_os_rate(희망값)로
    만들면 os_hz < capture_hz(DAC 한도로 1× 클램프 등)일 때 pipe_base_yaml 의
    samplerate 와 어긋나 cutoff 가 잘못 계산된다.
    """
    from api.camilla_yaml import resolve_camilla_base_rate

    return resolve_camilla_base_rate(profile)


def ensure_fir_coefficient_files(os_factor: int | None = None, profile: dict[str, Any] | None = None) -> dict[str, str]:
    rate = _process_rate_hz(profile or {})
    root = fir_dir()
    specs = {
        "whick_dac_dig_fir": (DIG_FIR_TAPS, DIG_CUTOFF_HZ, rate),
        "whick_dac_os_fir": (OS_FIR_TAPS, OS_CUTOFF_HZ, rate),
        "whick_dac_interp_fir": (INTERP_FIR_TAPS, INTERP_CUTOFF_HZ, rate),
    }
    paths: dict[str, str] = {}
    for name, (taps, cutoff, sample_rate) in specs.items():
        fname = f"{name}_{sample_rate}.txt"
        fpath = root / fname
        if not fpath.is_file():
            write_fir_text(fpath, windowed_sinc_lowpass(taps, cutoff, sample_rate))
        paths[name] = str(fpath)
    return paths


def dac_preprocess_devices_yaml(profile: dict[str, Any]) -> str:
    """하위 호환 — devices 계약은 camilla_yaml.pipe_base_yaml 단일."""
    from api.camilla_yaml import pipe_base_yaml

    return pipe_base_yaml(profile).rstrip()


def _fir_conv_block(fid: str, rel_path: str) -> list[str]:
    return [
        f"  {fid}:",
        "    type: Conv",
        "    description: Whick DAC CPU preprocess",
        "    parameters:",
        "      type: Raw",
        f"      filename: {rel_path}",
        "      format: TEXT",
    ]


def dac_preprocess_filter_yaml_lines(profile: dict[str, Any], profile_path: Path | None = None) -> list[str]:
    rate = _process_rate_hz(profile)
    ensure_fir_coefficient_files(profile=profile)
    lines: list[str] = []

    # 절대경로 사용: WS SetConfig(파일 없이 YAML만 전송)는 config 파일 위치를 기준으로
    # 상대경로를 못 풀어 "Could not open coefficient file" 로 검증 실패 → 매번 무거운
    # restart_daemon()로 떨어져 MPD 파이프와 충돌(끊김/크래시)을 유발했다.
    for fid in ("whick_dac_dig_fir", "whick_dac_os_fir", "whick_dac_interp_fir"):
        lines.extend(_fir_conv_block(fid, str(fir_dir() / f"{fid}_{rate}.txt")))

    lines.extend(
        [
            "  whick_dac_ns:",
            "    type: Dither",
            "    description: Noise Shaping",
            "    parameters:",
            "      type: Highpass",
            f"      bits: {DSM_OUTPUT_BITS}",
            "  whick_dac_dsm_lim:",
            "    type: Limiter",
            "    description: Delta-Sigma headroom",
            "    parameters:",
            "      soft_clip: true",
            "      clip_limit: -0.3",
            "  whick_dac_dsm:",
            "    type: Dither",
            "    description: Delta-Sigma Modulator output word",
            "    parameters:",
            "      type: Flat",
            f"      bits: {DSM_OUTPUT_BITS}",
            "      amplitude: 2",
        ]
    )
    return lines


def dac_preprocess_pipeline_ids() -> list[str]:
    return [
        "whick_dac_dig_fir",
        "whick_dac_os_fir",
        "whick_dac_interp_fir",
        "whick_dac_dsm_lim",
        "whick_dac_ns",
        "whick_dac_dsm",
    ]


def dac_os_playback_rate(profile: dict[str, Any] | None = None) -> int:
    return dac_os_rate(profile=profile or {})
