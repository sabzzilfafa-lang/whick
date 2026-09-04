"""CamillaDSP 상주 데몬 — Loopback capture → DAC, websocket 제어."""
from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from api.camilla_loopback import loopback_card_name, resolve_transport, camilla_fifo_path
from api.camilla_ws import ping as ws_ping
from api.camilla_ws import patch_config, reload_from_file, set_config
from api.camilla_yaml import ws_camilla_config, ws_camilla_filters_config

from api.dac_preprocess import dac_os_rate
from api.dsp_store import camilla_profile_path, write_camilla_file

PID_FILE = Path(os.getenv("WHICK_CAMILLA_PID", "/var/lib/whick/run/camilladsp.pid"))
BRIDGE_PID_FILE = Path(os.getenv("WHICK_CAMILLA_BRIDGE_PID", "/var/lib/whick/run/camilla-fifo-bridge.pid"))
LOG_FILE = Path(os.getenv("WHICK_CAMILLA_DAEMON_LOG", "/var/lib/whick/run/camilladsp-daemon.log"))
DEVICE_STATE = Path(os.getenv("WHICK_CAMILLA_DEVICE_STATE", "/var/lib/whick/run/camilla-playback-device.txt"))
WS_PORT = os.getenv("WHICK_CAMILLA_WS_PORT", "1234")
WS_ADDR = os.getenv("WHICK_CAMILLA_WS_HOST", "127.0.0.1")
BRIDGE_SCRIPT = Path("/app/docker/camilla-fifo-bridge.py")

_apply_lock = threading.Lock()
_suspended_for_direct = False


def playback_device_key() -> str:
    from api.alsa_device import plughw_to_hw, resolve_direct_alsa_device

    dev = resolve_direct_alsa_device()
    return plughw_to_hw(dev) or dev or "default"


def _read_stored_playback_device() -> str:
    try:
        return DEVICE_STATE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _write_stored_playback_device(dev: str) -> None:
    try:
        DEVICE_STATE.parent.mkdir(parents=True, exist_ok=True)
        DEVICE_STATE.write_text(dev, encoding="utf-8")
    except OSError:
        pass


def playback_device_needs_rebind() -> bool:
    current = playback_device_key()
    stored = _read_stored_playback_device()
    # stored 비어 있으면 장치 미확정 — 재바인딩 필요(핫플러그·기동 직후)
    if not stored:
        return True
    return stored != current


def forget_stored_playback_device() -> None:
    """DAC 핫플러그 등 — 저장된 장치 키를 지워 강제 재바인딩."""
    try:
        if DEVICE_STATE.is_file():
            DEVICE_STATE.unlink()
    except OSError:
        pass


def _pause_mpd_feed() -> None:
    try:
        subprocess.run(["mpc", "pause"], timeout=3, capture_output=True, check=False)
    except Exception:
        pass


def _pid_is_zombie(pid: int) -> bool:
    """EINVAL로 죽은 camilladsp가 defunct로 남으면 pgrep이 '실행 중'으로 오판한다."""
    try:
        # /proc/<pid>/stat: name may contain spaces in parentheses — state is after last ')'
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
        state = raw.split(")", 1)[1].lstrip().split(" ", 1)[0]
        return state == "Z"
    except (OSError, IndexError, ValueError):
        return False


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return not _pid_is_zombie(pid)


def read_pid() -> int | None:
    if not PID_FILE.is_file():
        return None
    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    if _pid_alive(pid):
        return pid
    try:
        PID_FILE.unlink(missing_ok=True)
    except OSError:
        pass
    return None


