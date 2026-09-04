"""ALSA 장치 해석 — hw 직결(bit-perfect) · HW 볼륨 · 장치 프로브."""
from __future__ import annotations

from typing import Any

import os
import re
import subprocess
from pathlib import Path

from api.asound import asound_root


def _shell_resolve(*, mode: str) -> str:
    script = Path("/app/docker/resolve-alsa-device.sh")
    if not script.is_file():
        return ""
    env = {**os.environ, "WHICK_ALSA_DEVICE_MODE": mode}
    try:
        proc = subprocess.run(
            ["sh", str(script), "--print"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            env=env,
        )
        return (proc.stdout or "").strip()
    except Exception:
        return ""


def plughw_to_hw(device: str) -> str:
    if device.startswith("plughw:"):
        return "hw:" + device[len("plughw:") :]
    return device


# ALSA dump-hw-params 토큰 → CamillaDSP 2.0.3 포맷명. 우선순위 = 품질 높은 순.
_ALSA_TO_CAMILLA_FORMAT = (
    ("S32_LE", "S32LE"),
    ("S24_3LE", "S24LE3"),
    ("S24_3_LE", "S24LE3"),
    ("S24_LE", "S24LE"),
    ("S16_LE", "S16LE"),
)


def parse_hw_params_formats(dump_text: str) -> list[str]:
    """aplay --dump-hw-params 출력에서 Camilla 포맷명 목록 (품질 높은 순)."""
    found: set[str] = set()
    for line in (dump_text or "").splitlines():
        if "FORMAT:" not in line.upper() and not line.strip().startswith("FORMAT"):
            # "Available formats:" 아래 불릿도 허용
            token = line.strip().lstrip("- ").strip()
            if token in {a for a, _ in _ALSA_TO_CAMILLA_FORMAT}:
                found.add(token)
            continue
        upper = line.upper()
        if "FORMAT" not in upper:
            continue
        for alsa_name, _camilla in _ALSA_TO_CAMILLA_FORMAT:
            if alsa_name in line or alsa_name.replace("_", "") in line:
                found.add(alsa_name)
    ordered: list[str] = []
    seen_camilla: set[str] = set()
    for alsa_name, camilla in _ALSA_TO_CAMILLA_FORMAT:
        if alsa_name in found and camilla not in seen_camilla:
            ordered.append(camilla)
            seen_camilla.add(camilla)
    return ordered


_dump_cache: tuple[str, float, str] | None = None
_DUMP_CACHE_SEC = 8.0


def dump_playback_hw_params(device: str) -> str:
    """hw: 재생 장치의 실제 포맷 목록. plughw는 변환으로 거짓 통과하므로 hw만."""
    import time

    global _dump_cache
    if not device or device == "default":
        return ""
    hw = plughw_to_hw(device)
    now = time.monotonic()
    if _dump_cache and _dump_cache[0] == hw and (now - _dump_cache[1]) < _DUMP_CACHE_SEC:
        return _dump_cache[2]
    text = ""
    # 요청 포맷이 달라도 FORMAT 줄에 지원 목록이 나온다. 한 번만 호출.
    try:
        proc = subprocess.run(
            [
                "aplay",
                "-D",
                hw,
                "--dump-hw-params",
                "-f",
                "S32_LE",
                "-r",
                "48000",
                "-c",
                "2",
                "/dev/zero",
            ],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        text = (proc.stdout or "") + (proc.stderr or "")
    except Exception:
        text = ""
    _dump_cache = (hw, now, text)
    return text


def list_playback_camilla_formats(device: str) -> list[str]:
    """이 DAC가 hw:로 받는 Camilla 포맷. 비어 있으면 모름(추측 금지)."""
    return parse_hw_params_formats(dump_playback_hw_params(device))


def playback_format_candidates(device: str) -> list[str]:
    """실패 시 재시도 순서. dump에 있는 것만. dump 비면 S16 없이 24/32만."""
    listed = list_playback_camilla_formats(device)
    if listed:
        return listed
    return ["S32LE", "S24LE3", "S24LE"]


def pick_playback_camilla_format(device: str, *, preferred: str | None = None) -> str:
    """DAC hw_params에 있는 것만 고른다. USB DB/16bit 바닥 금지.

    dump가 비는 경우(Camilla가 장치를 점유 중 EINVAL 등)에는 직전에 성공한
    preferred(probed_alsa_format)를 쓰고, 그것도 없을 때만 S32LE.
    """
    explicit = (os.getenv("WHICK_CAMILLA_ALSA_FORMAT") or "").strip()
    if explicit:
        return explicit
    listed = list_playback_camilla_formats(device)
    pref = (preferred or "").strip() or None
    if pref and listed and pref in listed:
        return pref
    if listed:
        return listed[0]
    if pref:
        return pref
    return "S32LE"


def probe_playback_device(device: str, *, sample_rate: int = 48000, bits: int = 24) -> bool:
    """카드가 있는지 dump로 확인. 요청 포맷 EINVAL은 '장치 없음'이 아님.

    dump_playback_hw_params와 동일하게 hw:만 본다(plughw 거짓 통과·캐시 키 불일치 방지).
    """
    if not device or device == "default":
        return False
    hw = plughw_to_hw(device) or device
    text = dump_playback_hw_params(hw)
    if text and ("RATE" in text or "FORMAT:" in text.upper()):
        return True
    fmts = {
        16: ("S16_LE",),
        24: ("S24_LE", "S24_3LE"),
        32: ("S32_LE",),
    }.get(bits, ("S24_LE", "S24_3LE"))
    for fmt in fmts:
        try:
            proc = subprocess.run(
                [
                    "aplay",
                    "-D",
                    hw,
                    "--dump-hw-params",
                    "-f",
                    fmt,
                    "-r",
                    str(sample_rate),
                    "-c",
                    "2",
                    "/dev/zero",
                ],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            combined = (proc.stdout or "") + (proc.stderr or "")
            if "RATE" in combined or "FORMAT:" in combined.upper():
                return True
            if proc.returncode == 0:
                return True
        except Exception:
            continue
    return False


def resolve_direct_alsa_device() -> str:
    """Bit-perfect Direct — hw 우선, 실패 시 plughw."""
    explicit = (os.getenv("WHICK_ALSA_DEVICE") or "").strip()
    if explicit and explicit.lower() not in ("auto", ""):
        return explicit

    mode = os.getenv("WHICK_ALSA_DEVICE_MODE", "hw").strip().lower()
    if mode == "plug":
        dev = _shell_resolve(mode="plug")
        return dev or "default"

    dev = _shell_resolve(mode="hw")
    if dev:
        for bits in (32, 24, 16):
            if probe_playback_device(dev, bits=bits):
                return dev
    plug = _shell_resolve(mode="plug")
    if plug:
        return plug
    return dev or "default"


def resolve_dsp_alsa_device() -> str:
    """DSP pipe — plughw 허용(호환), hw 가능 시 hw."""
    explicit = (os.getenv("WHICK_DSP_ALSA_DEVICE") or os.getenv("WHICK_CAMILLA_ALSA_DEVICE") or "").strip()
    if explicit and explicit.lower() not in ("auto", ""):
        return explicit
    hw = _shell_resolve(mode="hw")
    if hw and probe_playback_device(hw):
        return hw
    plug = _shell_resolve(mode="plug")
    return plug or hw or "default"


def card_name_from_device(device: str) -> str | None:
    m = re.search(r"CARD=([^,\s]+)", device)
    if m:
        return m.group(1)
    m2 = re.match(r"hw:(\d+)", device)
    if m2:
        id_path = asound_root() / f"card{m2.group(1)}" / "id"
        if id_path.is_file():
            return id_path.read_text(encoding="utf-8", errors="replace").strip()
    return None


def has_hardware_mixer(card: str) -> bool:
    try:
        proc = subprocess.run(
            ["amixer", "-D", f"hw:CARD={card}", "scontrols"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode == 0 and bool(re.search(r"(PCM|Master|Digital)", out, re.I))
    except Exception:
        return False


def resolve_direct_mixer_type() -> str:
    """Bit-perfect Direct — none(PCM 무가공) · hardware(DAC 볼륨) · software."""
    pref = os.getenv("WHICK_BITPERFECT_MIXER", "auto").strip().lower()
    if pref in ("none", "null"):
        return "none"
    if pref in ("software", "hardware"):
        return pref
    card = card_name_from_device(resolve_direct_alsa_device())
    if card and has_hardware_mixer(card):
        return "hardware"
    return "none"


def set_hardware_volume(percent: int, *, device: str | None = None) -> bool:
    """DAC/앰프 HW 믹서 볼륨 — bit-perfect 경로용."""
    dev = device or resolve_direct_alsa_device()
    card = card_name_from_device(dev)
    if not card:
        return False
    pct = max(0, min(100, int(percent)))
    for ctrl in ("PCM", "Digital", "Master", "Speaker"):
        try:
            proc = subprocess.run(
                ["amixer", "-D", f"hw:CARD={card}", "sset", ctrl, f"{pct}%"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            if proc.returncode == 0 and "off" not in (proc.stderr or "").lower():
                return True
        except Exception:
            continue
    return False


def ui_volume_to_mixer_percent(ui: int) -> int:
    """리모컨 UI 0–100 → 실제 믹서 %.

    MPD/software·amixer % 는 진폭 선형이라 체감은 저음량에서 급격히 줄어든다.
    √곡선(기본 gamma=0.5)으로 슬라이더 위치에 맞춰 체감을 균등하게 맞춘다.
    WHICK_VOLUME_UI_GAMMA=1 → 선형(구 동작), 0.2~1.0.
    """
    u = max(0, min(100, int(ui)))
    if u <= 0:
        return 0
    if u >= 100:
        return 100
    try:
        gamma = float(os.getenv("WHICK_VOLUME_UI_GAMMA", "0.5") or "0.5")
    except ValueError:
        gamma = 0.5
    gamma = max(0.2, min(1.0, gamma))
    if abs(gamma - 1.0) < 1e-6:
        return u
    return max(0, min(100, int(round(100.0 * ((u / 100.0) ** gamma)))))


def _mpc_set_volume(applied: int) -> bool:
    try:
        proc = subprocess.run(
            ["mpc", "--quiet", "volume", str(max(0, min(100, int(applied))))],
            timeout=3,
            capture_output=True,
            check=False,
        )
        return proc.returncode == 0
    except Exception:
        return False


def set_playback_volume(percent: int, replay_gain_db: float = 0.0) -> dict[str, Any]:
    """볼륨 — UI% 유지, 믹서에는 균등 곡선 적용.

    Direct mixer=none(HW 믹서 없는 DAC) + DSP(Whick DSP software) 일 때
    amixer 실패 후 mpc fallback — 미호출이면 리모컨 볼륨이 안 먹는다.
    replay_gain_db: 라이브러리 정규화 게인(재생 트랙별). 믹서 %에 선형 배수.
    """
    pct = max(0, min(100, int(percent)))
    applied = ui_volume_to_mixer_percent(pct)
    try:
        rg = float(replay_gain_db or 0.0)
    except (TypeError, ValueError):
        rg = 0.0
    if abs(rg) >= 0.01:
        applied = max(0, min(100, int(round(applied * (10.0 ** (rg / 20.0))))))
    mixer = resolve_direct_mixer_type()

    if mixer == "none":
        ok = set_hardware_volume(applied)
        if ok:
            return {
                "ok": True,
                "path": "alsa_hw",
                "percent": pct,
                "applied": applied,
                "replay_gain_db": rg,
            }
        if _mpc_set_volume(applied):
            return {
                "ok": True,
                "path": "mpc_dsp_fallback",
                "percent": pct,
                "applied": applied,
                "replay_gain_db": rg,
            }
        return {
            "ok": False,
            "path": "none_fixed",
            "error": "mpc volume failed",
            "percent": pct,
            "applied": applied,
            "replay_gain_db": rg,
        }

    if _mpc_set_volume(applied):
        return {
            "ok": True,
            "path": f"mpc_{mixer}",
            "percent": pct,
            "applied": applied,
            "replay_gain_db": rg,
        }
    return {
        "ok": False,
        "path": "mpc",
        "error": "mpc volume failed",
        "percent": pct,
        "applied": applied,
        "replay_gain_db": rg,
    }
