"""MPD → CamillaDSP 상주 재생 경로 — 프로필·데몬 상태."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from api.dsp_store import camilla_profile_path, default_dsp_profile, write_camilla_file
from api.playback_router import (
    camilla_enabled,
    profile_needs_dsp,
    read_alsa_hw_params,
    resolve_playback_mode,
    sync_playback_route,
)

CAMILLA_LOG = Path(os.getenv("WHICK_CAMILLA_DAEMON_LOG", "/var/lib/whick/run/camilladsp-daemon.log"))
LEGACY_LOG = Path("/var/lib/whick/run/whick-dsp-pipe.log")


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


def ensure_default_profile() -> str:
    path = camilla_profile_path()
    if not path.is_file():
        write_camilla_file(default_dsp_profile())
    return str(path)


def pipeline_status(profile: dict[str, Any] | None = None) -> dict[str, Any]:
    path = camilla_profile_path()
    log_tail = ""
    for log_path in (CAMILLA_LOG, LEGACY_LOG):
        if log_path.is_file():
            try:
                lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
                log_tail = "\n".join(lines[-8:])
                break
            except OSError:
                log_tail = ""
    mode = resolve_playback_mode(profile)
    from api.alsa_device import resolve_direct_alsa_device, resolve_direct_mixer_type
    from api.camilla_daemon import daemon_status
    from api.camilla_loopback import (
        camilla_fifo_path,
        loopback_capture_device,
        loopback_feed_device,
        loopback_card_name,
        transport_mode,
    )
    from api.playback_config import playback_config_summary

    daemon = daemon_status()
    mode_transport = transport_mode()
    return {
        "ok": True,
        "camilla_enabled": camilla_enabled(),
        "playback_mode": mode,
        "dsp_needed": profile_needs_dsp(profile),
        "mpd_output_mode": mode,
        "architecture": "camilla_resident",
        "transport": mode_transport,
        "camilladsp_installed": bool(shutil.which("camilladsp")),
        "ffmpeg_installed": bool(shutil.which("ffmpeg")),
        "librespot_installed": bool(shutil.which(os.getenv("WHICK_LIBRESPOT_BIN", "librespot"))),
        "librespot_running": _librespot_running(),
        "librespot_audio_path": (
            "subprocess → fifo → camilla daemon"
            if mode_transport == "fifo"
            else "alsa → Loopback → camilla daemon"
        ),
        "profile_path": str(path) if path.is_file() else None,
        "alsa_device": resolve_direct_alsa_device(),
        "direct_mixer_type": resolve_direct_mixer_type(),
        "loopback_card": loopback_card_name(),
        "loopback_feed": loopback_feed_device() if mode_transport == "aloop" else None,
        "loopback_capture": loopback_capture_device() if mode_transport == "aloop" else None,
        "fifo_path": str(camilla_fifo_path()) if mode_transport == "fifo" else None,
        "daemon": daemon,
        **playback_config_summary(profile),
        "hw_params": read_alsa_hw_params(),
        "log_tail": log_tail or daemon.get("log_tail") or "",
    }


def reload_profile(
    profile: dict[str, Any] | None = None,
    *,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Camilla yaml 갱신 + 상주 데몬 WS 적용 + MPD 출력 경로 동기화."""
    from api.camilla_daemon import apply_profile, start_daemon

    if profile is None:
        path = ensure_default_profile()
        started = start_daemon(profile=default_dsp_profile())
        route = sync_playback_route(default_dsp_profile())
        return {
            "ok": bool(started.get("ok")),
            "camillaPath": path,
            "message": "default profile ready",
            "route": route,
            "apply": started,
        }

    apply = apply_profile(profile, previous=previous)
    ok, detail = _check_camilla_file(apply.get("path") or camilla_profile_path())
    # EQ/필터만 변경 시 MPD 출력 전환 불필요 — sync_playback_route는 Camilla suspend/restart 유발 가능
    method = str(apply.get("method") or "")
    if method in ("patch_config", "set_config", "set_config_full", "reload"):
        route = {"ok": True, "skipped": "mpd_outputs_unchanged", "apply_method": method}
    else:
        route = sync_playback_route(profile)
    if ok and apply.get("ok"):
        return {
            "ok": True,
            "camillaPath": apply.get("path"),
            "message": f"profile applied via {apply.get('method')}",
            "route": route,
            "apply": apply,
        }

    print(f"[DSP] apply issue check={detail} apply={apply}")
    fallback = {
        "enabled": True,
        "eqEnabled": False,
        "version": 2,
        "peaking": [],
        "userPeaking": [],
        "balanceDb": {"left": 0, "right": 0},
        "swapChannels": False,
        "dacPreprocessEnabled": False,
        "roomPeaking": [],
        "source": "passthrough-fallback",
    }
    apply2 = apply_profile(fallback, previous=profile)
    ok2, detail2 = _check_camilla_file(apply2.get("path") or camilla_profile_path())
    route2 = sync_playback_route(fallback)
    return {
        "ok": bool(ok2 and apply2.get("ok")),
        "camillaPath": apply2.get("path"),
        "message": "invalid DSP profile — reverted to passthrough"
        if ok2
        else "invalid DSP profile — passthrough fallback failed",
        "error": detail if ok2 else f"{detail}; fallback: {detail2}",
        "route": route2,
        "apply": apply2,
        "previous_apply": apply,
    }


def _check_camilla_file(path: str | Path) -> tuple[bool, str]:
    if not shutil.which("camilladsp"):
        return True, "camilladsp not installed — skip check"
    try:
        proc = subprocess.run(
            ["camilladsp", "--check", str(path)],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        combined = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode == 0 and "Config is not valid" not in combined:
            return True, combined.strip() or "check ok"
        return False, combined.strip()
    except Exception as exc:
        return False, str(exc)


def verify_camilla_dry_run() -> tuple[bool, str]:
    if not shutil.which("camilladsp"):
        return False, "camilladsp not installed"
    path = ensure_default_profile()
    return _check_camilla_file(path)