def _live_camilladsp_pids() -> list[int]:
    try:
        proc = subprocess.run(
            ["pgrep", "-x", "camilladsp"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except Exception:
        return []
    if proc.returncode != 0 or not proc.stdout.strip():
        return []
    out: list[int] = []
    for tok in proc.stdout.split():
        try:
            pid = int(tok)
        except ValueError:
            continue
        if _pid_alive(pid):
            out.append(pid)
    return out


def is_running() -> bool:
    if read_pid() is not None:
        return True
    return bool(_live_camilladsp_pids())


def stop_daemon() -> dict[str, Any]:
    pid = read_pid()
    killed: list[int] = []
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
            killed.append(pid)
        except OSError:
            pass
    if BRIDGE_PID_FILE.is_file():
        try:
            bpid = int(BRIDGE_PID_FILE.read_text(encoding="utf-8").strip())
            os.kill(bpid, signal.SIGTERM)
            killed.append(bpid)
        except (OSError, ValueError):
            pass
        try:
            BRIDGE_PID_FILE.unlink(missing_ok=True)
        except OSError:
            pass
    try:
        subprocess.run(["pkill", "-f", "camilla-fifo-bridge.py"], timeout=5, check=False, capture_output=True)
    except Exception:
        pass
    try:
        subprocess.run(["pkill", "-x", "camilladsp"], timeout=5, check=False, capture_output=True)
    except Exception:
        pass
    for _ in range(15):
        if not is_running():
            break
        time.sleep(0.05)
    if is_running():
        try:
            subprocess.run(["pkill", "-9", "-x", "camilladsp"], timeout=5, check=False, capture_output=True)
        except Exception:
            pass
    try:
        PID_FILE.unlink(missing_ok=True)
    except OSError:
        pass
    return {"ok": not is_running(), "killed": killed}


def start_daemon(*, profile: dict[str, Any] | None = None) -> dict[str, Any]:
    global _suspended_for_direct
    if not (os.getenv("WHICK_CAMILLA_ENABLED", "1") == "1"):
        return {"ok": False, "error": "camilla disabled"}

    transport, transport_info = resolve_transport()
    if transport == "aloop" and not loopback_card_name():
        return {"ok": False, "error": "loopback unavailable", "transport": transport_info}
    if transport == "fifo":
        fifo_ok = True
        nested = transport_info.get("fifo") if isinstance(transport_info, dict) else None
        if isinstance(nested, dict):
            fifo_ok = bool(nested.get("ok"))
        elif isinstance(transport_info, dict) and transport_info.get("ok") is False:
            fifo_ok = False
        if not fifo_ok:
            return {"ok": False, "error": "fifo failed", "transport": transport_info}

    if profile is not None:
        write_camilla_file(profile)
    path = camilla_profile_path()
    if not path.is_file():
        return {"ok": False, "error": f"missing profile: {path}"}

    if is_running():
        _suspended_for_direct = False
        return {
            "ok": True,
            "already": True,
            "pid": read_pid(),
            "transport": transport,
            "transport_info": transport_info,
        }

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)

    camilla_cmd = [
        "camilladsp",
        "-a",
        WS_ADDR,
        "-p",
        str(WS_PORT),
        "-o",
        str(LOG_FILE),
        "-l",
        "info",
        str(path),
    ]

    try:
        if transport == "fifo":
            if not BRIDGE_SCRIPT.is_file():
                return {"ok": False, "error": f"missing bridge: {BRIDGE_SCRIPT}"}
            bridge = subprocess.Popen(
                ["python3", str(BRIDGE_SCRIPT)],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            BRIDGE_PID_FILE.write_text(str(bridge.pid), encoding="utf-8")
            proc = subprocess.Popen(
                camilla_cmd,
                stdin=bridge.stdout,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            if bridge.stdout:
                bridge.stdout.close()
        else:
            proc = subprocess.Popen(
                camilla_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
    except Exception as exc:
        return {"ok": False, "error": str(exc), "transport": transport, "transport_info": transport_info}

    PID_FILE.write_text(str(proc.pid), encoding="utf-8")
    for _ in range(20):
        if proc.poll() is not None:
            return {
                "ok": False,
                "error": f"camilladsp exited early code={proc.returncode}",
                "transport": transport,
                "transport_info": transport_info,
                "log": _tail_log(),
            }
        poked = ws_ping(timeout=0.3)
        if poked.get("ok"):
            _write_stored_playback_device(playback_device_key())
            _suspended_for_direct = False
            return {
                "ok": True,
                "pid": proc.pid,
                "transport": transport,
                "transport_info": transport_info,
                "ws": poked,
                "fifo": str(camilla_fifo_path()) if transport == "fifo" else None,
            }
        time.sleep(0.1)
    ok = is_running()
    if ok:
        _write_stored_playback_device(playback_device_key())
        _suspended_for_direct = False
    return {
        "ok": ok,
        "pid": proc.pid,
        "transport": transport,
        "transport_info": transport_info,
        "warn": "ws not ready yet",
        "log": _tail_log(),
    }


def restart_daemon(*, profile: dict[str, Any] | None = None, pause_feeders: bool = True) -> dict[str, Any]:
    if pause_feeders:
        _pause_mpd_feed()
    stop = stop_daemon()
    start = start_daemon(profile=profile)
    return {"ok": bool(start.get("ok")), "stop": stop, "start": start}


def suspend_for_direct_playback() -> dict[str, Any]:
    """DSD DoP / Direct — DAC 핸들 해제."""
    global _suspended_for_direct
    if not is_running():
        _suspended_for_direct = True
        return {"ok": True, "skipped": "not running"}
    _pause_mpd_feed()
    stopped = stop_daemon()
    _suspended_for_direct = True
    return {"ok": bool(stopped.get("ok")), "stopped": stopped}


def resume_for_dsp_playback(profile: dict[str, Any] | None = None) -> dict[str, Any]:
    """PCM resident 경로 — 필요 시 Camilla 재기동."""
    global _suspended_for_direct
    if playback_device_needs_rebind() or _suspended_for_direct or not is_running():
        started = restart_daemon(profile=profile, pause_feeders=False)
        _suspended_for_direct = False
        return {"ok": bool(started.get("ok")), "method": "restart", "detail": started}
    _suspended_for_direct = False
    return {"ok": True, "method": "already_running", "pid": read_pid()}


def sync_daemon_for_playback_mode(mode: str, profile: dict[str, Any] | None = None) -> dict[str, Any]:
    if mode in ("bitperfect", "dsd_dop"):
        return suspend_for_direct_playback()
    if mode == "dsp":
        return resume_for_dsp_playback(profile)
    return {"ok": True, "skipped": mode}


def _tail_log(n: int = 12) -> str:
    if not LOG_FILE.is_file():
        return ""
    try:
        lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-n:])
    except OSError:
        return ""


def needs_structural_reload(old: dict[str, Any] | None, new: dict[str, Any] | None) -> bool:
    """devices/rate/FIR/DAC 장치 변경 → 데몬 재시작. 필터만이면 WS hot apply.

    previous 없음(프로세스 재시작 직후): 데몬이 이미 돌면 hot apply로 맞추고,
    장치가 바뀌었으면(playback_device_needs_rebind)만 구조 재시작.
    빈 dict({})와 None을 구분 — None은 '이전 프로파일 모름', {}는 '빈 프로파일'.
    """
    if old is None:
        return bool(playback_device_needs_rebind())
    old = old or {}
    new = new or {}
    # 전처리 ON/OFF는 필터만. devices(rate·포맷)가 같을 때는 데몬 재시작 금지.
    try:
        from api.camilla_yaml import resolve_camilla_base_rate

        if resolve_camilla_base_rate(old) != resolve_camilla_base_rate(new):
            return True
    except Exception:
        try:
            if dac_os_rate(profile=old) != dac_os_rate(profile=new):
                return True
        except Exception:
            pass
    try:
        from api.playback_config import dsp_pipe_rate_hz

        if dsp_pipe_rate_hz(old) != dsp_pipe_rate_hz(new):
            return True
    except Exception:
        pass
    if playback_device_needs_rebind():
        return True
    return False


def apply_profile(
    profile: dict[str, Any],
    *,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """yaml 기록 후 WS 적용. 구조 변경·실패 시 데몬 재시작."""
    with _apply_lock:
        path = write_camilla_file(profile)
        ws_full = ws_camilla_config(profile)
        ws_filters = ws_camilla_filters_config(profile)

        if not is_running():
            started = start_daemon(profile=profile)
            return {
                "ok": bool(started.get("ok")),
                "path": path,
                "method": "start",
                "start": started,
                "card": loopback_card_name(),
            }

        if needs_structural_reload(previous, profile):
            restarted = restart_daemon(profile=profile, pause_feeders=True)
            return {
                "ok": bool(restarted.get("ok")),
                "path": path,
                "method": "restart_structural",
                "restart": restarted,
            }

        # previous 없음(API 재시작 직후): patch만 하면 rate/devices 누락 가능 → full SetConfig
        allow_patch = previous is not None
        ws_patch: dict[str, Any] = {"ok": False, "skipped": "no_previous"}
        if allow_patch:
            # Camilla ≥3: PatchConfig(JSON 부분객체). 2.0.3은 미지원 → 실패 후 full로.
            ws_patch = patch_config(ws_filters)
            if ws_patch.get("ok"):
                _write_stored_playback_device(playback_device_key())
                return {"ok": True, "path": path, "method": "patch_config", "ws": ws_patch}

        # 동일 devices 포함 full SetConfig — 필터만 바뀌면 Camilla가 재오픈 없이 적용 시도.
        ws_full_res = set_config(ws_full)
        if ws_full_res.get("ok"):
            _write_stored_playback_device(playback_device_key())
            return {
                "ok": True,
                "path": path,
                "method": "set_config_full",
                "ws_patch_fail": ws_patch,
                "ws": ws_full_res,
            }

        rel = reload_from_file()
        if rel.get("ok"):
            _write_stored_playback_device(playback_device_key())
            return {
                "ok": True,
                "path": path,
                "method": "reload",
                "ws_patch_fail": ws_patch,
                "ws_full_fail": ws_full_res,
                "reload": rel,
            }

        restarted = restart_daemon(profile=profile, pause_feeders=True)
        return {
            "ok": bool(restarted.get("ok")),
            "path": path,
            "method": "restart_fallback",
            "ws_patch_fail": ws_patch,
            "ws_full_fail": ws_full_res,
            "reload_fail": rel,
            "restart": restarted,
        }


def daemon_status() -> dict[str, Any]:
    pid = read_pid()
    ws = ws_ping(timeout=0.5) if (pid or is_running()) else {"ok": False, "error": "not running"}
    return {
        "running": is_running(),
        "suspended_for_direct": _suspended_for_direct,
        "pid": pid,
        "ws": ws,
        "ws_url": f"ws://{WS_ADDR}:{WS_PORT}",
        "profile": str(camilla_profile_path()) if camilla_profile_path().is_file() else None,
        "playback_device": playback_device_key(),
        "playback_device_stored": _read_stored_playback_device(),
        "loopback_card": loopback_card_name(),
        "log_tail": _tail_log(8),
    }
