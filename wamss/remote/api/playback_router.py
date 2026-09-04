"""재생 경로 라우터 — Bit-Perfect(DSP off) vs DSP 처리 vs legacy PoC."""
from __future__ import annotations

import json
import os
import re
import signal
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Literal

from api.asound import asound_root
from api.dac_preprocess import dac_preprocess_enabled
from api.dsd_playback import dsd_playback_plan, dop_wrapper_rate, dsd_format_from_rate

PlaybackMode = Literal["bitperfect", "dsp", "legacy", "null", "dsd_dop"]

PLAYBACK_JSON = Path(os.getenv("WHICK_PLAYBACK_JSON", "/var/lib/whick/run/current-playback.json"))
MPD_CONF = os.getenv("WHICK_MPD_CONF", "/etc/mpd.conf")
MPD_HOST = os.getenv("WHICK_MPD_HOST", "127.0.0.1")
MPD_PORT = int(os.getenv("WHICK_MPD_PORT", "6600"))
DSD_EXTS = {".dsf", ".dff"}

_MPD_RESTART_LOCK = threading.Lock()


def mpd_is_ready(*, timeout: float = 2.0) -> bool:
    """mpc status가 성공하면 MPD 제어 소켓이 살아 있는 것."""
    try:
        out = subprocess.run(
            ["mpc", "status"],
            timeout=max(0.5, float(timeout)),
            capture_output=True,
            text=True,
            check=False,
        )
        return out.returncode == 0 and bool((out.stdout or "").strip())
    except Exception:
        return False


