"""DSD 재생 — MPD DoP · ffmpeg 폴백."""
from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path

from api.dac_capability import load_dac_capability, supports_dop

DSD_EXTS = {".dsf", ".dff"}
# ffprobe native DSD sample rates (Hz)
DSD64_RATE = 2_822_400
DSD128_RATE = 5_644_800
DSD256_RATE = 11_289_600
DSD512_RATE = 22_579_200
DSD_PLAYER_PID = Path(os.getenv("WHICK_DSD_PLAYER_PID", "/var/lib/whick/run/dsd-player.pid"))
DSD_PLAYER_LOG = Path(os.getenv("WHICK_DSD_PLAYER_LOG", "/var/lib/whick/run/dsd-player.log"))


def is_dsd_file(path: str | Path) -> bool:
    return Path(path).suffix.lower() in DSD_EXTS


def dsd_format_from_rate(raw_rate: int) -> str:
    if raw_rate >= DSD512_RATE:
        return "DSD512"
    if raw_rate >= DSD256_RATE:
        return "DSD256"
    if raw_rate >= DSD128_RATE:
        return "DSD128"
    if raw_rate >= DSD64_RATE:
        return "DSD64"
    return "DSD"


def dop_wrapper_rate(dsd_label: str) -> int:
    """DoP PCM 래퍼 샘플레이트 (DSD64 → 176.4kHz)."""
    return {
        "DSD64": 176400,
        "DSD128": 352800,
        "DSD256": 705600,
        "DSD512": 1411200,
    }.get(dsd_label, 176400)


def stop_external_dsd_player() -> None:
    if not DSD_PLAYER_PID.is_file():
        return
    try:
        pid = int(DSD_PLAYER_PID.read_text(encoding="utf-8").strip())
        os.kill(pid, signal.SIGTERM)
    except (OSError, ValueError, ProcessLookupError):
        pass
    try:
        DSD_PLAYER_PID.unlink(missing_ok=True)
    except OSError:
        pass


def _resolve_alsa() -> str:
    from api.alsa_device import resolve_direct_alsa_device

    return resolve_direct_alsa_device()


def play_dsd_external(file_path: str, *, raw_sample_rate: int = 0) -> bool:
    """MPD DSD 디코드 실패 시 ffmpeg → ALSA (PCM 고해상도 폴백)."""
    path = Path(file_path)
    if not path.is_file():
        return False
    sr = int(raw_sample_rate or 0)
    if sr <= 0:
        try:
            import json as _json

            raw = subprocess.check_output(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    "a:0",
                    "-show_entries",
                    "stream=sample_rate",
                    "-of",
                    "json",
                    str(path),
                ],
                stderr=subprocess.DEVNULL,
                timeout=15,
            )
            sr = int((_json.loads(raw).get("streams") or [{}])[0].get("sample_rate") or DSD64_RATE)
        except Exception:
            sr = DSD64_RATE
    pcm_rate = dop_wrapper_rate(dsd_format_from_rate(sr))
    alsa = _resolve_alsa()
    DSD_PLAYER_LOG.parent.mkdir(parents=True, exist_ok=True)
    stop_external_dsd_player()
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(path),
        "-af",
        f"aresample={pcm_rate}:resampler=soxr",
        "-f",
        "s32le",
        "-ar",
        str(pcm_rate),
        "-ac",
        "2",
        "pipe:1",
    ]
    alsa_cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "s32le",
        "-ar",
        str(pcm_rate),
        "-ac",
        "2",
        "-i",
        "pipe:0",
        "-f",
        "alsa",
        alsa,
    ]
    try:
        ff = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=open(DSD_PLAYER_LOG, "a", encoding="utf-8"))
        assert ff.stdout is not None
        alsa_proc = subprocess.Popen(
            alsa_cmd,
            stdin=ff.stdout,
            stdout=subprocess.DEVNULL,
            stderr=open(DSD_PLAYER_LOG, "a", encoding="utf-8"),
            start_new_session=True,
        )
        ff.stdout.close()
        DSD_PLAYER_PID.write_text(str(alsa_proc.pid), encoding="utf-8")
        return True
    except Exception as exc:
        with open(DSD_PLAYER_LOG, "a", encoding="utf-8") as fh:
            fh.write(f"[dsd] external play failed: {exc}\n")
        return False


def dsd_playback_plan(file_path: str, *, raw_sample_rate: int = 0) -> dict:
    """재생 전략 — MPD+DoP 우선, DSP 불가."""
    cap = load_dac_capability()
    label = dsd_format_from_rate(raw_sample_rate) if raw_sample_rate else "DSD"
    use_dop = supports_dop() and bool(cap.get("dop", True))
    return {
        "is_dsd": True,
        "dsd_format": label,
        "strategy": "mpd_dop" if use_dop else "mpd_pcm_fallback",
        "dop": use_dop,
        "dop_wrapper_rate": dop_wrapper_rate(label) if use_dop else None,
        "dsp_allowed": False,
        "external_fallback": "ffmpeg_pcm",
    }