def _mpd_port_in_use(host: str = MPD_HOST, port: int = MPD_PORT) -> bool:
    """연결 성공 = 리스너 존재(포트 사용 중)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.35)
    try:
        sock.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        try:
            sock.close()
        except OSError:
            pass


def _iter_mpd_pids() -> list[int]:
    pids: list[int] = []
    try:
        for ent in os.listdir("/proc"):
            if not ent.isdigit():
                continue
            pid = int(ent)
            try:
                raw = Path(f"/proc/{pid}/cmdline").read_bytes()
            except OSError:
                continue
            cmd = raw.replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()
            if not cmd:
                continue
            # "mpd --no-daemon" / "/usr/bin/mpd …"
            first = cmd.split(" ", 1)[0]
            base = Path(first).name
            if base == "mpd" or cmd.startswith("mpd ") or "/mpd " in f" {cmd}":
                pids.append(pid)
    except OSError:
        pass
    return pids


def _signal_mpd_pids(sig: int) -> None:
    for pid in _iter_mpd_pids():
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            pass
        except PermissionError as exc:
            print(f"[MPD] kill pid={pid} denied: {exc}")


def _wait_mpd_port_free(*, timeout_sec: float = 8.0) -> bool:
    deadline = time.monotonic() + max(0.5, float(timeout_sec))
    while time.monotonic() < deadline:
        if not _mpd_port_in_use():
            return True
        time.sleep(0.15)
    return not _mpd_port_in_use()


def _stop_mpd_hard() -> None:
    """pidfile 기반 mpd --kill → 잔존 프로세스 SIGTERM/SIGKILL → :6600 해제 대기."""
    subprocess.run(["mpd", "--kill"], timeout=5, capture_output=True, check=False)
    if _wait_mpd_port_free(timeout_sec=2.0):
        return
    _signal_mpd_pids(signal.SIGTERM)
    if _wait_mpd_port_free(timeout_sec=3.0):
        return
    _signal_mpd_pids(signal.SIGKILL)
    _wait_mpd_port_free(timeout_sec=3.0)

def camilla_enabled() -> bool:
    return os.getenv("WHICK_CAMILLA_ENABLED", "1") == "1"


def _room_active(profile: dict[str, Any]) -> bool:
    for band in profile.get("roomPeaking") or []:
        if abs(float(band.get("gainDb") or 0)) >= 0.05:
            return True
    return False


def _eq_active(profile: dict[str, Any]) -> bool:
    if profile.get("eqEnabled") is not True:
        return False
    for band in profile.get("userPeaking") or profile.get("peaking") or []:
        if abs(float(band.get("gainDb") or 0)) >= 0.05:
            return True
    balance = profile.get("balanceDb") or {}
    if float(balance.get("left") or 0) > 0.05 or float(balance.get("right") or 0) > 0.05:
        return True
    return False


def profile_needs_dsp(profile: dict[str, Any] | None) -> bool:
    if not profile or profile.get("enabled") is False:
        return False
    if dac_preprocess_enabled(profile):
        return True
    if bool(profile.get("swapChannels")):
        return True
    if _room_active(profile):
        return True
    if _eq_active(profile):
        return True
    return False


def resolve_playback_mode(profile: dict[str, Any] | None = None) -> PlaybackMode:
    meta = read_current_playback()
    if meta.get("is_dsd"):
        from api.dac_capability import supports_dop

        return "dsd_dop" if supports_dop() else "bitperfect"

    env = (os.getenv("WHICK_PLAYBACK_MODE") or "auto").strip().lower()
    if env == "legacy":
        return "legacy"
    if env == "bitperfect":
        # 강제 Direct — 디버그용. 상업 기본은 Camilla 상주(bypass)
        return "bitperfect"
    if env == "dsp":
        return "dsp"
    if not camilla_enabled():
        return "null"
    # PCM: 항상 Loopback→Camilla. DSP OFF는 yaml bypass (경로 전환 없음)
    return "dsp"


def write_current_playback(
    *,
    bit_depth: int | None = None,
    sample_rate: int | None = None,
    source_format: str = "",
    file_path: str = "",
    is_dsd: bool = False,
    dsd_rate: int | None = None,
) -> None:
    PLAYBACK_JSON.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "bit_depth": int(bit_depth or 16),
        "sample_rate": int(sample_rate or 44100),
        "source_format": source_format,
        "file_path": file_path,
        "is_dsd": bool(is_dsd),
        "dsd_rate": dsd_rate,
    }
    PLAYBACK_JSON.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def read_current_playback() -> dict[str, Any]:
    if not PLAYBACK_JSON.is_file():
        return {}
    try:
        return json.loads(PLAYBACK_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _alsa_device() -> str:
    from api.alsa_device import resolve_direct_alsa_device

    return resolve_direct_alsa_device()


def regenerate_mpd_conf(profile: dict[str, Any] | None = None) -> str:
    from api.alsa_device import resolve_direct_mixer_type
    from api.mpd_conf import render
    from api.playback_config import sync_dsp_pipe_env

    sync_dsp_pipe_env(profile)
    layout = os.getenv("WHICK_PLAYBACK_LAYOUT", "modern")
    if os.getenv("WHICK_PLAYBACK_MODE", "auto").strip().lower() == "legacy":
        layout = "legacy"
    content = render(
        camilla=camilla_enabled(),
        layout=layout,
        alsa_device=_alsa_device(),
        direct_mixer=resolve_direct_mixer_type(),
        profile=profile,
    )
    Path(MPD_CONF).write_text(content, encoding="utf-8")
    return layout


def _target_alsa_card_names() -> set[str]:
    """Whick Direct ALSA device에 해당하는 카드 id."""
    dev = _alsa_device()
    names: set[str] = set()
    m = re.search(r"CARD=([^,\s]+)", dev)
    if m:
        names.add(m.group(1))
    if dev.startswith("hw:") or dev.startswith("plughw:"):
        parts = dev.split(":")
        if len(parts) > 1 and parts[1].isdigit():
            idx = parts[1].split(",")[0]
            id_path = asound_root() / f"card{idx}" / "id"
            if id_path.is_file():
                names.add(id_path.read_text(encoding="utf-8", errors="replace").strip())
    return names


def restart_mpd_daemon() -> dict[str, Any]:
    """mpd.conf 변경 후 MPD 재기동 — audio_output·dop 반영.

    설치/터널 force-recreate 직후 ALSA·DAC가 아직 안 잡힌 채로
    `mpd --kill`→즉시 기동하면 :6600 Address already in use / hung MPD가 남는다.
    포트 해제 확인·잔존 프로세스 정리·mpc ready 검증까지 한다.
    """
    with _MPD_RESTART_LOCK:
        last_err = ""
        for attempt in range(1, 4):
            try:
                _stop_mpd_hard()
                if _mpd_port_in_use():
                    last_err = f"port {MPD_HOST}:{MPD_PORT} still in use after kill"
                    print(f"[MPD] restart attempt {attempt}/3: {last_err}")
                    time.sleep(0.5 * attempt)
                    continue

                proc = subprocess.Popen(
                    ["mpd", "--no-daemon"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
                # 기동 직후 바로 죽는지·포트가 열리는지 확인
                ready = False
                for _ in range(20):
                    time.sleep(0.25)
                    if proc.poll() is not None:
                        err = b""
                        try:
                            err = proc.stderr.read() if proc.stderr else b""
                        except Exception:
                            pass
                        last_err = (
                            f"MPD exited rc={proc.returncode}: "
                            f"{err.decode('utf-8', errors='replace').strip()[:240]}"
                        )
                        break
                    if _mpd_port_in_use() and mpd_is_ready(timeout=1.5):
                        ready = True
                        break
                if ready:
                    # 성공 시 PIPE 잔류로 데드락 나지 않게 stderr 닫기
                    try:
                        if proc.stderr:
                            proc.stderr.close()
                    except Exception:
                        pass
                    subprocess.run(["mpc", "update"], timeout=10, capture_output=True, check=False)
                    return {"ok": True, "pid": proc.pid, "attempts": attempt}
                if proc.poll() is None:
                    try:
                        proc.terminate()
                    except OSError:
                        pass
                    _stop_mpd_hard()
                if not last_err:
                    last_err = "MPD started but mpc status not ready"
                print(f"[MPD] restart attempt {attempt}/3 failed: {last_err}")
                time.sleep(0.4 * attempt)
            except Exception as exc:
                last_err = str(exc)
                print(f"[MPD] restart attempt {attempt}/3 exception: {exc}")
                time.sleep(0.4 * attempt)
        return {"ok": False, "error": last_err or "MPD restart failed"}


def reload_mpd_after_conf_change(profile: dict[str, Any] | None = None) -> dict[str, Any]:
    """설정 재생성 + MPD 재시작 + 출력 경로 동기화."""
    layout = regenerate_mpd_conf(profile)
    restarted = restart_mpd_daemon()
    route = sync_playback_route(profile)
    return {"layout": layout, "mpd": restarted, "route": route}


def ensure_mpd_after_boot(profile: dict[str, Any] | None = None) -> dict[str, Any]:
    """컨테이너 기동 직후 — conf가 같으면 불필요한 kill/restart를 피한다.

    entrypoint가 이미 mpd를 띄운 뒤 lifespan이 무조건 restart 하면
    DAC/ALSA 레이스와 :6600 EADDRINUSE의 주원인이 된다.
    """
    conf_path = Path(MPD_CONF)
    before = conf_path.read_text(encoding="utf-8") if conf_path.is_file() else ""
    layout = regenerate_mpd_conf(profile)
    after = conf_path.read_text(encoding="utf-8") if conf_path.is_file() else ""
    conf_changed = before != after
    ready = mpd_is_ready(timeout=2.0)
    if conf_changed or not ready:
        restarted = restart_mpd_daemon()
    else:
        restarted = {"ok": True, "skipped": "mpd_already_ready", "conf_changed": False}
    route = sync_playback_route(profile)
    return {
        "layout": layout,
        "mpd": restarted,
        "route": route,
        "conf_changed": conf_changed,
    }

def _mpc_outputs() -> list[tuple[int, str, bool]]:
    try:
        proc = subprocess.run(
            ["mpc", "outputs"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:
        return []
    out: list[tuple[int, str, bool]] = []
    for line in (proc.stdout or "").splitlines():
        m = re.match(r"Output\s+(\d+)\s+\((.+)\)\s+is\s+(enabled|disabled)", line.strip(), re.I)
        if m:
            out.append((int(m.group(1)), m.group(2).strip(), m.group(3).lower() == "enabled"))
    return out


def _output_nums_by_name(names: set[str]) -> list[int]:
    nums: list[int] = []
    for num, name, _ in _mpc_outputs():
        if name in names:
            nums.append(num)
    return nums


def apply_mpd_outputs(mode: PlaybackMode) -> dict[str, Any]:
    """MPD 출력 enable/disable — spectrum tap은 항상 유지.

    상주 Camilla: PCM은 Whick DSP(Loopback feed) 고정.
    Direct는 DSD DoP 등 예외만.
    """
    if mode == "null":
        return {"ok": True, "mode": mode, "skipped": "camilla disabled"}

    direct = _output_nums_by_name({"Whick Direct"})
    dsp = _output_nums_by_name({"Whick CamillaDSP", "Whick DSP"})
    spectrum = _output_nums_by_name({"Whick spectrum tap"})
    legacy_pipe = _output_nums_by_name({"Whick CamillaDSP"}) if mode == "legacy" else []

    try:
        if mode == "legacy":
            enable = legacy_pipe + spectrum
            if enable:
                subprocess.run(
                    ["mpc", "enable", "only", *[str(n) for n in enable]],
                    timeout=5,
                    check=False,
                    capture_output=True,
                )
        elif mode in ("bitperfect", "dsd_dop"):
            enable = direct + spectrum
            if enable:
                subprocess.run(
                    ["mpc", "enable", "only", *[str(n) for n in enable]],
                    timeout=5,
                    check=False,
                    capture_output=True,
                )
        elif mode == "dsp":
            enable = dsp + spectrum
            if enable:
                subprocess.run(
                    ["mpc", "enable", "only", *[str(n) for n in enable]],
                    timeout=5,
                    check=False,
                    capture_output=True,
                )
    except Exception as exc:
        return {"ok": False, "mode": mode, "error": str(exc)}

    return {
        "ok": True,
        "mode": mode,
        "direct": direct,
        "dsp": dsp,
        "spectrum": spectrum,
        "camilla_resident": mode == "dsp",
    }


def read_alsa_hw_params() -> dict[str, Any]:
    """재생 중 ALSA hw_params — Whick Direct DAC playback(p) 장치만."""
    base = asound_root()
    if not base.is_dir():
        return {}
    target_cards = _target_alsa_card_names()
    best: tuple[int, dict[str, Any]] | None = None
    for hw in base.glob("card*/pcm*p/sub*/hw_params"):
        try:
            text = hw.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "closed" in text.lower() or "format:" not in text:
            continue
        card_dir = hw.parts[3] if len(hw.parts) > 3 else ""
        card_id_path = base / card_dir / "id"
        card_name = card_id_path.read_text(encoding="utf-8", errors="replace").strip() if card_id_path.is_file() else card_dir
        if target_cards and card_name not in target_cards and card_dir not in target_cards:
            continue
        fields: dict[str, str] = {}
        for line in text.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                fields[k.strip().lower()] = v.strip()
        rate_m = re.search(r"(\d+)", fields.get("rate", ""))
        bits_m = re.search(r"(\d+)", fields.get("format", ""))
        if not rate_m:
            continue
        info = {
            "card": card_name,
            "rate": int(rate_m.group(1)),
            "format": fields.get("format", ""),
            "bit_depth": int(bits_m.group(1)) if bits_m else None,
            "channels": fields.get("channels", ""),
        }
        if best is None or info["rate"] > best[0]:
            best = (info["rate"], info)
    return best[1] if best else {}


def build_playback_state(
    profile: dict[str, Any] | None,
    *,
    source_bit_depth: int | None = None,
    source_sample_rate: int | None = None,
    source_format: str = "",
    file_path: str = "",
) -> dict[str, Any]:
    meta = read_current_playback()
    file_path = file_path or str(meta.get("file_path") or "")
    ext = Path(file_path).suffix.lower() if file_path else ""
    is_dsd = ext in DSD_EXTS or bool(meta.get("is_dsd"))
    mode = resolve_playback_mode(profile)
    src_sr = int(source_sample_rate or meta.get("sample_rate") or 44100)
    if is_dsd and mode != "null":
        plan = dsd_playback_plan(file_path or meta.get("file_path", ""), raw_sample_rate=src_sr)
        mode = "dsd_dop" if plan.get("dop") else "bitperfect"
    elif is_dsd:
        plan = None
    else:
        plan = None

    src_bd = int(source_bit_depth or meta.get("bit_depth") or 16)
    src_fmt = source_format or str(meta.get("source_format") or "")

    from api.alsa_device import resolve_direct_alsa_device, resolve_direct_mixer_type
    from api.dac_capability import clamp_pcm_rate, load_dac_capability, pcm_exceeds_dac_cap
    from api.playback_config import dsp_pipe_rate_hz

    alsa_dev = resolve_direct_alsa_device()
    mixer_type = resolve_direct_mixer_type()
    cap = load_dac_capability()
    cap_sr = int(cap.get("pcm_max_sample_rate") or 384000)
    expected_pcm_sr = clamp_pcm_rate(src_sr) if not is_dsd else src_sr

    hw = read_alsa_hw_params()
    out_sr = int(hw.get("rate") or 0)
    out_bd = hw.get("bit_depth")
    dsp_active = mode == "dsp" and profile_needs_dsp(profile)
    resampled = False
    resample_reason: str | None = None

    if mode in ("bitperfect", "dsd_dop"):
        if mode == "dsd_dop" and plan:
            out_sr = int(plan.get("dop_wrapper_rate") or dop_wrapper_rate(dsd_format_from_rate(src_sr)))
            out_bd = 24
            resampled = False
        elif mode == "bitperfect":
            if alsa_dev.startswith("plughw:"):
                resample_reason = resample_reason or "plughw_may_resample"
            if pcm_exceeds_dac_cap(src_sr):
                resampled = True
                resample_reason = f"dac_cap_{cap_sr}"
            if out_sr and src_sr and out_sr != src_sr:
                resampled = True
                resample_reason = resample_reason or f"hw_rate_{out_sr}_vs_source_{src_sr}"
            if out_bd and src_bd and int(out_bd) != src_bd:
                resampled = True
                resample_reason = resample_reason or f"hw_bits_{out_bd}_vs_source_{src_bd}"
            if not out_sr:
                out_sr = expected_pcm_sr
            if not out_bd:
                out_bd = src_bd
    elif mode == "dsp":
        from api.camilla_loopback import loop_rate_hz

        loop_sr = loop_rate_hz()
        out_sr = int(hw.get("rate") or int(os.getenv("WHICK_DAC_ALSA_RATE", str(loop_sr))))
        out_bd = hw.get("bit_depth") or 32
        resampled = src_sr != loop_sr or bool(hw.get("rate") and hw["rate"] != src_sr)
        resample_reason = f"camilla_loop_{loop_sr}" if resampled else None
    elif mode == "legacy":
        out_sr = int(os.getenv("WHICK_DAC_ALSA_RATE", "48000"))
        out_bd = 16
        resampled = True
    else:
        out_sr = src_sr
        out_bd = src_bd

    return {
        "mode": mode,
        "source_format": src_fmt.lower(),
        "source_bit_depth": src_bd,
        "source_sample_rate": src_sr,
        "output_bit_depth": int(out_bd) if out_bd else src_bd,
        "output_sample_rate": out_sr or src_sr,
        "dsp_active": dsp_active,
        "resampled": resampled,
        "resample_reason": resample_reason,
        "alsa_device": alsa_dev,
        "mixer_type": mixer_type,
        "dac_pcm_max_sample_rate": cap_sr,
        "expected_pcm_sample_rate": expected_pcm_sr,
        "dac_cap_clamped": pcm_exceeds_dac_cap(src_sr) if not is_dsd else False,
        "is_dsd": is_dsd,
        "file_path": file_path,
        "dsd": plan,
        "dsp_pipe_rate_khz": dsp_pipe_rate_hz(profile) // 1000,
    }


def sync_playback_route(profile: dict[str, Any] | None = None) -> dict[str, Any]:
    """프로필 기준 MPD 출력 전환 + 상주 Camilla 동기화."""
    mode = resolve_playback_mode(profile)
    from api.camilla_daemon import sync_daemon_for_playback_mode

    daemon = sync_daemon_for_playback_mode(mode, profile)
    route = apply_mpd_outputs(mode)
    route["daemon"] = daemon
    return route
