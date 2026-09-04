#!/usr/bin/env python3
"""USB 부팅 — 헤드리스(모니터·키보드 없음) · 스마트폰 전용.

무선: provision.json STA만 (wifi_ssid/password). 가상 공유기·캡티브 포털 없음.
유선: eth/USB-LAN DHCP. 폰 포털은 LAN IP 또는 whick.org 개인 URL.
full 프로필 WAN 없음: eth 대기 또는 명확 실패 — 가상 AP 기동 금지.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, urlparse

from error_guide import classify_install_error, guide_by_code
from i18n_msg import bi

RETRYABLE_CC_ERROR_CODES = frozenset(
    {
        "server_unreachable",
        "server_register",
        "hw_identity",
        "network",
        "unknown",
        "wifi_provision",
        "",
    }
)
NON_RETRYABLE_CC_ERROR_CODES = frozenset(
    {
        "wifi_auth",
        "wifi_failed",
        "hw_not_authorized",
        "install_complete",
        "ap_failed",
        "cc_install_failed",
    }
)

from cc_client import (
    ack_bootstrap_command,
    cc_health_ok,
    fetch_remote_phase_bundle,
    auto_register_product,
    fetch_install_session,
    patch_session_progress,
    register_product,
    report_access_ready,
    report_hw_fingerprint,
    keepalive_session,
    submit_reinstall_consent,
)

SKIP_HW_ID = os.environ.get("WHICK_SKIP_HW_ID", "0").strip().lower() not in ("0", "false", "no")

ROOT = Path(__file__).resolve().parent
WHICK_BUILD = os.environ.get("WHICK_CONNECT_BUILD", "dev")
WHICK_VERSION = os.environ.get("WHICK_CONNECT_VERSION", "")
NET_PROFILE_PATHS = (
    ROOT / "net-profile",
    Path("/opt/whick-boot-connect/net-profile"),
)
PROVISION_PATHS = (
    ROOT / "provision.json",
    Path("/opt/whick/boot-connect/provision.json"),
    Path("/opt/whick-boot-connect/provision.json"),
    Path("/etc/whick/provision.json"),
    Path("/mnt/whick-media/whick-os/opt/whick/boot-connect/provision.json"),
    Path("/cdrom/whick-os/opt/whick/boot-connect/provision.json"),
    Path("/mnt/whick-media/casper/whick-os/opt/whick/boot-connect/provision.json"),
    Path("/cdrom/casper/whick-os/opt/whick/boot-connect/provision.json"),
)
BOOTSTRAP_SESSION_PATHS = (
    Path(os.environ.get("WHICK_BOOTSTRAP_SESSION", "/tmp/whick-bootstrap-session.json")),
    ROOT / "whick-bootstrap-session.json",
    Path("/opt/whick/boot-connect/whick-bootstrap-session.json"),
    Path("/opt/whick-boot-connect/whick-bootstrap-session.json"),
    Path("/etc/whick/whick-bootstrap-session.json"),
    Path("/mnt/whick-media/whick-os/opt/whick/boot-connect/whick-bootstrap-session.json"),
    Path("/cdrom/whick-os/opt/whick/boot-connect/whick-bootstrap-session.json"),
    Path("/mnt/whick-media/casper/whick-os/opt/whick/boot-connect/whick-bootstrap-session.json"),
    Path("/cdrom/casper/whick-os/opt/whick/boot-connect/whick-bootstrap-session.json"),
)
TEMPLATE = ROOT / "templates" / "install.html"
STATE_PATH = Path(os.environ.get("WHICK_SETUP_STATE", "/tmp/whick-setup-state.json"))
BOOTSTRAP_PATH = Path(os.environ.get("WHICK_BOOTSTRAP_SESSION", "/tmp/whick-bootstrap-session.json"))
PORT = int(os.environ.get("WHICK_PHONE_PORT", "80"))
WIFI_IF = os.environ.get("WHICK_WIFI_IF", "")
LOG = Path(os.environ.get("WHICK_SETUP_LOG", "/tmp/whick-customer-setup.log"))

_lock = threading.RLock()
_connect_lock = threading.Lock()
_connect_started = False
_boot_connect_running = False
_hw_report_lock = threading.Lock()
_hw_report_running = False
_error_auto_retry_lock = threading.Lock()
_error_auto_retry_running = False
_wifi_connect_lock = threading.Lock()
_wifi_connect_started = False

_access_invite_lock = threading.Lock()
_access_invite_sent = False
_access_invite_poll_active = False

_auto_register_lock = threading.Lock()
_auto_register_started = False

_remote_cmd_lock = threading.Lock()
_remote_cmd_id: int | None = None
_remote_cmd_running = False
_remote_bundle_lock = threading.Lock()
_remote_bundle_ready = False
_install_reboot_lock = threading.Lock()
_install_reboot_scheduled = False

REBOOT_USB_REMOVE_SEC = max(10, int(os.environ.get("WHICK_INSTALL_REBOOT_DELAY_SEC", "30")))


def env_usb_live() -> bool:
    if os.environ.get("WHICK_PROD_INSTALL", "").strip() in ("1", "true", "yes"):
        return False
    return os.environ.get("WHICK_USB_LIVE_INSTALL", "1").strip() in ("1", "true", "yes")

CC_REMOTE_COMMAND_SCRIPTS = {
    "install_linux": "02_linux_install.sh",
    "install_docker": "03_docker.sh",
    "install_runtime": "04_runtime.sh",
}
REMOTE_CC_PHASES = frozenset(
    {"register_done", "install_linux", "install_docker", "install_runtime", "complete"}
)
REINSTALL_CONSENT_PHASES = frozenset(
    {
        "reinstall_consent_pending",
        "reinstall_consent_done",
        "reinstall_consent_denied",
        "register_pending",
    }
)
# 동의 완료 후에는 auto-register가 진행되어야 함 — pending/denied만 등록 차단
REINSTALL_CONSENT_REGISTER_BLOCKED = frozenset(
    {
        "reinstall_consent_pending",
        "reinstall_consent_denied",
    }
)
REMOTE_CC_PHASE_HINTS = {
    "register_done": (100, bi("초기 연동 완료 — Whick 원격 설치 대기", "Initial link done — waiting for Whick remote install")),
    "install_linux": (10, bi("Linux 설치 중… (Whick 원격 1/3)", "Installing Linux… (Whick remote 1/3)")),
    "install_docker": (45, bi("Docker 설치 중… (Whick 원격 2/3)", "Installing Docker… (Whick remote 2/3)")),
    "install_runtime": (75, bi("뮤직서버 준비 중… (Whick 원격 3/3)", "Preparing music server… (Whick remote 3/3)")),
    "complete": (100, bi("설치 완료 — SSD Ubuntu · 관제 전환", "Install complete — SSD Ubuntu · ops handoff")),
}
TTY_INSTALL_PHASES = frozenset(
    {
        "register_done",
        "install_linux",
        "install_docker",
        "install_runtime",
        "reboot_pending",
        "post_install_verify",
    }
)


def _post_install_reboot_message(remaining: int | None = None) -> str:
    # host_reboot 카운트다운 — T-60 USB 제거 가능.
    if remaining is not None and remaining > 0:
        return bi(
            f"지금 설치 USB를 제거하세요 · SSD 재부팅까지 {remaining}초",
            f"Remove USB now — SSD reboot in {remaining}s",
        )
    return bi(
        f"지금 설치 USB를 제거하세요 · SSD 재부팅까지 {REBOOT_USB_REMOVE_SEC}초",
        f"Remove USB now — SSD reboot in {REBOOT_USB_REMOVE_SEC}s",
    )


def _linux_install_completed_on_device() -> bool:
    phase_dir = Path(os.environ.get("WHICK_PHASE_DIR", "/tmp/whick-phases"))
    return (phase_dir / "linux_install_done").is_file()


def schedule_post_install_reboot(delay_sec: int | None = None) -> None:
    """CC host_reboot — T-60 안내 후 자동 재부팅.

    카운트다운·reboot 는 tmpfs(/run) 스크립트로 돌려 USB 제거 후에도 재부팅이 살아 있게 한다.
    linux_install_done 이 있으면 preview(usb_live) 스킵을 무시하고 반드시 물리 재부팅한다.
    """
    global _install_reboot_scheduled
    with _install_reboot_lock:
        if _install_reboot_scheduled:
            return
        _install_reboot_scheduled = True
    delay = max(10, int(delay_sec or REBOOT_USB_REMOVE_SEC))
    threading.Thread(target=_post_install_reboot_worker, args=(delay,), daemon=True).start()


def _arm_tmpfs_deferred_reboot(delay_sec: int) -> Path | None:
    """USB root 가 사라져도 재부팅되도록 /run 에 sleep+reboot 스크립트를 심는다."""
    delay = max(10, int(delay_sec))
    for run_dir in (Path("/run/whick"), Path("/dev/shm/whick"), Path("/tmp/whick")):
        try:
            run_dir.mkdir(parents=True, exist_ok=True)
            script = run_dir / "deferred-reboot.sh"
            script.write_text(
                "#!/bin/sh\n"
                f"sleep {delay}\n"
                "sync\n"
                "reboot -ff 2>/dev/null || true\n"
                "sleep 1\n"
                "echo 1 > /proc/sys/kernel/sysrq 2>/dev/null || true\n"
                "echo b > /proc/sysrq-trigger 2>/dev/null || true\n"
                "systemctl --force --force reboot 2>/dev/null || true\n",
                encoding="utf-8",
            )
            script.chmod(0o755)
            # start_new_session — USB umount / parent death 에도 남도록
            subprocess.Popen(
                ["/bin/sh", str(script)],
                start_new_session=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
            log(f"tmpfs deferred reboot armed delay={delay}s script={script}")
            return script
        except OSError as exc:
            log(f"tmpfs deferred reboot arm failed at {run_dir}: {exc}")
    return None


def _issue_force_reboot() -> None:
    """casper Live 에서 언마운트 없이 즉시 재부팅.

    systemctl 을 먼저 호출하면 서비스 정리·매체 언마운트에 걸려 파이썬이 죽고
    reboot -ff / SysRq 폴백까지 도달하지 못한다 (세션 275·280).
    순서: reboot -ff → SysRq b → systemctl(최후·timeout).
    """
    try:
        subprocess.run(["sync"], check=False, timeout=15)
    except Exception as exc:
        log(f"sync before reboot failed: {exc}")

    try:
        subprocess.Popen(["reboot", "-ff"], start_new_session=True)
        log("reboot -ff issued")
    except Exception as exc:
        log(f"reboot -ff failed: {exc}")
    time.sleep(1)

    try:
        with open("/proc/sys/kernel/sysrq", "w") as f:
            f.write("1")
        with open("/proc/sysrq-trigger", "w") as f:
            f.write("b")
        log("sysrq b issued")
    except OSError as exc:
        log(f"sysrq reboot failed: {exc}")
    time.sleep(1)

    try:
        subprocess.run(
            ["systemctl", "--force", "--force", "reboot"],
            check=False,
            timeout=5,
        )
    except Exception as exc:
        log(f"systemctl reboot failed: {exc}")
    log("reboot commands issued (force path: reboot-ff → sysrq → systemctl)")


def _post_install_reboot_worker(delay_sec: int = REBOOT_USB_REMOVE_SEC) -> None:
    delay = max(10, int(delay_sec or REBOOT_USB_REMOVE_SEC))

    if not _linux_install_completed_on_device():
        log("reboot blocked — install_linux not finished (linux_install_done missing)")
        msg = (
            "Reboot held — Ubuntu not deployed to SSD yet. "
            "Complete partition apply + rootfs (install_linux) before reboot."
        )
        tty_write(
            [
                "",
                "  Reboot waiting (SSD Ubuntu not installed)",
                "",
                "  Finish partition apply and Ubuntu rootfs deploy,",
                "  then remove USB and reboot.",
                "",
            ]
        )
        set_state(phase="install_linux", progress_pct=50, progress_msg=msg)
        write_tty_status(force=True)
        sync_cc_progress(
            phase="install_linux",
            progress_pct=50,
            progress_msg=msg,
        )
        return

    # SSD Ubuntu 배포 완료 — preview(usb_live)여도 물리 재부팅 필수
    if env_usb_live():
        log(
            "USB live flag set but linux_install_done present — forcing physical reboot "
            f"(PROD_INSTALL={os.environ.get('WHICK_PROD_INSTALL', '')!r} "
            f"USB_LIVE={os.environ.get('WHICK_USB_LIVE_INSTALL', '')!r})"
        )

    log(f"post-install reboot scheduled in {delay}s — remove USB now")
    # USB 뽑아도 재부팅되도록 먼저 tmpfs 에 암
    _arm_tmpfs_deferred_reboot(delay)
    sync_cc_progress(
        phase="reboot_pending",
        progress_pct=98,
        progress_msg=bi(f"[reboot:countdown] 지금 설치 USB를 제거하세요 · SSD 전환 재부팅까지 {delay}초", f"[reboot:countdown] Remove the install USB now — SSD reboot in {delay}s"),
        wait=True,
    )
    for remaining in range(delay, 0, -1):
        msg = _post_install_reboot_message(remaining)
        set_state(phase="done", progress_pct=100, progress_msg=msg)
        write_tty_status(force=True)
        time.sleep(1)
    log("post-install reboot now")
    tty_write(
        [
            "",
            "  Rebooting to SSD Ubuntu…",
            "  USB should already be removed.",
            "",
        ]
    )
    sync_cc_progress(
        phase="reboot_pending",
        progress_pct=98,
        progress_msg="[reboot:issuing] force reboot now",
        wait=True,
    )
    _issue_force_reboot()


def _cc_remote_poll_interval() -> int:
    push = os.environ.get("WHICK_CC_INSTALL_PUSH", "").strip() in ("1", "true", "yes")
    default = "8" if push else "12"
    return max(8, int(os.environ.get("WHICK_CC_REMOTE_POLL_SEC", default)))


def sync_cc_session_state(sess: dict) -> bool:
    """CC session/me → 로컬 phase·진행률·TTY (변경 시 True)."""
    cc_phase = str(sess.get("phase") or "")
    set_state(cc_phase=cc_phase)
    if cc_phase == "failed":
        err_msg = str(sess.get("progress_msg") or sess.get("error") or "CC install failed").strip()
        set_install_error(err_msg or "CC install failed", code="cc_install_failed")
        return True
    if cc_phase not in REMOTE_CC_PHASES:
        return False

    st = get_state()
    local_phase = str(st.get("phase") or "")
    cc_step_pct = sess.get("phase_progress_pct")
    cc_pct = sess.get("progress_pct")
    cc_msg = str(sess.get("progress_msg") or "").strip()

    if cc_phase == "complete":
        if local_phase != "done":
            # USB Live: orchestrator가 host_reboot → reboot_pending 후 complete — premature reboot 방지
            ri = sess.get("remote_install") or {}
            cmd = ri.get("command") or {}
            ctype = str(cmd.get("type") or "")
            if env_usb_live() and ctype not in ("host_reboot", "") and local_phase not in (
                "reboot_pending",
                "post_install_verify",
            ):
                log(
                    f"sync_cc: ignore premature complete (usb live, active_cmd={ctype}, local={local_phase})"
                )
                return False
            if not _linux_install_completed_on_device():
                log("sync_cc: ignore complete — linux_install_done missing (SSD OS required before reboot)")
                set_state(
                    phase="install_linux",
                    progress_pct=50,
                    progress_msg="Waiting for SSD Ubuntu — finish partition + rootfs before reboot",
                )
                write_tty_status(force=True)
                return True
            reboot_msg = _post_install_reboot_message()
            set_state(
                phase="done",
                progress_pct=100,
                progress_msg=reboot_msg,
            )
            write_tty_status(force=True)
            schedule_post_install_reboot()
            return True
        return False

    hint = REMOTE_CC_PHASE_HINTS.get(cc_phase)
    if cc_step_pct is not None:
        pct = int(cc_step_pct)
    else:
        pct = int(cc_pct) if cc_pct is not None else (hint[0] if hint else st.get("progress_pct"))
    msg = cc_msg or (hint[1] if hint else st.get("progress_msg") or "")
    detail = _install_progress_detail(cc_phase, pct, msg)

    changed = (
        local_phase != cc_phase
        or int(st.get("phase_progress_pct") if st.get("phase_progress_pct") is not None else st.get("progress_pct") or 0)
        != int(pct or 0)
        or str(st.get("progress_msg") or "").strip() != str(msg or "").strip()
    )
    if cc_phase == "register_done":
        set_state(
            phase="register_done",
            registered=True,
            progress_pct=pct,
            phase_progress_pct=pct,
            progress_msg=msg or REMOTE_CC_PHASE_HINTS["register_done"][1],
            progress_detail=detail,
        )
    else:
        set_state(
            phase=cc_phase,
            progress_pct=pct,
            phase_progress_pct=pct,
            progress_msg=msg,
            progress_detail=detail,
        )

    if changed:
        write_tty_status()
        return True
    return False

MAX_POST_BODY = 65536

_tty_written_fingerprint: str = ""

INSTALL_PUSH_TITLE = "Whick 설치"
EMAIL_PENDING_BODY = bi(
    "서버에서 설치 안내 메일을 보내고 있습니다…",
    "Sending the install guide email from the server…",
)
PORTAL_GUIDE_BODY = bi(
    "같은 Wi-Fi에서 whick.org에 로그인한 뒤, 고유 접속 주소(/page/계정)에서 설치 안내를 따라 주세요.",
    "On the same Wi-Fi, log in to whick.org, then follow the install guide at your personal URL (/page/account).",
)
LAN_PUSH_BODY = PORTAL_GUIDE_BODY
LEGACY_PORT = 8765

_state: dict = {
    "phase": "welcome",
    "setup_mode": "lan",
    "phone_seen": False,
    "lan_url": "",
    "wired_ok": False,
    "wan_ok": False,
    "home_ssid": "",
    "reconnect_url": "",
    "progress_pct": 0,
    "phase_progress_pct": 0,
    "display_phase_pct": 0,
    "progress_msg": bi("Whick 서버 연결 중… 설치 안내는 이메일로 보냅니다.", "Connecting to Whick… Install guide will be emailed."),
    "progress_detail": "",
    "device_code": "",
    "member_no": "",
    "device_id": None,
    "registered": False,
    "bootstrap_token": "",
    "session_id": None,
    "hw_id_hash": "",
    "error": "",
    "error_code": "",
    "error_title": "",
    "error_steps": [],
    "phone_login_url": "",
    "install_portal_url": "",
    "phone_alert_id": 0,
    "phone_alert_title": "",
    "phone_alert_body": "",
    "mb_id": "",
    "can_auto_register": False,
    "auto_register_error": "",
}


def load_boot_connect_diagnostics() -> dict:
    """boot-connect result + log tail — TTY/API 진단용."""
    result_path = Path(os.environ.get("WHICK_CONNECT_RESULT", "/tmp/whick-connect-result.json"))
    log_path = Path(os.environ.get("WHICK_CONNECT_LOG", "/tmp/whick-connect.log"))
    diag: dict = {"error": "", "error_code": "", "log_tail": [], "result_raw": ""}
    try:
        raw = result_path.read_text(encoding="utf-8", errors="replace").strip()
        diag["result_raw"] = raw[:240]
        if raw:
            data = json.loads(raw)
            if isinstance(data, dict):
                diag["error"] = str(data.get("error") or "")
                diag["error_code"] = str(data.get("error_code") or "")
                if data.get("hw_report_error"):
                    diag["hw_report_error"] = str(data.get("hw_report_error"))
                if data.get("link_ok"):
                    diag["link_ok"] = True
    except (OSError, json.JSONDecodeError):
        if not diag["error"]:
            diag["error"] = "connect result missing or invalid"
            diag["error_code"] = "server_unreachable"
    try:
        if log_path.is_file():
            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            diag["log_tail"] = [ln for ln in lines[-8:] if ln.strip()]
    except OSError:
        pass
    if not diag["error"] and diag["log_tail"]:
        diag["error"] = diag["log_tail"][-1][:160]
    if not diag["error_code"] and diag["error"]:
        low = diag["error"].lower()
        if low.startswith("health:") or "ssl" in low or "timed out" in low:
            diag["error_code"] = "server_unreachable"
        elif low.startswith("session:") or low.startswith("link:"):
            diag["error_code"] = "server_register"
    return diag


def customer_setup_url() -> str:
    """고객 스마트폰 SSOT — LAN URL 또는 whick.org 개인 포털."""
    st = get_state()
    portal = resolve_customer_portal_url()
    if portal and customer_portal_profile():
        return portal
    return (st.get("lan_url") or st.get("phone_login_url") or st.get("install_portal_url") or "").strip()


def apply_customer_setup_url(*, reason: str = "lan") -> str:
    """고객-facing URL 갱신 (LAN IP / 개인 포털)."""
    url = customer_setup_url()
    eth = get_eth_ip() or get_lan_ip()
    lan_debug = f"http://{eth}:{PORT}/" if eth else ""
    updates: dict = {
        "phone_login_url": url or lan_debug,
        "reconnect_url": url or lan_debug,
    }
    if lan_debug:
        updates["lan_url"] = lan_debug
    if reason == "register_ready" and (url or lan_debug):
        shown = url or lan_debug
        updates["phone_alert_title"] = INSTALL_PUSH_TITLE
        updates["phone_alert_body"] = bi(f"같은 Wi-Fi · {shown} — 장비 등록이 자동으로 진행됩니다", f"Same Wi-Fi · {shown} — device registration continues automatically")
    set_state(**updates)
    return url or lan_debug


def session_keepalive_loop() -> None:
    """CC bootstrap 세션 만료 방지 — 초기 연동·원격 설치(5~7) 전 구간."""
    base = max(60, int(os.environ.get("WHICK_KEEPALIVE_SEC", "120")))
    stop_phases = frozenset({"done", "error"})
    while True:
        st = get_state()
        phase = str(st.get("phase") or "")
        if phase in stop_phases:
            break
        interval = (
            _cc_remote_poll_interval()
            if phase == "register_done" or phase.startswith("install_") or st.get("registered")
            else base
        )
        time.sleep(interval)
        st = get_state()
        phase = str(st.get("phase") or "")
        if phase in stop_phases:
            break
        if (
            phase == "register_done"
            or phase.startswith("install_")
            or st.get("registered")
        ):
            handle_cc_remote_install()
        boot = load_bootstrap_session()
        token = st.get("bootstrap_token") or (boot or {}).get("bootstrap_token") or ""
        sid = st.get("session_id") or (boot or {}).get("session_id")
        if not token or not sid:
            continue
        ok = False
        for attempt in range(3):
            try:
                keepalive_session(token, int(sid))
                log(f"install session keepalive OK phase={phase}")
                ok = True
                break
            except Exception as e:
                log(f"install session keepalive ({attempt + 1}/3): {e}")
                time.sleep(min(15, 5 * (attempt + 1)))
        if not ok and not has_wan():
            log("install session keepalive: WAN down — retry next interval")

def has_install_session() -> bool:
    st = get_state()
    if st.get("bootstrap_token") or st.get("session_id"):
        return True
    boot = load_bootstrap_session()
    return bool(boot and boot.get("bootstrap_token"))

_CC_NO_REGRESS_PHASES = REMOTE_CC_PHASES | {
    "register_done",
    "register_pending",
    "register_needed",
    "failed",
    "done",
    "error",
}


def _may_sync_cc_phone_phase(phase: str) -> bool:
    """등록·원격 설치 중에는 phone_seen이 CC phase를 되돌리지 않음."""
    return str(phase or "") not in _CC_NO_REGRESS_PHASES


def _cc_session_blocks_auto_register(sess: dict | None) -> bool:
    if not sess:
        return False
    rc = sess.get("reinstall_consent") or {}
    if rc.get("blocks_register"):
        return True
    phase = str(sess.get("phase") or "")
    return phase in ("reinstall_consent_pending", "reinstall_consent_denied")


def _apply_cc_reinstall_consent_state(sess: dict, *, phone_seen: bool = False) -> None:
    cc_phase = str(sess.get("phase") or "")
    local_phase = cc_phase if cc_phase in REINSTALL_CONSENT_PHASES else "reinstall_consent_pending"
    updates: dict = {
        "cc_phase": cc_phase,
        "phase": local_phase,
        "progress_pct": int(sess.get("progress_pct") or 0),
        "progress_msg": str(sess.get("progress_msg") or "재설치 동의 대기"),
        "reinstall_consent": sess.get("reinstall_consent") or {},
        "can_auto_register": bool(sess.get("can_auto_register")),
    }
    if phone_seen:
        updates["phone_seen"] = True
    mb_id = str(sess.get("mb_id") or "").strip()
    if mb_id:
        updates["mb_id"] = mb_id
    set_state(**updates)
    write_tty_status(force=True)


def mark_phone_seen(client_ip: str) -> None:
    if not client_ip or client_ip.startswith("127."):
        return
    st = get_state()
    phase = st.get("phase")

    if has_install_session() and phase in (
        "await_phone",
        "lan_setup",
        "phone_login_ready",
    ):
        try:
            token, _ = _bootstrap_credentials()
            if token:
                sess = fetch_install_session(token)
                if _cc_session_blocks_auto_register(sess):
                    _apply_cc_reinstall_consent_state(sess, phone_seen=True)
                    log(
                        f"phone seen — reinstall consent blocks register "
                        f"phase={sess.get('phase')}"
                    )
                    return
        except Exception as exc:
            log(f"phone seen cc session check: {exc}")
        url = (st.get("lan_url") or st.get("phone_login_url") or "").strip()
        set_state(
            phone_seen=True,
            phase="register_needed",
            progress_pct=max(int(st.get("progress_pct") or 0), 70),
            progress_msg=bi("Whick 연결 완료 — 장비 등록을 자동으로 진행합니다", "Whick connected — registering the device automatically"),
            auto_register_error="",
        )
        sync_cc_progress(
            phase="register_pending",
            progress_pct=70,
            progress_msg="phone_seen — auto-register",
        )
        if url:
            notify_phone_login(url, reason="register_ready")
        try_auto_register()
        log(f"phone seen from {client_ip} -> register_needed (auto)")
        return
    if st.get("phone_seen"):
        return
    new_phase = "await_phone" if phase in ("welcome", "network_scan", "phone_login_ready") else phase
    set_state(
        phone_seen=True,
        phase=new_phase,
        progress_msg=bi("스마트폰 연결됨 — 설치를 계속합니다.", "Phone connected — continuing install."),
    )
    if _may_sync_cc_phone_phase(phase) and _may_sync_cc_phone_phase(new_phase):
        sync_cc_progress(
            phase="await_phone",
            progress_pct=max(int(st.get("progress_pct") or 0), 55),
            progress_msg="phone_seen",
        )
    log(f"phone seen from {client_ip}")


def _bootstrap_credentials() -> tuple[str, int | None]:
    boot = load_bootstrap_session()
    with _lock:
        token = _state.get("bootstrap_token") or ""
        sid = _state.get("session_id")
    if not token and boot:
        apply_bootstrap_session(boot)
        with _lock:
            token = _state.get("bootstrap_token") or ""
            sid = _state.get("session_id")
    if not sid and boot:
        sid = boot.get("session_id")
    return token, int(sid) if sid else None


def sync_cc_progress(
    phase: str = "",
    progress_pct: int | None = None,
    progress_msg: str = "",
    phase_progress_pct: int | None = None,
    *,
    wait: bool = False,
) -> None:
    """관제 CC — await_phone / register_pending 등 중간 phase 반영.

    wait=True: 재부팅 직전처럼 프로세스 종료 전에 PATCH 가 끝나야 할 때 동기 호출.
    """
    step_pct = phase_progress_pct if phase_progress_pct is not None else progress_pct

    def worker() -> None:
        try:
            token, sid = _bootstrap_credentials()
            if not token or not sid:
                return
            patch_session_progress(
                token,
                sid,
                phase=phase,
                progress_pct=progress_pct,
                phase_progress_pct=step_pct,
                progress_msg=progress_msg,
            )
        except Exception as exc:
            log(f"sync_cc_progress: {exc}")

    if wait:
        worker()
        return
    threading.Thread(target=worker, daemon=True).start()


def _remote_phase_cache_dir() -> Path:
    return Path(os.environ.get("WHICK_REMOTE_PHASE_DIR", "/tmp/whick-cc-phases"))


def _ensure_remote_phase_bundle(token: str) -> None:
    global _remote_bundle_ready
    cache = _remote_phase_cache_dir()
    marker = cache / ".bundle-ok"
    remote_version = ""
    try:
        from cc_client import fetch_remote_phase_bundle_meta

        remote_version = str(fetch_remote_phase_bundle_meta(token) or "").strip()
    except Exception as exc:
        log(f"remote phase bundle meta: {exc}")
    with _remote_bundle_lock:
        cached_version = marker.read_text(encoding="utf-8").strip() if marker.is_file() else ""
        if (
            marker.is_file()
            and _remote_bundle_ready
            and remote_version
            and cached_version == remote_version
        ):
            return
        fetch_remote_phase_bundle(token, str(cache))
        _remote_bundle_ready = True
        log(f"remote phase bundle OK cache={cache} v={marker.read_text(encoding='utf-8')[:16]}")


def _resolve_phase_script(command_type: str) -> Path | None:
    script_name = CC_REMOTE_COMMAND_SCRIPTS.get(command_type)
    if not script_name:
        return None
    cached = _remote_phase_cache_dir() / "phases" / script_name
    if cached.is_file():
        return cached
    # dev / 7_ai_only checkout fallback (not shipped on USB apkovl)
    uab_live = os.environ.get("WHICK_UAB_LIVE_ROOT", "").strip()
    bases = []
    if uab_live:
        bases.append(Path(uab_live) / "phases")
    bases.extend([ROOT.parent / "live" / "phases", ROOT / "phases"])
    for base in bases:
        candidate = base / script_name
        if candidate.is_file():
            return candidate
    return None


def _apply_ack_followup(ack_result: dict | None) -> None:
    """Ack 응답 next_command — WS 없을 때 SLO-R3 (≤1s 다음 command)."""
    if not isinstance(ack_result, dict):
        return
    sv = ack_result.get("session_view")
    cmd = ack_result.get("next_command")
    if not cmd and isinstance(sv, dict):
        cmd = sv.get("command")
    if cmd and cmd.get("id"):
        synthetic = {
            "phase": sv.get("phase") if isinstance(sv, dict) else None,
            "remote_install": {"command": cmd},
        }
        handle_cc_remote_install(synthetic)
        return
    if ack_result.get("next_command_id"):
        handle_cc_remote_install()


_install_ws_stop = threading.Event()
_install_ws_started = False
_install_ws_lock = threading.Lock()


def _cc_install_push_enabled() -> bool:
    return os.environ.get("WHICK_CC_INSTALL_PUSH", "").strip().lower() in ("1", "true", "yes")


def _install_ws_url(token: str) -> str:
    explicit = os.environ.get("WHICK_CC_WS_URL", "").strip()
    if explicit:
        base = explicit.rstrip("/")
        if "/ws/install-device" in base:
            return base if "token=" in base else f"{base}?token={quote(token)}"
        return f"{base}/ws/install-device?token={quote(token)}"
    api = os.environ.get("WHICK_CC_API_URL", "https://admin.whick.org/api/v1").rstrip("/")
    parsed = urlparse(api)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    host = parsed.netloc or parsed.path.split("/")[0]
    return f"{scheme}://{host}/ws/install-device?token={quote(token)}"


def _handle_install_ws_message(msg: dict) -> None:
    mtype = msg.get("type")
    if mtype == "hello":
        return
    if mtype == "command_ack":
        # Replay-safe: never trust stale next_command embedded in WS replay
        handle_cc_remote_install()
        return
    if mtype != "install_event":
        return
    et = msg.get("event_type")
    if et == "command.ack":
        handle_cc_remote_install()
        return
    if et not in ("command.enqueued", "session.update"):
        return
    token, _ = _bootstrap_credentials()
    if not token:
        return
    try:
        sess = fetch_install_session(token)
    except Exception as exc:
        log(f"install-ws fetch: {exc}")
        return
    if et == "session.update":
        sync_cc_session_state(sess)
    handle_cc_remote_install(sess)


def _dispatch_install_ws_message(msg: dict) -> None:
    threading.Thread(
        target=_handle_install_ws_message,
        args=(msg,),
        daemon=True,
        name="cc-install-ws-msg",
    ).start()


def cc_install_device_ws_loop() -> None:
    from cc_install_ws import install_device_ws_loop

    backoff = 2
    while not _install_ws_stop.is_set():
        if not _cc_install_push_enabled() or not has_wan():
            time.sleep(backoff)
            continue
        token, _ = _bootstrap_credentials()
        if not token:
            time.sleep(backoff)
            continue
        url = _install_ws_url(token)
        try:
            install_device_ws_loop(url, _dispatch_install_ws_message, stop=_install_ws_stop)
            backoff = 2
        except Exception as exc:
            log(f"install-ws: {exc}")
            backoff = min(backoff * 2, 30)
        if not _install_ws_stop.is_set():
            time.sleep(backoff)


def start_cc_install_device_ws() -> None:
    global _install_ws_started
    if not _cc_install_push_enabled():
        return
    with _install_ws_lock:
        if _install_ws_started:
            return
        _install_ws_started = True
    threading.Thread(target=cc_install_device_ws_loop, daemon=True, name="cc-install-ws").start()


def handle_cc_remote_install(sess: dict | None = None) -> None:
    """CC orchestrator 명령 pull — register_done 이후 CC가 지시한 단계만 실행."""
    global _remote_cmd_id, _remote_cmd_running
    if sess is None:
        token, _sid = _bootstrap_credentials()
        if not token:
            return
        try:
            sess = fetch_install_session(token)
        except Exception as exc:
            log(f"remote install poll: {exc}")
            return

    sync_cc_session_state(sess)

    ri = sess.get("remote_install") or {}
    cmd = ri.get("command")
    if not cmd or not cmd.get("id"):
        return

    cmd_id = int(cmd["id"])
    ctype = str(cmd.get("type") or "")
    params = cmd.get("params") or {}
    if isinstance(params, str):
        try:
            params = json.loads(params)
        except json.JSONDecodeError:
            params = {}
    if ctype in ("install_docker", "install_runtime") and str(params.get("source") or "") == "ssd_firstboot":
        log(f"remote install skip {ctype} — SSD first-boot only (source=ssd_firstboot)")
        return
    if ctype == "host_reboot":
        with _remote_cmd_lock:
            if _remote_cmd_running and _remote_cmd_id == cmd_id:
                return
            if _remote_cmd_running:
                return
            _remote_cmd_id = cmd_id
            _remote_cmd_running = True
        threading.Thread(
            target=_host_reboot_command_worker,
            args=(cmd_id, params),
            daemon=True,
        ).start()
        return

    with _remote_cmd_lock:
        if _remote_cmd_running and _remote_cmd_id == cmd_id:
            return
        if _remote_cmd_running:
            return
        _remote_cmd_id = cmd_id
        _remote_cmd_running = True
    threading.Thread(
        target=_remote_command_worker,
        args=(cmd_id, ctype, params if isinstance(params, dict) else {}),
        daemon=True,
    ).start()


def _host_reboot_command_worker(command_id: int, params: dict) -> None:
    """CC host_reboot — SSD Ubuntu 배포 확인 후 카운트다운 · 강제 재부팅."""
    global _remote_cmd_running, _remote_cmd_id, _install_reboot_scheduled
    _remote_cmd_running = True
    # 이전 skip/실패 후 재시도 가능하도록 예약 플래그 리셋
    with _install_reboot_lock:
        _install_reboot_scheduled = False
    delay = max(10, int(params.get("delay_sec") or REBOOT_USB_REMOVE_SEC))
    token, sid = _bootstrap_credentials()
    ack_result = None
    try:
        if not _linux_install_completed_on_device():
            msg = "host_reboot blocked — install_linux not finished (SSD Ubuntu required)"
            log(msg)
            if token and sid:
                try:
                    ack_bootstrap_command(token, command_id, success=False, message=msg)
                except Exception as exc:
                    log(f"host_reboot ack fail: {exc}")
            return
        # preview(usb live) + SSD 미배포: 물리 재부팅 없음
        # linux_install_done 있으면 반드시 재부팅 (flag 무시)
        if env_usb_live() and not _linux_install_completed_on_device():
            ack_msg = "preview — physical reboot skipped (usb live)"
            if token and sid:
                try:
                    ack_result = ack_bootstrap_command(
                        token,
                        command_id,
                        success=True,
                        message=ack_msg,
                    )
                except Exception as exc:
                    log(f"host_reboot ack: {exc}")
            schedule_post_install_reboot(delay_sec=delay)
            return
        if token and sid:
            try:
                ack_result = ack_bootstrap_command(
                    token,
                    command_id,
                    success=True,
                    message=f"reboot in {delay}s — remove USB now",
                )
            except Exception as exc:
                log(f"host_reboot ack: {exc}")
        schedule_post_install_reboot(delay_sec=delay)
    finally:
        _remote_cmd_running = False
        with _remote_cmd_lock:
            if _remote_cmd_id == command_id:
                _remote_cmd_id = None
        if ack_result is not None:
            _apply_ack_followup(ack_result)


def _clear_linux_install_done_after_cc_reject(
    ack_result: dict,
    command_type: str,
    phase_env: dict[str, str],
    command_id: int,
    ok_result: bool,
) -> None:
    """CC strict ack 실패 시 linux_install_done 제거 — 재시도·재실행 가능."""
    if command_type != "install_linux":
        return
    if ok_result and not ack_result.get("dry_run_rejected"):
        return
    if ack_result.get("success") is not False and not ack_result.get("dry_run_rejected"):
        return
    phase_dir = Path(phase_env.get("WHICK_PHASE_DIR", "/tmp/whick-phases"))
    try:
        (phase_dir / "linux_install_done").unlink(missing_ok=True)
    except OSError:
        pass
    if ack_result.get("dry_run_rejected"):
        log(f"remote cmd {command_id}: CC rejected dry-run ack — cleared linux_install_done")
    else:
        log(f"remote cmd {command_id}: CC rejected install_linux ack — cleared linux_install_done")


def _phase_subprocess_env(command_type: str = "") -> dict[str, str]:
    env = os.environ.copy()
    mini_bin = ROOT / "mini" / "bin"
    mini_sbin = ROOT / "mini" / "sbin"
    mini_usr_bin = ROOT / "mini" / "usr" / "bin"
    mini_usr_sbin = ROOT / "mini" / "usr" / "sbin"
    cache_bin = _remote_phase_cache_dir() / "bin"
    cache_root = _remote_phase_cache_dir()
    extra = ["/sbin", "/usr/sbin", "/bin", "/usr/bin"]
    if cache_bin.is_dir():
        extra.append(str(cache_bin))
    if mini_usr_sbin.is_dir():
        extra.append(str(mini_usr_sbin))
    if mini_usr_bin.is_dir():
        extra.append(str(mini_usr_bin))
    if mini_sbin.is_dir():
        extra.append(str(mini_sbin))
    if mini_bin.is_dir():
        extra.append(str(mini_bin))
    legacy_bin = ROOT / "bin"
    if legacy_bin.is_dir():
        extra.append(str(legacy_bin))
    env["PATH"] = ":".join(extra + [env.get("PATH", "")])
    env.setdefault("WHICK_PHASE_DIR", "/tmp/whick-phases")
    env["WHICK_USB_LIVE_INSTALL"] = "1"
    env["WHICK_BOOT_CONNECT_ROOT"] = str(ROOT)
    env["WHICK_REMOTE_PHASE_ROOT"] = str(cache_root)
    env["WHICK_BOOT_CONNECT_SRC"] = str(ROOT)
    try:
        # SSD 재부팅 후 Wi-Fi 이관용 — provision 우선, 없으면 Live STA(home_ssid + wpa conf)
        _ssid, _pwd = provision_wifi_credentials()
        if not _ssid:
            _ssid = str(get_state().get("home_ssid") or "").strip()
        if _ssid:
            env["WHICK_PROVISION_WIFI_SSID"] = _ssid
            env["WHICK_PROVISION_WIFI_PASSWORD"] = _pwd
        for _wpa in (
            Path("/tmp/whick-wpa.conf"),
            Path("/run/whick-wpa.conf"),
            Path("/etc/wpa_supplicant/wpa_supplicant.conf"),
        ):
            try:
                if _wpa.is_file() and "network={" in _wpa.read_text(encoding="utf-8", errors="replace"):
                    env["WHICK_LIVE_WPA_CONF"] = str(_wpa)
                    break
            except OSError:
                continue
    except Exception:
        pass
    usb_root = os.environ.get("WHICK_USB_ROOT", "").strip()
    if usb_root:
        env["WHICK_USB_ROOT"] = usb_root
    prod = os.environ.get("WHICK_PROD_INSTALL", "").strip() in ("1", "true", "yes")
    lab_dry = os.environ.get("WHICK_LINUX_INSTALL_DRY_RUN", "").strip() == "1"
    existing_boot = os.environ.get("WHICK_BOOTSTRAP_ROOTFS", "").strip()
    if existing_boot and Path(existing_boot).is_file():
        env["WHICK_BOOTSTRAP_ROOTFS"] = existing_boot
    if prod:
        env["WHICK_PROD_INSTALL"] = "1"
    if prod and not env.get("WHICK_BOOTSTRAP_ROOTFS"):
        for bootstrap in (
            ROOT / "bootstrap" / "whick-bootstrap-rootfs.tar.xz",
            Path("/opt/whick-boot-connect/bootstrap/whick-bootstrap-rootfs.tar.xz"),
            Path(f"{usb_root}/whick-boot-connect/bootstrap/whick-bootstrap-rootfs.tar.xz") if usb_root else None,
            Path("/data/whick-ai_music_server/3_product/dist/uab/whick-bootstrap-rootfs.tar.xz"),
        ):
            if bootstrap and bootstrap.is_file():
                env["WHICK_BOOTSTRAP_ROOTFS"] = str(bootstrap)
                break
    if prod and not lab_dry:
        env["WHICK_LINUX_INSTALL_DRY_RUN"] = "0"
        env["WHICK_ALLOW_LIVE_DISK_APPLY"] = "1"
        env["WHICK_DISK_APPLY"] = "1"
    elif lab_dry:
        env["WHICK_LINUX_INSTALL_DRY_RUN"] = "1"
    elif "WHICK_LINUX_INSTALL_DRY_RUN" not in os.environ:
        env["WHICK_LINUX_INSTALL_DRY_RUN"] = "0" if prod else "1"
    else:
        env["WHICK_LINUX_INSTALL_DRY_RUN"] = os.environ["WHICK_LINUX_INSTALL_DRY_RUN"]
    env["WHICK_SETUP_STATE"] = str(STATE_PATH)
    env["WHICK_BOOTSTRAP_SESSION"] = str(BOOTSTRAP_PATH)
    return env


def _remote_ack_message(command_type: str, ok_result: bool, env: dict[str, str], tail: str) -> str:
    """Prod CC orchestrator rejects ack message containing 'dry-run' (USB Live preview)."""
    if not ok_result:
        return tail[-200:] if tail else command_type
    if os.environ.get("WHICK_LINUX_INSTALL_SANDBOX_ACK", "").strip() == "1":
        # 7_ai_only 가상 — strict CC가 dry-run/sandbox 거부 → canonical ack (실디스크 아님)
        if command_type == "install_linux":
            return "Linux 파티션 설치 완료 — Ubuntu SSD deploy_bootstrap OK"
        return f"{command_type} sandbox ok"
    phase_dir = Path(env.get("WHICK_PHASE_DIR", "/tmp/whick-phases"))
    prod = env.get("WHICK_PROD_INSTALL", "").strip() in ("1", "true", "yes")
    usb_live = env.get("WHICK_USB_LIVE_INSTALL", "").strip() == "1"
    dry = env.get("WHICK_LINUX_INSTALL_DRY_RUN", "").strip() == "1"
    if command_type == "install_linux" and (phase_dir / "linux_install_done").is_file():
        if prod and not dry:
            return "Linux 파티션 설치 완료 — Ubuntu SSD 배포 deploy_bootstrap OK"
        if usb_live and dry:
            return "install_linux dry-run — partition only, SSD Ubuntu not deployed"
    if usb_live and dry and command_type == "install_linux":
        return "install_linux dry-run — partition only, SSD Ubuntu not deployed"
    raw = tail[-200:] if tail else command_type
    if re.search(r"dry-run", raw, re.I):
        if usb_live and command_type == "install_docker":
            return "docker deferred until Whick OS on disk"
        if usb_live and command_type == "install_runtime":
            return "runtime deferred until Whick OS on disk"
        return re.sub(r"dry-run", "preview", raw, flags=re.I)
    return raw


def _remote_command_worker(command_id: int, command_type: str, params: dict | None = None) -> None:
    global _remote_cmd_running, _remote_cmd_id
    _remote_cmd_running = True
    token, sid = _bootstrap_credentials()
    ok_result = False
    message = ""
    params = params if isinstance(params, dict) else {}
    phase_env: dict[str, str] = _phase_subprocess_env(command_type)
    if params.get("retry") in (True, "true", "1", 1):
        phase_env["WHICK_INSTALL_RETRY"] = "1"
    try:
        if token:
            try:
                _ensure_remote_phase_bundle(token)
            except Exception as exc:
                message = f"phase bundle: {exc}"
                log(f"remote cmd {command_id}: {message}")
                raise
        script = _resolve_phase_script(command_type)
        if not script:
            message = f"phase script missing: {command_type}"
            log(f"remote cmd {command_id}: {message}")
            set_install_error(message, code="server_register")
        else:
            phase_env = _phase_subprocess_env(command_type)
            if params.get("retry") in (True, "true", "1", 1):
                phase_env["WHICK_INSTALL_RETRY"] = "1"
            log(f"remote cmd {command_id}: run {script.name} ({command_type}) prod={phase_env.get('WHICK_PROD_INSTALL')} dry={phase_env.get('WHICK_LINUX_INSTALL_DRY_RUN')} retry={phase_env.get('WHICK_INSTALL_RETRY', '0')}")
            tty_write(["", f"  Whick remote install — {command_type}…", ""])
            hint = REMOTE_CC_PHASE_HINTS.get(command_type)
            if hint:
                set_state(
                    phase=command_type,
                    progress_pct=hint[0],
                    progress_msg=hint[1],
                )
                write_tty_status(force=True)
            sync_cc_progress(
                phase=command_type,
                phase_progress_pct=0,
                progress_msg=hint[1] if hint else f"CC remote {command_type}",
            )
            bash = ROOT / "mini" / "usr" / "bin" / "bash"
            if not bash.is_file():
                bash = ROOT / "mini" / "bin" / "bash"
            shell = str(bash) if bash.is_file() else (shutil.which("bash") or "/bin/sh")
            proc = subprocess.run(
                [shell, str(script)],
                env=phase_env,
                capture_output=True,
                text=True,
                timeout=7200,
            )
            tail = (proc.stdout or proc.stderr or "")[-800:]
            log(f"remote cmd {command_id} rc={proc.returncode} {tail}")
            ok_result = proc.returncode == 0
            message = _remote_ack_message(command_type, ok_result, phase_env, tail)
            if not ok_result:
                set_install_error(f"{command_type} failed", code="server_register")
    except Exception as exc:
        message = str(exc)
        log(f"remote cmd {command_id} error: {exc}")
        set_install_error(message, code="server_register")
    finally:
        ack_result = None
        if token:
            try:
                ack_result = ack_bootstrap_command(
                    token,
                    command_id,
                    success=ok_result,
                    message=message,
                )
            except Exception as exc:
                log(f"remote cmd ack {command_id}: {exc}")
        _remote_cmd_running = False
        with _remote_cmd_lock:
            if _remote_cmd_id == command_id:
                _remote_cmd_id = None
        if ack_result is not None:
            _clear_linux_install_done_after_cc_reject(
                ack_result, command_type, phase_env, command_id, ok_result
            )
            _apply_ack_followup(ack_result)
        write_tty_status(force=True)


def cc_install_sync_loop() -> None:
    """CC 세션 ↔ 로컬 phase — 유선 auto-register · CC 원격 설치 명령 pull."""
    base_interval = max(20, int(os.environ.get("WHICK_CC_SYNC_SEC", "30")))
    wired_auto_phases = frozenset(
        {
            "await_phone",
            "lan_setup",
            "phone_login_ready",
            "connecting",
            "linked",
            "hw_analyzed",
            "hw_analyzing",
            "register_needed",
            "reinstall_consent_done",
        }
    )
    while True:
        st = get_state()
        phase = str(st.get("phase") or "")
        interval = (
            _cc_remote_poll_interval()
            if phase == "register_done" or phase.startswith("install_") or st.get("registered")
            else base_interval
        )
        time.sleep(interval)
        st = get_state()
        phase = str(st.get("phase") or "")
        if phase in ("done", "error"):
            break
        if not can_poll_cc():
            continue
        token, _sid = _bootstrap_credentials()
        if not token:
            continue
        try:
            sess = fetch_install_session(token)
        except Exception as e:
            log(f"cc_install_sync: {e}")
            continue

        cc_phase = str(sess.get("phase") or "")
        mb_id = str(sess.get("mb_id") or "").strip()
        can_auto = bool(sess.get("can_auto_register"))
        if mb_id or can_auto:
            set_state(mb_id=mb_id, can_auto_register=can_auto)

        if cc_phase in REINSTALL_CONSENT_PHASES:
            set_state(
                cc_phase=cc_phase,
                phase=cc_phase,
                progress_pct=int(sess.get("progress_pct") or 0),
                progress_msg=str(sess.get("progress_msg") or ""),
                reinstall_consent=sess.get("reinstall_consent") or {},
                portal_stage=str(sess.get("portal_stage") or ""),
                portal_stage_label=str(sess.get("portal_stage_label") or ""),
            )
            write_tty_status(force=True)
            if (
                cc_phase in ("reinstall_consent_done", "register_pending")
                and can_auto
                and mb_id
            ):
                log(f"cc_install_sync: reinstall consent OK — auto-register ({mb_id[:12]}…)")
                try_auto_register()
            continue

        if cc_phase in REMOTE_CC_PHASES or cc_phase == "failed":
            sync_cc_session_state(sess)

        if (
            is_wired_usb_profile()
            and can_auto
            and mb_id
            and phase in wired_auto_phases
        ):
            log(f"cc_install_sync: wired auto-register ({mb_id[:12]}…)")
            try_auto_register()
            st = get_state()
            phase = str(st.get("phase") or "")
            cc_phase = str(sess.get("phase") or "")
            if (
                phase in wired_auto_phases
                and phase != "register_done"
                and cc_phase != "register_done"
                and not phase.startswith("install_")
            ):
                continue

        handle_cc_remote_install(sess)


def try_auto_register() -> None:
    global _auto_register_started
    with _auto_register_lock:
        st = get_state()
        if st.get("phase") == "register_done":
            handle_cc_remote_install()
            return
        if st.get("phase") in REINSTALL_CONSENT_REGISTER_BLOCKED:
            return
        if _auto_register_started or st.get("phase") in ("done", "error"):
            return
        _auto_register_started = True
        sync_cc_progress(
            phase="register_pending",
            progress_pct=75,
            progress_msg="auto-register started",
        )

    def worker() -> None:
        global _auto_register_started
        try:
            token, _sid = _bootstrap_credentials()
            if not token:
                set_state(
                    auto_register_error=bi("설치 세션이 없습니다. Whick 연결을 다시 시도해 주세요.", "No install session. Please reconnect to Whick."),
                    progress_msg=bi("설치 세션 없음 — 연결을 다시 시도합니다", "No install session — retrying connection"),
                )
                return

            for attempt in range(40):
                st = get_state()
                if st.get("phase") in ("register_done", "done", "error"):
                    if st.get("phase") == "register_done":
                        handle_cc_remote_install()
                    return
                try:
                    sess = fetch_install_session(token)
                except Exception as e:
                    log(f"auto-register session: {e}")
                    time.sleep(3)
                    continue

                mb_id = str(sess.get("mb_id") or "").strip()
                can_auto = bool(sess.get("can_auto_register"))
                set_state(mb_id=mb_id, can_auto_register=can_auto)

                if sess.get("phase") == "register_done":
                    set_state(
                        phase="register_done",
                        registered=True,
                        progress_pct=100,
                        progress_msg=bi("초기 연동 완료", "Initial link complete"),
                    )
                    write_tty_status()
                    handle_cc_remote_install()
                    return

                if can_auto and mb_id:
                    set_state(
                        phase="register_needed",
                        progress_pct=82,
                        progress_msg=bi("계정 확인됨 — 장비 등록 중…", "Account verified — registering device…"),
                        progress_detail=mb_id,
                        auto_register_error="",
                    )
                    write_tty_status()
                    try:
                        reg = auto_register_product(token)
                        set_state(
                            phase="register_done",
                            registered=True,
                            member_no=reg.get("member_no", ""),
                            device_id=reg.get("device_id"),
                            progress_pct=100,
                            progress_msg=bi("초기 연동 완료", "Initial link complete"),
                            progress_detail=reg.get("member_no", ""),
                            auto_register_error="",
                        )
                        write_tty_status()
                        log(f"auto-register OK member={reg.get('member_no')}")
                        try:
                            sess = fetch_install_session(token)
                            sync_cc_session_state(sess)
                            handle_cc_remote_install(sess)
                        except Exception as exc:
                            log(f"post-register CC sync: {exc}")
                            handle_cc_remote_install()
                    except Exception as e:
                        log(f"auto-register failed: {e}")
                        set_state(
                            progress_msg=bi("자동 등록 실패 — 잠시 후 다시 시도합니다", "Auto-register failed — retrying shortly"),
                            auto_register_error=str(e),
                        )
                    return

                if not mb_id:
                    set_state(
                        progress_pct=max(int(st.get("progress_pct") or 0), 72),
                        progress_msg=(
                            "whick.org 로그인 계정 확인 중…"
                            if attempt < 8
                            else bi("whick.org 로그인 필요 — 같은 Wi-Fi에서 whick.org 로그인 후 이 화면을 새로고침하세요", "Log in to whick.org on the same Wi-Fi, then refresh this screen")
                        ),
                        progress_detail=bi("부팅 전 whick.org 로그인 · 설치 안내 메일 계정과 동일해야 합니다", "Log in to whick.org before boot — use the same account as the install email"),
                    )
                    if attempt % 3 == 0:
                        write_tty_status()
                time.sleep(3)
        finally:
            with _auto_register_lock:
                _auto_register_started = False

    threading.Thread(target=worker, daemon=True).start()

def _install_invite_hw_ready(invite: dict) -> bool:
    """hw-report / access-ready 완료 — portal_only도 포털 안내로 진행 가능."""
    sent = int(invite.get("sent") or 0)
    skipped = str(invite.get("skipped") or "")
    return sent > 0 or skipped in ("already_sent", "portal_only")


def _install_invite_mail_sent(invite: dict) -> bool:
    """실제 설치안내(172 LAN) 이메일이 발송된 경우만."""
    sent = int(invite.get("sent") or 0)
    skipped = str(invite.get("skipped") or "")
    return sent > 0 or skipped == "already_sent"


def _install_invite_progress_body(invite: dict) -> str:
    skipped = str(invite.get("skipped") or "")
    if _install_invite_mail_sent(invite):
        return EMAIL_SENT_BODY
    if skipped == "portal_only":
        return PORTAL_GUIDE_BODY
    return EMAIL_PENDING_BODY


def schedule_hw_report_retry(*, reason: str = "") -> None:
    """link_ok 이후 raw DMI hw-report 백그라운드 재시도."""
    if SKIP_HW_ID:
        return
    global _hw_report_running

    from hw_identity import collect_dmi_raw_for_server, collect_hw_runtime_specs

    with _hw_report_lock:
        if _hw_report_running:
            return
        _hw_report_running = True

    def worker() -> None:
        global _hw_report_running
        try:
            backoff = 8
            while True:
                st = get_state()
                if st.get("hw_report_ok"):
                    return
                if st.get("phase") in ("done", "register_done", "error"):
                    if st.get("phase") == "error" and not st.get("link_ok"):
                        return
                    if st.get("phase") == "error":
                        return
                boot = load_bootstrap_session()
                if not boot or not boot.get("bootstrap_token"):
                    time.sleep(5)
                    continue
                token = boot["bootstrap_token"]
                session_id = boot.get("session_id")
                eth_ip = get_lan_ip()
                lan_url = f"http://{eth_ip}:{PORT}/" if eth_ip else (st.get("lan_url") or "")
                mb_raw, identity_source = collect_dmi_raw_for_server(retries=4, retry_delay_sec=2.0)
                fp = {
                    "hostname": os.uname().nodename,
                    "source": "usb-customer-setup",
                    "kernel": os.uname().release,
                    "motherboard": mb_raw,
                    "identity_source": identity_source,
                    **collect_hw_runtime_specs(),
                }
                if lan_url.startswith("http"):
                    fp["lan_url"] = lan_url
                    fp["access_mode"] = "lan"
                try:
                    hr = report_hw_fingerprint(token, session_id=session_id, fingerprint=fp)
                    hw_hash = hr.get("hw_id_hash") or hr.get("hw_id_hash_server") or ""
                    invite = hr.get("phone_invite") or {}
                    mail_ok = _install_invite_hw_ready(invite)
                    set_state(
                        hw_report_ok=True,
                        hw_id_hash=hw_hash,
                        connect_last_hw_error="",
                    )
                    if boot.get("hw_id_hash") != hw_hash and hw_hash:
                        boot["hw_id_hash"] = hw_hash
                        try:
                            BOOTSTRAP_PATH.write_text(json.dumps(boot, ensure_ascii=False, indent=2))
                            os.chmod(BOOTSTRAP_PATH, 0o600)
                        except OSError:
                            pass
                    if mail_ok:
                        stop_install_login_poll(source="hw-report-retry")
                    log(f"hw-report retry ok hash={hw_hash[:12]}… reason={reason or 'bg'}")
                    return
                except Exception as e:
                    set_state(connect_last_hw_error=str(e))
                    log(f"hw-report retry failed: {e}")
                time.sleep(backoff)
                backoff = min(60, backoff + 8)
        finally:
            with _hw_report_lock:
                _hw_report_running = False

    threading.Thread(target=worker, daemon=True).start()


def stop_install_login_poll(*, source: str = "") -> None:
    """설치 안내 메일 발송 완료 — access-invite 재시도·로그인 IP 감시 중단."""
    global _access_invite_sent, _access_invite_poll_active
    with _access_invite_lock:
        if _access_invite_sent:
            return
        _access_invite_sent = True
        _access_invite_poll_active = False
    set_state(install_mail_sent=True)
    if source:
        log(f"install login poll stopped ({source})")


def schedule_access_invite_to_cc() -> None:
    """CC 세션 확인 + LAN URL → 고객 이메일. whick.org 로그인 늦어도 주기 재시도."""
    global _access_invite_poll_active

    with _access_invite_lock:
        if _access_invite_sent:
            return
        if _access_invite_poll_active:
            return
        _access_invite_poll_active = True

    def worker() -> None:
        global _access_invite_poll_active
        attempt = 0
        try:
            while True:
                st = get_state()
                if st.get("phase") in ("register_done", "done", "error"):
                    return
                with _access_invite_lock:
                    if _access_invite_sent:
                        return

                boot = load_bootstrap_session()
                token = ""
                session_id = st.get("session_id")
                with _lock:
                    token = _state.get("bootstrap_token") or ""
                if boot:
                    if not session_id:
                        session_id = boot.get("session_id")
                    if not token:
                        token = boot.get("bootstrap_token", "")
                if not token or not session_id:
                    time.sleep(2 if attempt else 0.5)
                    attempt += 1
                    continue

                lan = (st.get("lan_url") or st.get("phone_login_url") or "").strip()
                lan_ip = get_lan_ip()
                if not lan.startswith("http://") and lan_ip:
                    lan = f"http://{lan_ip}:{PORT}/"
                    set_state(lan_url=lan, setup_mode="lan")

                if not lan.startswith("http://"):
                    time.sleep(2 if attempt else 0.5)
                    attempt += 1
                    continue

                device_code = st.get("device_code") or (boot.get("device_code", "") if boot else "")
                try:
                    result = report_access_ready(
                        token,
                        int(session_id),
                        access_mode="lan",
                        ap_ok=False,
                        ap_ssid="",
                        device_code=device_code,
                        captive_url="",
                        lan_url=lan,
                    )
                    invite = result.get("phone_invite") or {}
                    if _install_invite_hw_ready(invite):
                        stop_install_login_poll(source="lan-invite-sent")
                        phase_now = get_state().get("phase") or ""
                        guide_body = _install_invite_progress_body(invite)
                        invite_updates: dict = {
                            "progress_detail": lan,
                            "progress_msg": guide_body,
                            "phone_alert_title": INSTALL_PUSH_TITLE,
                            "phone_alert_body": guide_body,
                        }
                        if phase_now not in (
                            "register_needed",
                            "register_done",
                            "done",
                            "error",
                            "connecting",
                            "wifi_needed",
                            "wifi_connecting",
                        ):
                            invite_updates["phase"] = "await_phone"
                        set_state(**invite_updates)
                        write_tty_status(force=True)
                        log(
                            f"CC email invite lan sent={invite.get('sent')} "
                            f"skipped={invite.get('skipped')}"
                        )
                        return
                    log(
                        f"install invite pending (whick.org login?) sent={invite.get('sent')} "
                        f"skipped={invite.get('skipped')} — retry in 8s"
                    )
                except Exception as e:
                    log(f"access invite CC error (attempt {attempt}): {e}")
                attempt += 1
                with _access_invite_lock:
                    if _access_invite_sent:
                        return
                time.sleep(8)
        finally:
            with _access_invite_lock:
                _access_invite_poll_active = False

    threading.Thread(target=worker, daemon=True).start()

def log(msg: str) -> None:
    line = f"[setup] {msg}\n"
    sys.stderr.write(line)
    try:
        with LOG.open("a") as f:
            f.write(line)
    except OSError:
        pass


def read_net_profile() -> str:
    # Live ISO start.sh exports WHICK_USB_PROFILE; older path used WHICK_NET_PROFILE.
    for key in ("WHICK_NET_PROFILE", "WHICK_USB_PROFILE"):
        env = os.environ.get(key, "").strip().lower()
        if env in ("wired", "wireless", "full"):
            return env
    for path in (
        *NET_PROFILE_PATHS,
        Path("/etc/whick/net-profile"),
    ):
        if not path.is_file():
            continue
        try:
            prof = path.read_text(encoding="utf-8").strip().lower()
        except OSError:
            continue
        if prof in ("wired", "wireless", "full"):
            return prof
    return "full"


def is_wired_usb_profile() -> bool:
    return read_net_profile() == "wired"


def is_wireless_usb_profile() -> bool:
    return read_net_profile() == "wireless"


def eth_path_enabled() -> bool:
    """USB-LAN·유선 eth — wired/full만. wireless USB는 처음부터 Wi-Fi 전용."""
    return not is_wireless_usb_profile()


def customer_portal_profile() -> bool:
    """유선·무선 USB — 설치 안내는 장비 LAN이 아닌 whick.org 개인 포털."""
    return is_wired_usb_profile() or is_wireless_usb_profile()


def resolve_customer_portal_url() -> str:
    st = get_state()
    mb = str(st.get("mb_id") or st.get("member_no") or "").strip()
    if not mb:
        prov = load_provision() or {}
        mb = str(prov.get("mb_id") or "").strip()
    if not mb:
        return ""
    return f"{WHICK_SITE_BASE}/page/{quote(mb, safe='')}"


def customer_install_guide_url(*, fallback_lan: str = "") -> str:
    if customer_portal_profile():
        portal = resolve_customer_portal_url()
        if portal:
            return portal
    return (fallback_lan or "").strip()


def apply_customer_install_guide_url(*, fallback_lan: str = "", reason: str = "lan_ready") -> str:
    """유선·무선 USB — phone_login_url·알림을 개인 설치 포털로 고정."""
    guide = customer_install_guide_url(fallback_lan=fallback_lan)
    if guide:
        if guide != fallback_lan:
            set_state(install_portal_url=guide)
        notify_phone_login(guide, reason=reason)
        return guide
    if fallback_lan:
        notify_phone_login(fallback_lan, reason=reason)
    return fallback_lan


def load_provision() -> dict | None:
    for path in PROVISION_PATHS:
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(data, dict):
            return data
    return None


def ensure_wifi_sta_tools() -> None:
    """Ubuntu Live squashfs 에 wpasupplicant 가 없음 → ISO pool deb 로 설치.

    무선 Live 는 overlay remaster 만 해서 wpa/iw 가 rootfs 에 안 들어간다.
    pool/main/w/wpa + libpcsclite 는 ISO 에 있으므로 부팅 직후 dpkg -i.
    """
    if shutil.which("wpa_supplicant") and shutil.which("wpa_passphrase"):
        return
    media_roots: list[Path] = []
    for p in (
        Path("/cdrom"),
        Path("/mnt/whick-media"),
        Path("/run/live/medium"),
        Path("/media/cdrom"),
    ):
        if p.is_dir():
            media_roots.append(p)
    # by-label mount 시도 (아직 안 올라온 경우)
    for label in ("WHICK_OS_wireless", "WHICK_OS_WIRELESS", "WHICK_OS_wired"):
        dev = Path(f"/dev/disk/by-label/{label}")
        if not dev.exists():
            continue
        mnt = Path("/mnt/whick-media")
        mnt.mkdir(parents=True, exist_ok=True)
        run(["mount", "-o", "ro", str(dev), str(mnt)], check=False)
        if mnt.is_dir():
            media_roots.append(mnt)
        break
    debs: list[str] = []
    for root in media_roots:
        pcs = sorted(root.glob("pool/main/p/pcsc-lite/libpcsclite1_*.deb"))
        wpa = sorted(root.glob("pool/main/w/wpa/wpasupplicant_*.deb"))
        iw = sorted(root.glob("pool/main/i/iw/iw_*.deb"))
        nl3 = sorted(root.glob("pool/main/libn/libnl3/libnl-3-200_*.deb"))
        nlgenl = sorted(root.glob("pool/main/libn/libnl3/libnl-genl-3-200_*.deb"))
        nlroute = sorted(root.glob("pool/main/libn/libnl3/libnl-route-3-200_*.deb"))
        # overlay 동봉(선택)
        overlay = list((root / "whick-os" / "debs").glob("*.deb")) if (root / "whick-os" / "debs").is_dir() else []
        if pcs or wpa or iw or nl3 or overlay:
            debs = [str(p) for p in pcs + wpa + iw + nl3 + nlgenl + nlroute + overlay]
            break
    if not debs:
        raise RuntimeError("Wi-Fi tools missing (wpa_supplicant) and ISO pool debs not found")
    # SSD deploy 가 ISO remount 실패해도 쓰도록 Live 호스트에 캐시
    try:
        cache = Path("/var/tmp/whick-wifi-debs")
        cache.mkdir(parents=True, exist_ok=True)
        for src in debs:
            shutil.copy2(src, cache / Path(src).name)
    except OSError as e:
        log(f"WARN: could not cache Wi-Fi debs: {e}")
    log(f"installing Wi-Fi STA tools from ISO pool: {len(debs)} debs")
    r = run(["dpkg", "-i", *debs], check=False)
    if r.returncode != 0:
        # 의존 깨짐 시 한 번 더 시도(순서)
        run(["dpkg", "--configure", "-a"], check=False)
        r2 = run(["dpkg", "-i", *debs], check=False)
        if r2.returncode != 0:
            err = (r2.stderr or r.stderr or r2.stdout or r.stdout or "").strip()[:200]
            raise RuntimeError(f"Wi-Fi tools install failed: {err}")
    if not shutil.which("wpa_supplicant") or not shutil.which("wpa_passphrase"):
        raise RuntimeError("wpa_supplicant still missing after dpkg -i")
    log("Wi-Fi STA tools ready (wpa_supplicant)")


def provision_wifi_credentials() -> tuple[str, str]:
    ssid = os.environ.get("WHICK_PROVISION_WIFI_SSID", "").strip()
    pwd = os.environ.get("WHICK_PROVISION_WIFI_PASSWORD", "")
    prov = load_provision()
    if prov:
        ssid = ssid or str(prov.get("wifi_ssid") or "").strip()
        pwd = pwd or str(prov.get("wifi_password") or "")
    return ssid, pwd


def init_provision_bootstrap() -> None:
    """VIP 맞춤 USB — bootstrap 세션 + member 힌트."""
    boot = load_bootstrap_session()
    if boot:
        apply_bootstrap_session(boot)
    prov = load_provision()
    if not prov:
        return
    mb = str(prov.get("mb_id") or "").strip()
    if mb:
        set_state(member_no=mb, mb_id=mb)
    portal = resolve_customer_portal_url()
    if portal and customer_portal_profile():
        set_state(install_portal_url=portal)
    if boot:
        return
    token = str(prov.get("bootstrap_token") or "").strip()
    sid = prov.get("session_id")
    code = str(prov.get("device_code") or "")
    if token and sid:
        apply_bootstrap_session(
            {
                "session_id": sid,
                "device_code": code,
                "bootstrap_token": token,
            }
        )

def wpa_quote_ssid(ssid: str) -> str:
    return ssid.replace("\\", "\\\\").replace('"', '\\"')


def write_wpa_config(path: Path, ssid: str, password: str) -> None:
    ctrl = "ctrl_interface=/var/run/wpa_supplicant\nupdate_config=1\n"
    Path("/var/run/wpa_supplicant").mkdir(parents=True, exist_ok=True)
    if password:
        r = run(["wpa_passphrase", ssid, password])
        if r.returncode != 0:
            raise RuntimeError("Wi-Fi config error (wpa_passphrase)")
        body = r.stdout or ""
        if "ctrl_interface=" not in body:
            body = ctrl + body
        path.write_text(body)
    else:
        q = wpa_quote_ssid(ssid)
        path.write_text(
            f'{ctrl}network={{\n\tssid="{q}"\n\tkey_mgmt=NONE\n}}\n'
        )
    path.chmod(0o600)

def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    """Live 미니멀 rootfs — rfkill/iw/killall 등 바이너리 없으면 FileNotFoundError.

    check=False 이면 127 로 CompletedProcess 반환 (연결 흐름이 죽지 않게).
    """
    try:
        return subprocess.run(cmd, capture_output=True, text=True, **kw)
    except FileNotFoundError as e:
        if kw.get("check"):
            raise
        return subprocess.CompletedProcess(list(cmd), 127, "", str(e))


def save_state() -> None:
    with _lock:
        payload = {k: v for k, v in _state.items() if k != "bootstrap_token"}
    STATE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    try:
        os.chmod(STATE_PATH, 0o600)
    except OSError:
        pass


def set_state(**kw) -> None:
    with _lock:
        if "phase" in kw and kw["phase"] != _state.get("phase"):
            seed = kw.get("phase_progress_pct", kw.get("progress_pct", 0))
            kw.setdefault("display_phase_pct", int(seed or 0))
        if "phase_progress_pct" in kw and kw["phase_progress_pct"] is not None:
            target = int(kw["phase_progress_pct"])
            disp = _state.get("display_phase_pct")
            if disp is None or int(disp) > target:
                kw["display_phase_pct"] = target
            elif int(disp) < target:
                _ensure_phase_display_ticker()
        _state.update(kw)
        save_state()


def set_install_error(raw: str = "", data: dict | None = None, code: str = "") -> None:
    payload = dict(data or {})
    payload.setdefault("net_profile", read_net_profile())
    guide = guide_by_code(code) if code else None
    if not guide:
        guide = classify_install_error(raw, payload)
    raw_s = str(raw or "").strip()
    raw_ascii = "".join(ch for ch in raw_s if ord(ch) < 128).strip()[:160]
    set_state(
        phase="error",
        error=guide["error_message"],
        error_code=guide["error_code"],
        error_title=guide["error_title"],
        error_steps=guide["error_steps"],
        progress_msg=guide["error_title"],
        install_error_detail=raw_ascii or raw_s[:160],
        connect_last_error=raw_ascii or "",
    )
    kick_error_auto_retry("install_error")
    write_tty_status(force=True)


def kick_error_auto_retry(reason: str = "") -> None:
    """error 상태 — WAN 되면 boot-connect 자동 재시도 (무한)."""
    global _error_auto_retry_running
    with _error_auto_retry_lock:
        if _error_auto_retry_running:
            return
        _error_auto_retry_running = True
    threading.Thread(target=_error_auto_retry_worker, args=(reason,), daemon=True).start()


def _error_auto_retry_worker(reason: str = "") -> None:
    global _error_auto_retry_running
    try:
        backoff = 5
        while True:
            st = get_state()
            phase = st.get("phase")
            if phase in ("done", "register_done"):
                return
            if phase != "error":
                time.sleep(3)
                continue
            if not _retriable_install_error():
                return
            if not has_wan():
                time.sleep(5)
                continue
            if is_wireless_usb_profile():
                if not st.get("home_ssid") and not get_wifi_sta_ip():
                    time.sleep(5)
                    continue
            elif not eth_has_link() and not st.get("home_ssid"):
                time.sleep(5)
                continue
            log(f"auto retry Whick connect ({reason or 'error'})")
            retry_install()
            for _ in range(90):
                p = get_state().get("phase")
                if p in ("await_phone", "register_needed", "register_done", "done", "lan_setup"):
                    return
                if p == "error":
                    break
                time.sleep(2)
            time.sleep(backoff)
            backoff = min(45, backoff + 5)
    finally:
        with _error_auto_retry_lock:
            _error_auto_retry_running = False


def get_state() -> dict:
    with _lock:
        st = dict(_state)
        st.pop("bootstrap_token", None)
        return st


_phase_ticker_started = False
_phase_ticker_lock = threading.Lock()


def _ensure_phase_display_ticker() -> None:
    global _phase_ticker_started
    with _phase_ticker_lock:
        if _phase_ticker_started:
            return
        _phase_ticker_started = True
    threading.Thread(target=_phase_display_ticker, daemon=True).start()


def _phase_display_ticker() -> None:
    """단계 내 0–100% — 2초마다 1%씩 목표치까지 (CC·쉘 점프 보간)."""
    tick_sec = float(os.environ.get("WHICK_PHASE_TICK_SEC", "2"))
    while True:
        time.sleep(tick_sec)
        changed = False
        with _lock:
            target = _state.get("phase_progress_pct")
            if target is None:
                continue
            target = int(target)
            display = int(
                _state.get("display_phase_pct")
                if _state.get("display_phase_pct") is not None
                else target
            )
            if display < target:
                _state["display_phase_pct"] = display + 1
                changed = True
            elif display > target:
                _state["display_phase_pct"] = target
                changed = True
        if changed:
            write_tty_status()


def _resolve_display_phase_pct(st: dict) -> int:
    if st.get("display_phase_pct") is not None:
        return int(st["display_phase_pct"])
    if st.get("phase_progress_pct") is not None:
        return int(st["phase_progress_pct"])
    return int(st.get("progress_pct") or 0)


def session_ready() -> bool:
    boot = load_bootstrap_session()
    if boot and boot.get("bootstrap_token") and boot.get("session_id"):
        return True
    with _lock:
        return bool(_state.get("bootstrap_token") and _state.get("session_id"))


def load_bootstrap_session() -> dict | None:
    """맞춤 USB: ISO/미디어의 whick-bootstrap-session.json 도 인정 (/tmp 만 보면 DIY 세션 재생성됨)."""
    for path in BOOTSTRAP_SESSION_PATHS:
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        token = data.get("bootstrap_token")
        if not token:
            continue
        if path.resolve() != BOOTSTRAP_PATH.resolve():
            try:
                BOOTSTRAP_PATH.parent.mkdir(parents=True, exist_ok=True)
                BOOTSTRAP_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                os.chmod(BOOTSTRAP_PATH, 0o600)
                log(f"bootstrap session seeded from {path} → {BOOTSTRAP_PATH} code={data.get('device_code')}")
            except OSError as e:
                log(f"bootstrap seed copy failed: {e}")
        return data
    return None


def apply_bootstrap_session(data: dict) -> None:
    set_state(
        session_id=data.get("session_id"),
        device_code=data.get("device_code", ""),
        hw_id_hash=data.get("hw_id_hash", ""),
        bootstrap_token=data.get("bootstrap_token", ""),
    )


def has_wan() -> bool:
    return run(["ping", "-c1", "-W2", "8.8.8.8"]).returncode == 0


def can_poll_cc() -> bool:
    """인터넷 또는 CC API — session/me·원격 설치 명령 pull."""
    return has_wan() or cc_health_ok()


def find_wifi_once() -> str:
    for p in Path("/sys/class/net").iterdir():
        if (p / "wireless").is_dir():
            return p.name
    return ""


def wait_for_wifi(max_sec: int = 60) -> str:
    """Wi-Fi 칩·드라이버 늦게 올라오는 USB/내장 무선 대기."""
    deadline = time.time() + max_sec
    while time.time() < deadline:
        ensure_kernel_modules()
        w = find_wifi_once()
        if w:
            return w
        time.sleep(2)
    return ""


def find_wifi() -> str:
    return find_wifi_once()


def iface_ipv4(name: str) -> str:
    r = run(["ip", "-4", "-o", "addr", "show", name])
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[2] == "inet":
            return parts[3].split("/")[0]
    return ""


def get_eth_ip() -> str:
    for p in Path("/sys/class/net").iterdir():
        name = p.name
        if name == "lo" or (p / "wireless").is_dir():
            continue
        ip = iface_ipv4(name)
        if ip:
            return ip
    return ""


def get_wifi_sta_ip() -> str:
    """공유기 Wi-Fi(STA) IP."""
    wifi = WIFI_IF or find_wifi_once()
    if not wifi:
        return ""
    return iface_ipv4(wifi)


def get_lan_ip() -> str:
    """고객 LAN URL — wireless USB는 Wi-Fi STA만, wired/full은 유선 우선."""
    if is_wireless_usb_profile():
        return get_wifi_sta_ip()
    return get_eth_ip() or get_wifi_sta_ip()

def list_eth_ifaces() -> list[str]:
    names: list[str] = []
    for p in Path("/sys/class/net").iterdir():
        name = p.name
        if name == "lo" or (p / "wireless").is_dir():
            continue
        names.append(name)
    return sorted(names)


def iface_bus_label(name: str) -> str:
    dev = Path(f"/sys/class/net/{name}/device")
    if not dev.exists():
        return "?"
    try:
        rp = str(dev.resolve())
    except OSError:
        return "?"
    if "/usb" in rp:
        return "USB"
    if "/pci" in rp:
        return "PCI"
    return "LAN"


def usb_eth_diag_lines() -> list[str]:
    """lsusb — USB-LAN dongle seen but no netdev yet."""
    r = run(["lsusb"], check=False, timeout=5)
    if r.returncode != 0 or not r.stdout.strip():
        return []
    lines: list[str] = []
    has_usb_nic = False
    for ln in r.stdout.splitlines():
        low = ln.lower()
        if any(
            tok in low
            for tok in (
                "asix",
                "0b95:1790",
                "0b95:772b",
                "realtek",
                "0bda:8152",
                "0bda:8153",
                "0fe6:9900",
                "lan",
                "ethernet",
                "network",
            )
        ):
            has_usb_nic = True
            lines.append(f"  usb: {ln.strip()}")
    if not has_usb_nic:
        return []
    if any(iface_bus_label(n) == "USB" for n in list_eth_ifaces()):
        return []
    lines.append("  usb: adapter detected — loading driver (ASIX/Realtek USB-LAN)…")
    return lines


def eth_carrier(name: str) -> bool:
    try:
        return Path(f"/sys/class/net/{name}/carrier").read_text().strip() == "1"
    except OSError:
        return False


def eth_has_link() -> bool:
    eths = list_eth_ifaces()
    return bool(eths) and any(eth_carrier(n) for n in eths)


def tty_instruction_lines() -> list[str]:
    """TTY — 유선/무선 상태별 안내 (한글 위 · 영어 아래)."""
    st = get_state()

    def lines(*pairs: tuple[str, str]) -> list[str]:
        out: list[str] = []
        for ko, en in pairs:
            out.append(f"  {ko}")
            out.append(f"  {en}")
        return out

    if is_wireless_usb_profile():
        ssid = str(st.get("home_ssid") or provision_wifi_credentials()[0] or "").strip()
        portal = resolve_customer_portal_url()
        if portal and has_wan():
            return lines(
                ("1) 같은 Wi-Fi에서 whick.org 로그인", "1) Log in at whick.org (same Wi-Fi)"),
                (f"2) 설치 주소: {portal}", f"2) Install portal: {portal}"),
            )
        if ssid:
            return lines(
                (f"1) 무선 USB — «{ssid}» 연결 중", f"1) Wireless USB — connecting to «{ssid}»"),
                ("2) 인터넷 연결 대기 중…", "2) Waiting for internet…"),
            )
        return lines(
            ("1) 무선 USB — provision.json Wi-Fi 필요", "1) Wireless USB — provision.json Wi-Fi required"),
            ("2) 다운로드에서 무선 맞춤 USB zip", "2) Downloads page — wireless custom USB zip"),
        )

    ip = get_eth_ip()

    if ip and has_wan():
        portal = customer_install_guide_url(fallback_lan=f"http://{ip}:{PORT}/")
        if portal.startswith(WHICK_SITE_BASE):
            line2 = (f"2) 설치 주소: {portal}", f"2) Install portal: {portal}")
        else:
            line2 = (f"2) 스마트폰 브라우저: {portal}", f"2) Phone browser: {portal}")
        return lines(
            ("1) 같은 Wi-Fi에서 whick.org 로그인", "1) Log in at whick.org (same Wi-Fi)"),
            line2,
        )
    if eth_has_link() and ip:
        return lines(
            ("1) 유선 연결됨 — 인터넷 확인 중…", "1) Wired connected — checking internet…"),
            (f"2) 스마트폰: http://{ip}/ (같은 네트워크)", f"2) Phone browser: http://{ip}/ (same network)"),
        )
    if eth_has_link():
        return lines(
            ("1) 유선 케이블 감지 — IP 대기", "1) Wired cable detected — waiting for IP"),
            ("2) 같은 Wi-Fi 폰: 설치 주소가 나오면 여세요", "2) Same Wi-Fi phone: open install URL when shown"),
        )
    if is_wired_usb_profile():
        return lines(
            ("1) 공유기 LAN을 USB-LAN 또는 내장 포트에 연결", "1) Connect router LAN to USB-LAN adapter or built-in port"),
            ("2) 유선 링크·IP 대기 중…", "2) Waiting for any wired link and IP…"),
        )
    return lines(
        ("1) 공유기 LAN을 USB-LAN 또는 내장 포트에 연결", "1) Connect router LAN to USB-LAN adapter or built-in port"),
        ("2) 유선 링크·IP 대기 중…", "2) Waiting for wired link and IP…"),
        ("3) 폰: 같은 Wi-Fi에서 LAN/설치 주소 열기", "3) Phone: same Wi-Fi — open LAN URL or whick.org portal when shown"),
    )


def eth_status_lines() -> list[str]:
    if is_wireless_usb_profile():
        lines: list[str] = []
        wifi = WIFI_IF or find_wifi_once()
        ssid = str(get_state().get("home_ssid") or provision_wifi_credentials()[0] or "").strip()
        if ssid:
            lines.append(f"  wifi STA: target «{ssid}»")
        elif wifi:
            lines.append(f"  wifi {wifi}: waiting for provision Wi-Fi…")
        else:
            lines.append("  wifi: waiting for wireless chip/driver…")
        sta = get_wifi_sta_ip()
        if sta:
            net = "internet OK" if has_wan() else "no internet — check router WAN/modem"
            lines.append(f"  wifi STA: IP {sta}, {net}")
        portal = resolve_customer_portal_url()
        if portal and has_wan():
            lines.append(f"  portal: {portal}")
        return lines

    lines: list[str] = []
    any_link = False
    any_ip = False
    for name in list_eth_ifaces():
        ip = iface_ipv4(name)
        carrier = eth_carrier(name)
        bus = iface_bus_label(name)
        if carrier:
            any_link = True
        if ip:
            any_ip = True
        if ip:
            net = "internet OK" if has_wan() else "no internet — check router WAN/modem"
            lines.append(f"  eth {name} ({bus}): IP {ip}, {net}")
        elif carrier:
            lines.append(f"  eth {name} ({bus}): link up, waiting for IP (router DHCP)...")
        elif is_wired_usb_profile():
            lines.append(f"  eth {name} ({bus}): no link — check cable and router port")
        else:
            lines.append(f"  eth {name} ({bus}): no link — plug cable to router LAN")
    if not lines:
        lines.append("  eth: no wired port yet — plug USB-LAN or built-in LAN cable")
        if not Path("/sys/class/net").exists() or len(list(Path("/sys/class/net").iterdir())) <= 1:
            lines.append("  tip: kernel modules may be missing (see boot: kernel modules OK?)")
    elif any_link and not any_ip:
        lines.append("  tip: switch/hub needs uplink to router LAN (DHCP comes from router)")
    elif any_ip and not has_wan():
        lines.append("  tip: local IP OK — fix router internet, then reboot or wait")
    if is_wired_usb_profile() or not is_wireless_usb_profile():
        lines.extend(usb_eth_diag_lines())
    return lines


def ensure_kernel_modules() -> None:
    """modloop + 유선/Wi-Fi 드라이버 (local.d 이후 재시도)."""
    if os.environ.get("WHICK_KERNEL_MODULES_DONE") == "1":
        if is_wired_usb_profile() or find_wifi_once():
            return
    sh = ROOT / "whick-kernel-modules.sh"
    if not sh.is_file():
        return
    run(
        [
            "sh",
            "-c",
            f". '{sh}' && whick_ensure_modloop && whick_load_net_modules",
        ],
        check=False,
        timeout=90,
    )
    if is_wired_usb_profile() or find_wifi_once():
        os.environ["WHICK_KERNEL_MODULES_DONE"] = "1"


def request_dhcp_on_iface(name: str, *, tries: int = 10) -> None:
    """USB Live DHCP: dhclient/dhcpcd/networkctl (legacy udhcpc fallback)."""
    run(["ip", "link", "set", name, "up"], check=False)
    if shutil.which("udhcpc"):
        run(["udhcpc", "-i", name, "-q", "-t", str(tries), "-n"], check=False)
        return
    if shutil.which("dhclient"):
        # -1: exit after first lease attempt; timeout seconds
        run(
            ["dhclient", "-1", "-v", "-timeout", str(max(5, int(tries))), name],
            check=False,
            timeout=max(20, int(tries) + 15),
        )
        return
    if shutil.which("dhcpcd"):
        run(["dhcpcd", "-w", "-t", str(tries), name], check=False, timeout=max(20, int(tries) + 15))
        return
    if shutil.which("networkctl"):
        run(["networkctl", "up", name], check=False)
        run(["networkctl", "renew", name], check=False)
        time.sleep(2)
        return
    log(f"no DHCP client found for {name} (need udhcpc|dhclient|dhcpcd|networkctl)")


def request_eth_dhcp() -> None:
    """유선 링크 올리고 DHCP 요청 (WAN 확인 없음)."""
    for name in list_eth_ifaces():
        run(["ip", "link", "set", name, "up"], check=False)
        if not eth_carrier(name):
            continue
        log(f"DHCP request on {name}")
        request_dhcp_on_iface(name, tries=10)

def prepare_wifi_iface(wifi: str, mode: str = "managed") -> None:
    run(["rfkill", "unblock", "all"], check=False)
    run(["killall", "wpa_supplicant"], check=False)
    # Ubuntu Live NetworkManager 가 wpa_supplicant 와 싸워 STA 실패하는 경우 방지
    if shutil.which("nmcli"):
        run(["nmcli", "device", "set", wifi, "managed", "no"], check=False)
    run(["ip", "addr", "flush", "dev", wifi], check=False)
    run(["ip", "link", "set", wifi, "up"], check=False)
    if shutil.which("iw"):
        run(["iw", "dev", wifi, "set", "type", "managed"], check=False)
    time.sleep(1)


def wpa_iface_state(wifi: str) -> str:
    r = run(["wpa_cli", "-i", wifi, "status"], check=False)
    for line in (r.stdout or "").splitlines():
        if line.startswith("wpa_state="):
            return line.split("=", 1)[1].strip()
    return ""


def wait_wpa_connected(wifi: str, timeout: int = 60) -> None:
    """wpa_supplicant 기동 직후 COMPLETED 까지 대기 (DHCP 선행 방지)."""
    deadline = time.time() + timeout
    state = ""
    handshake_ticks = 0
    empty_ticks = 0
    while time.time() < deadline:
        state = wpa_iface_state(wifi)
        if state == "COMPLETED":
            return
        if not state:
            empty_ticks += 1
            if empty_ticks == 5:
                # ctrl_interface 누락·소켓 미생성 진단
                run(["wpa_cli", "-i", wifi, "ping"], check=False)
            time.sleep(1)
            continue
        empty_ticks = 0
        if state in ("4WAY_HANDSHAKE", "GROUP_HANDSHAKE"):
            handshake_ticks += 1
            if handshake_ticks >= 25:
                raise RuntimeError("Wi-Fi password rejected or AP denied")
        elif state == "DISCONNECTED" and handshake_ticks >= 5:
            raise RuntimeError("Wi-Fi password rejected or AP denied")
        time.sleep(1)
    if not state:
        raise RuntimeError("Wi-Fi associate timeout (wpa_cli state empty — ctrl_interface?)")
    raise RuntimeError(f"Wi-Fi associate timeout (state={state})")


def wifi_ssid_in_scan(wifi: str, ssid: str) -> bool:
    """근처 AP 스캔에 목표 SSID 가 보이는지 (5GHz-only 등 진단)."""
    if not shutil.which("iw"):
        return False
    run(["iw", "dev", wifi, "scan", "trigger"], check=False)
    time.sleep(3)
    r = run(["iw", "dev", wifi, "scan", "dump"], check=False)
    needle = f"SSID: {ssid}"
    return needle in (r.stdout or "")


def bring_up_eth() -> bool:
    request_eth_dhcp()
    if has_wan():
        return True
    time.sleep(1)
    request_eth_dhcp()
    return has_wan()

def connect_wifi_sta(ssid: str, password: str, wifi: str) -> str:
    """집 Wi-Fi STA 연결 (provision.json)."""
    run(["ip", "addr", "flush", "dev", wifi], check=False)
    run(["ip", "link", "set", wifi, "up"], check=False)
    prepare_wifi_iface(wifi, mode="managed")
    if not wifi_ssid_in_scan(wifi, ssid):
        log(f"provision Wi-Fi scan: SSID «{ssid}» not seen (will still try associate)")
    wpa = Path("/tmp/whick-wpa.conf")
    write_wpa_config(wpa, ssid, password)
    run(["killall", "wpa_supplicant"], check=False)
    r = run(["wpa_supplicant", "-B", "-i", wifi, "-c", str(wpa)])
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip()[:120]
        raise RuntimeError(f"Wi-Fi connect failed (wpa_supplicant) {err}".strip())
    wait_wpa_connected(wifi, timeout=60)
    # 핫스팟/공유기: associate 직후 DHCP 한 번에 실패하는 경우가 많음 → 재시도 (TTY error 깜빡임 방지)
    ip = ""
    deadline = time.time() + 90
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        request_dhcp_on_iface(wifi, tries=12)
        time.sleep(2)
        ip = iface_ipv4(wifi)
        if ip:
            log(f"Wi-Fi DHCP OK ip={ip} attempt={attempt}")
            break
        log(f"Wi-Fi DHCP waiting… attempt={attempt}")
        time.sleep(3)
    if not ip:
        raise RuntimeError("Wi-Fi DHCP failed — no IPv4 address")
    if not has_wan():
        # ICMP 차단 핫스팟 대비 — CC health 로도 WAN 판정
        wan_deadline = time.time() + 45
        while time.time() < wan_deadline:
            if has_wan() or can_poll_cc():
                break
            time.sleep(3)
        if not has_wan() and not can_poll_cc():
            raise RuntimeError("Wi-Fi associated but no WAN (ping/CC health failed)")
    return ip

def run_boot_connect() -> None:
    global _boot_connect_running, _connect_started
    with _connect_lock:
        if _boot_connect_running:
            log("boot-connect already running — skip")
            return
        _boot_connect_running = True

    script = ROOT / "whick-boot-connect.sh"
    if not script.is_file():
        with _connect_lock:
            _boot_connect_running = False
            _connect_started = False
        set_install_error("Connection script missing")
        return
    set_state(
        phase="connecting",
        progress_pct=max(15, int(get_state().get("progress_pct") or 0)),
        progress_msg=EMAIL_PENDING_BODY,
        progress_detail="",
    )
    env = os.environ.copy()
    env.setdefault("WHICK_USB_ROOT", os.environ.get("WHICK_USB_ROOT", ""))
    # boot-connect.sh 가 whick-env(SSL·mini PATH) 를 상속 — subprocess 에도 명시 전달
    mini = os.environ.get("WHICK_MINI", "/opt/whick-boot-connect/mini")
    for ca in (
        "/etc/ssl/certs/ca-certificates.crt",
        f"{mini}/etc/ssl/certs/ca-certificates.crt",
    ):
        if os.path.isfile(ca):
            env.setdefault("SSL_CERT_FILE", ca)
            break
    for _ in range(20):
        eth_ip = get_lan_ip()
        if eth_ip:
            env["WHICK_LAN_URL"] = f"http://{eth_ip}:{PORT}/"
            break
        time.sleep(1)
    log_path = Path(os.environ.get("WHICK_CONNECT_LOG", "/tmp/whick-connect.log"))
    try:
        log_fh = open(log_path, "a", encoding="utf-8")
    except OSError:
        log_fh = subprocess.DEVNULL
    try:
        proc = subprocess.Popen(
            [str(script)],
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            env=env,
        )
        set_state(progress_pct=50, progress_msg=bi("Whick 서버와 통신 중…", "Talking to the Whick server…"))
        proc.wait()
    finally:
        if log_fh not in (None, subprocess.DEVNULL):
            log_fh.close()
        with _connect_lock:
            _boot_connect_running = False

    result_path = Path(os.environ.get("WHICK_CONNECT_RESULT", "/tmp/whick-connect-result.json"))
    try:
        data = json.loads(result_path.read_text()) if result_path.is_file() else {}
    except json.JSONDecodeError:
        data = {}
    if not data.get("error"):
        diag_fill = load_boot_connect_diagnostics()
        if diag_fill.get("error"):
            data["error"] = diag_fill["error"]
        if diag_fill.get("error_code") and not data.get("error_code"):
            data["error_code"] = diag_fill["error_code"]
    diag = load_boot_connect_diagnostics()
    set_state(
        connect_last_rc=proc.returncode,
        connect_last_error=data.get("error") or "",
        connect_last_error_code=data.get("error_code") or "",
        connect_last_device_code=data.get("device_code") or "",
        connect_last_hw_error=data.get("hw_report_error") or "",
        connect_log_tail=(diag.get("log_tail") or [])[-4:],
        link_ok=bool(data.get("link_ok")),
        hw_report_ok=bool(data.get("hw_report_ok")),
    )
    boot = load_bootstrap_session()
    has_bootstrap = bool(boot and str(boot.get("bootstrap_token") or "").strip())
    if data.get("link_ok") and not has_bootstrap:
        set_state(
            connect_last_error=data.get("error") or "bootstrap session missing",
            connect_last_error_code=data.get("error_code") or "bootstrap_save",
            link_ok=False,
        )
        set_install_error("Bootstrap session not saved", code="bootstrap_save")
        log("boot-connect link_ok but bootstrap missing — treat as failure")
        write_tty_status()
        return
    linked = has_bootstrap and (
        bool(data.get("link_ok"))
        or (proc.returncode == 0 and bool(data.get("ok") or data.get("link_ok")))
    )
    if linked:
        apply_bootstrap_session(boot)
        if _resume_from_cc_after_link(data, boot):
            eth_ip = get_lan_ip()
            login_url = f"http://{eth_ip}:{PORT}/" if eth_ip else (get_state().get("lan_url") or "")
            if login_url:
                set_state(lan_url=login_url, wan_ok=True, link_ok=True)
            try:
                handle_cc_remote_install()
            except Exception as exc:
                log(f"boot-connect resume remote install: {exc}")
            st = get_state()
            log(f"boot-connect resume session={data.get('device_code')} phase={st.get('phase')}")
            write_tty_status()
            return
        eth_ip = get_lan_ip()
        login_url = f"http://{eth_ip}:{PORT}/" if eth_ip else (get_state().get("lan_url") or "")
        if login_url:
            set_state(lan_url=login_url, setup_mode="lan")
        invite = data.get("phone_invite") or {}
        mail_ok = _install_invite_hw_ready(invite)
        if data.get("hw_report_ok") and mail_ok:
            stop_install_login_poll(source="hw-report")
            log(
                f"install mail via hw-report sent={invite.get('sent')} "
                f"skipped={invite.get('skipped')} — access-invite worker skipped"
            )
        elif data.get("link_ok") and mail_ok:
            stop_install_login_poll(source="link-skip")
            log(f"install mail via link sent={invite.get('sent')} skipped={invite.get('skipped')}")
        else:
            if data.get("link_ok") and invite.get("skipped"):
                log(
                    f"link mail skipped={invite.get('skipped')} hint={invite.get('hint')} "
                    f"— ap-ready worker scheduled"
                )
            schedule_access_invite_to_cc()
            if not data.get("hw_report_ok") and not SKIP_HW_ID:
                schedule_hw_report_retry(reason="boot-connect")
        st = get_state()
        phone_ready = bool(st.get("phone_seen"))
        if login_url:
            apply_customer_install_guide_url(
                fallback_lan=login_url,
                reason="register_ready" if phone_ready else "lan_ready",
            )
        phase = "register_needed" if phone_ready else "await_phone"
        link_msg = bi("Whick 서버 연결됨", "Connected to Whick server")
        if not data.get("hw_report_ok"):
            link_msg = bi("Whick 서버 연결됨 — 장비 정보 전송 중…", "Connected to Whick — sending device info…")
        set_state(
            phase=phase,
            progress_pct=70 if phase == "register_needed" else (55 if data.get("hw_report_ok") else 45),
            progress_msg=(
                bi("Whick 연결 완료 — 장비 등록을 자동으로 진행합니다", "Whick connected — registering the device automatically")
                if phase == "register_needed"
                else (
                    _install_invite_progress_body(invite)
                    if mail_ok
                    else (
                        link_msg
                        if not data.get("hw_report_ok")
                        else PORTAL_GUIDE_BODY
                    )
                )
            ),
            progress_detail=(
                customer_install_guide_url(fallback_lan=login_url)
                or login_url
                or data.get("device_code", "")
            ),
            device_code=data.get("device_code", ""),
            hw_id_hash=data.get("hw_id_hash", "") or (boot or {}).get("hw_id_hash", ""),
            link_ok=True,
            hw_report_ok=bool(data.get("hw_report_ok")),
            wan_ok=True,
        )
        if phase == "register_needed":
            try_auto_register()
        log(f"CC connected {data.get('device_code')} phase={phase}")
        write_tty_status()
    else:
        err = data.get("error") or bi("Whick 연결 실패", "Whick connection failed")
        with _connect_lock:
            _connect_started = False
        log(f"boot-connect failed rc={proc.returncode} code={data.get('error_code')} err={err}")
        set_install_error(err, data)


def retry_install() -> dict:
    global _connect_started
    st = get_state()
    code = st.get("error_code", "")

    with _connect_lock:
        _connect_started = False

    if code in ("wifi_auth", "wifi_failed", "wifi_provision") or (not has_wan() and st.get("home_ssid")):
        if is_wireless_usb_profile():
            ssid = str(st.get("home_ssid") or provision_wifi_credentials()[0] or "").strip()
            set_state(
                phase="wifi_connecting",
                error="",
                error_code="",
                error_title="",
                error_steps=[],
                setup_mode="lan",
                progress_msg=(bi(f"사전 등록 Wi-Fi «{ssid or '…'}» 재연결 중…", f"Reconnecting to provisioned Wi-Fi «{ssid or '…'}»…") if ssid else PORTAL_GUIDE_BODY),
                progress_pct=max(int(st.get("progress_pct") or 0), 8),
            )
            threading.Thread(target=provision_wifi_connect_worker, daemon=True).start()
            return {"ok": True, "phase": "wifi_connecting"}
        set_state(
            phase="lan_setup",
            error="",
            error_code="",
            error_title="",
            error_steps=[],
            progress_msg=bi("인터넷 연결을 확인한 뒤 다시 시도해 주세요.", "Check your Internet connection, then try again."),
            progress_pct=0,
        )
        return {"ok": True, "phase": "lan_setup"}

    if has_wan():
        set_state(
            phase="connecting",
            error="",
            error_code="",
            error_title="",
            error_steps=[],
            progress_pct=10,
            progress_msg=bi("Whick에 다시 연결하는 중…", "Reconnecting to Whick…"),
            progress_detail="",
        )
        start_connect_once()
        return {"ok": True, "phase": "connecting"}

    if st.get("setup_mode") == "lan":
        set_state(
            phase="lan_setup",
            error="",
            error_code="",
            error_title="",
            error_steps=[],
            progress_msg=bi("인터넷 연결을 확인한 뒤 다시 시도해 주세요.", "Check your Internet connection, then try again."),
        )
        return {"ok": True, "phase": "lan_setup"}

    set_state(
        phase="lan_setup",
        error="",
        error_code="",
        error_title="",
        error_steps=[],
        progress_msg=bi("인터넷 연결을 확인한 뒤 다시 시도해 주세요.", "Check your Internet connection, then try again."),
    )
    return {"ok": True, "phase": "lan_setup"}

def cc_connect_worker() -> None:
    """WAN 확보 즉시 CC(boot-connect) — 유선·Wi-Fi STA 모두."""
    for _ in range(90):
        phase = str(get_state().get("phase") or "")
        if phase in ("done", "error"):
            return
        if phase.startswith("install_") or phase == "register_done":
            if has_wan() and load_bootstrap_session():
                handle_cc_remote_install()
            return
        if _wired_path_settled():
            return
        st = get_state()
        if eth_path_enabled() and eth_has_link():
            request_eth_dhcp()
        ip = get_lan_ip()
        if ip:
            url = f"http://{ip}:{PORT}/"
            if get_state().get("lan_url") != url:
                set_state(lan_url=url, setup_mode="lan")
        if has_wan():
            if is_wireless_usb_profile():
                if get_state().get("home_ssid") or get_wifi_sta_ip():
                    on_wired_ready()
                    return
            else:
                on_wired_ready()
                return
        time.sleep(2)
    log("cc_connect_worker: WAN timeout")


def _already_past_register() -> bool:
    st = get_state()
    phase = str(st.get("phase") or "")
    return bool(st.get("registered")) or phase in (
        "register_done",
        "install_linux",
        "install_docker",
        "install_runtime",
        "done",
    )


def _resume_from_cc_after_link(data: dict, boot: dict | None) -> bool:
    """등록 완료·원격 설치 중 — boot-connect가 await_phone/register로 되돌리지 않음."""
    if data.get("bootstrap_reused"):
        return True
    if _already_past_register():
        return True
    token, _sid = _bootstrap_credentials()
    if not token and boot:
        token = str(boot.get("bootstrap_token") or "")
    if not token:
        return False
    try:
        sess = fetch_install_session(token)
    except Exception as exc:
        log(f"boot-connect resume check: {exc}")
        return _already_past_register()
    cc_phase = str(sess.get("phase") or "")
    return cc_phase in REMOTE_CC_PHASES or cc_phase == "complete"


def start_connect_once() -> None:
    global _connect_started
    with _connect_lock:
        if _connect_started or _boot_connect_running:
            return
        if not has_wan():
            return
        if _already_past_register() and load_bootstrap_session():
            set_state(wan_ok=True)
            handle_cc_remote_install()
            return
        _connect_started = True
    set_state(wan_ok=True)
    threading.Thread(target=run_boot_connect, daemon=True).start()


def on_internet_ready() -> None:
    """인터넷(WAN) 확보 — 유선·무선 공통: boot-connect(1~4) → 등록·설치."""
    on_wired_ready()


def on_wired_ready() -> None:
    """WAN 확보 후 공통 연동 경로 (유선 eth / 무선 provision STA 동일)."""
    if not has_wan():
        return
    st = get_state()
    eth_ip = get_lan_ip()
    lan_url = f"http://{eth_ip}:{PORT}/" if eth_ip else ""
    updates: dict = {
        "wan_ok": True,
    }
    if eth_path_enabled():
        updates["wired_ok"] = True
        updates["setup_mode"] = "lan"
    else:
        updates["setup_mode"] = "lan"
    if lan_url:
        updates["lan_url"] = lan_url
    guide_url = customer_install_guide_url(fallback_lan=lan_url)
    if guide_url:
        updates["install_portal_url"] = guide_url
        updates["progress_detail"] = guide_url
    if st.get("phase") not in (
        "connecting",
        "register_needed",
        "register_done",
        "done",
        "error",
    ):
        updates["progress_msg"] = (
            PORTAL_GUIDE_BODY
            if customer_portal_profile() and guide_url
            else bi("Whick 서버 연결 중… 설치 안내는 이메일로 보냅니다.", "Connecting to Whick… Install guide will be emailed.")
        )
        updates["progress_pct"] = max(int(st.get("progress_pct") or 0), 10)
    set_state(**updates)
    log(f"WAN ok ip={eth_ip} profile={read_net_profile()}")
    if customer_portal_profile() and lan_url:
        apply_customer_install_guide_url(fallback_lan=lan_url, reason="lan_ready")
    start_connect_once()

def _retriable_install_error() -> bool:
    st = get_state()
    if st.get("phase") != "error":
        return False
    code = str(st.get("error_code") or "unknown")
    if code in NON_RETRYABLE_CC_ERROR_CODES:
        return False
    return code in RETRYABLE_CC_ERROR_CODES


def error_recovery_watch() -> None:
    """error 감시 — set_install_error 외에도 error 고착 시 kick."""
    while True:
        if get_state().get("phase") == "error" and _retriable_install_error():
            kick_error_auto_retry("watch")
        time.sleep(8)


def _wired_path_settled() -> bool:
    st = get_state()
    if st.get("wired_ok") or st.get("wan_ok"):
        return True
    return st.get("phase") in ("connecting", "register_needed", "register_done", "done", "error")


def late_wired_watch() -> None:
    """USB-LAN·PCI 유선 — 늦게 연결되어도 WAN 되면 유선 경로 (wireless USB 제외)."""
    if is_wireless_usb_profile():
        return
    tick = 0
    while True:
        phase = get_state().get("phase")
        if phase in ("done", "register_done"):
            return
        if phase == "error":
            if _retriable_install_error() and has_wan():
                kick_error_auto_retry("late_wired")
            time.sleep(15)
            continue
        if _wired_path_settled():
            return
        if tick % 1 == 0:
            ensure_kernel_modules()
        if eth_has_link():
            request_eth_dhcp()
            if has_wan():
                on_wired_ready()
                return
        tick += 1
        time.sleep(5)

def network_worker(
    has_wifi: bool,
    *,
    skip_initial_eth_wait: bool = False,
) -> None:
    """유선 우선 · WAN 대기. 유선/full USB는 eth만. 무선은 STA WAN 대기. AP 없음."""
    time.sleep(0.3)
    ensure_kernel_modules()

    if is_wired_usb_profile():
        tick = 0
        while True:
            st = get_state()
            if st.get("phase") in ("done", "error", "register_done"):
                return
            if _wired_path_settled():
                return
            if tick % 1 == 0:
                ensure_kernel_modules()
            if eth_has_link():
                request_eth_dhcp()
                if has_wan():
                    on_wired_ready()
                    return
            tick += 1
            time.sleep(3)
        return

    if is_wireless_usb_profile():
        tick = 0
        while True:
            st = get_state()
            if st.get("phase") in ("done", "error", "register_done"):
                return
            if _wired_path_settled():
                return
            if tick % 1 == 0:
                ensure_kernel_modules()
            if has_wan() and get_wifi_sta_ip():
                on_internet_ready()
                return
            tick += 1
            time.sleep(3)
        return

    # full profile — wait for eth like wired; never start AP
    if not skip_initial_eth_wait:
        if not eth_has_link():
            log("network_worker: no wired link — waiting for eth (no AP)")
        else:
            for _attempt in range(4):
                st = get_state()
                if st.get("phase") in ("done", "error", "register_done"):
                    return
                request_eth_dhcp()
                if has_wan():
                    if get_state().get("phase") not in (
                        "connecting",
                        "register_needed",
                        "register_done",
                        "done",
                        "error",
                    ):
                        on_wired_ready()
                    return
                time.sleep(2)

    set_state(
        setup_mode="lan",
        phase="lan_setup",
        progress_pct=8,
        progress_msg=bi("유선 LAN 연결 대기 중… (미니PC ↔ 공유기 LAN 포트)", "Waiting for wired LAN… (mini PC ↔ router LAN port)"),
        progress_detail="",
    )
    while True:
        st = get_state()
        if st.get("phase") in (
            "done",
            "error",
            "wifi_connecting",
            "wifi_reconnect",
            "connecting",
            "phone_login_ready",
            "register_needed",
            "register_done",
        ):
            return
        if _wired_path_settled():
            return
        ensure_kernel_modules()
        if eth_has_link():
            request_eth_dhcp()
            if has_wan():
                if get_state().get("phase") not in (
                    "connecting",
                    "register_needed",
                    "register_done",
                    "done",
                    "error",
                ):
                    on_wired_ready()
                return
        elif bring_up_eth() and has_wan():
            if get_state().get("phase") not in (
                "connecting",
                "register_needed",
                "register_done",
                "done",
                "error",
            ):
                on_wired_ready()
            return
        time.sleep(3)


def notify_phone_login(url: str, *, reason: str = "lan_ready") -> None:
    """스마트폰 install.html 폴링·Notification용 알림."""
    url = (url or "").strip()
    if not url:
        return
    with _lock:
        prev = _state.get("phone_login_url") or ""
        alert_id = int(_state.get("phone_alert_id") or 0)
        if reason == "register_ready":
            title = INSTALL_PUSH_TITLE
            body = f"같은 Wi-Fi · {url} — 장비 등록 자동 진행"
            msg = "Whick 연결 완료 — 장비 등록 자동 진행"
        else:
            title = INSTALL_PUSH_TITLE
            body = LAN_PUSH_BODY
            msg = body
        if customer_portal_profile() and url.startswith(WHICK_SITE_BASE):
            msg = PORTAL_GUIDE_BODY
            body = PORTAL_GUIDE_BODY
        bump = reason == "register_ready" or url != prev
        if bump:
            alert_id += 1
        _state.update(
            phone_login_url=url,
            reconnect_url=url,
            phone_alert_id=alert_id,
            phone_alert_title=title,
            phone_alert_body=body,
            lan_url=url if url.startswith("http://") else _state.get("lan_url") or "",
            phone_url_lan=url,
        )
        if bump and reason == "lan_ready" and _state.get("phase") in (
            "welcome",
            "network_scan",
            "",
        ):
            _state["phase"] = "phone_login_ready"
            _state["progress_msg"] = msg
            _state["progress_detail"] = url
        save_state()
    log(f"phone login alert id={alert_id} reason={reason} url={url}")


def publish_lan_url(*, notify: bool = True) -> str:
    """고객 LAN URL — 유선·Wi-Fi STA IP 또는 whick.org 개인 포털."""
    ip = get_lan_ip()
    url = f"http://{ip}:{PORT}/" if ip else ""
    if url:
        set_state(lan_url=url)
    if customer_portal_profile():
        return apply_customer_install_guide_url(fallback_lan=url, reason="lan_ready")
    if url:
        prev = get_state().get("phone_login_url") or ""
        if notify and prev != url:
            notify_phone_login(url, reason="lan_ready")
        return url
    return ""


def early_eth_bootstrap() -> None:
    """유선 IP 확보 — LAN 전용 모드에서 주소 1회 안내 (반복 알림 방지)."""
    lan_announced = False
    for _ in range(60):
        st = get_state()
        eths = list_eth_ifaces()
        if eths and not any(eth_carrier(n) for n in eths) and not get_eth_ip():
            time.sleep(2)
            continue
        if _ % 5 == 0 and not list_eth_ifaces():
            ensure_kernel_modules()
        request_eth_dhcp()
        ip = get_lan_ip()
        if ip and not lan_announced:
            url = publish_lan_url(notify=True)
            if url:
                lan_announced = True
                lan_msg = (
                    bi("Whick 서버 연결 중… 설치 안내는 이메일로 보냅니다.", "Connecting to Whick… Install guide will be emailed.")
                    if has_wan()
                    else "유선 연결됨 — 인터넷 연결을 확인 중…"
                )
                set_state(
                    phase="lan_setup",
                    setup_mode="lan",
                    progress_msg=lan_msg,
                    progress_detail=url,
                )
                log(f"LAN URL ready {url} wan={has_wan()}")
                if has_wan():
                    start_connect_once()
        if lan_announced and has_wan():
            start_connect_once()
            return
        time.sleep(2)


def setup_urls() -> list[str]:
    urls: list[str] = []
    st = get_state()
    lan = st.get("lan_url") or ""
    if lan:
        urls.append(lan)
    portal = (st.get("install_portal_url") or st.get("phone_login_url") or "").strip()
    if portal and portal not in urls:
        urls.append(portal)
    if eth_path_enabled():
        eth = get_eth_ip()
        if eth:
            u = f"http://{eth}:{PORT}/"
            if u not in urls:
                urls.append(u)
    return urls


def _tty_path() -> Path | None:
    """Mini PC console path. None = disabled (phone-only mode)."""
    raw = os.environ.get("WHICK_SETUP_TTY", "/dev/tty1").strip()
    if raw.lower() in ("off", "0", "none"):
        return None
    return Path(raw)


def _tty_write_targets() -> list[Path]:
    """Visible console may be installer VT, not only /dev/tty1 — write both."""
    out: list[Path] = []
    primary = _tty_path()
    if primary is not None:
        out.append(primary)
    for raw in (
        os.environ.get("WHICK_SETUP_TTY_ACTIVE", "").strip(),
        "/dev/console",
    ):
        if not raw or raw.lower() in ("off", "0", "none"):
            continue
        p = Path(raw)
        if p not in out:
            out.append(p)
    # Active VT from kernel (e.g. tty1) when autoinstall holds another view
    try:
        active = Path("/sys/class/tty/tty0/active").read_text(encoding="utf-8").strip()
        if active and active.startswith("tty"):
            p = Path(f"/dev/{active}")
            if p not in out:
                out.append(p)
    except OSError:
        pass
    return out


def tty_write(lines: list[str]) -> None:
    targets = _tty_write_targets()
    if not targets:
        return
    # Clear screen + scrollback (\033[3J) — fbcon keeps history otherwise, so
    # per-second countdown frames stack/duplicate on the physical console.
    payload = "\033[3J\033[2J\033[H" + "\n".join(lines) + "\n"
    raw = payload.encode("utf-8", errors="replace")
    wrote = False
    for tty in targets:
        try:
            with tty.open("wb") as fh:
                fh.write(raw)
            wrote = True
        except OSError:
            continue
    if wrote:
        try:
            Path("/run/whick-tty-handoff").touch()
        except OSError:
            pass
        # Prefer VT1 for physical monitor (autoinstall early may stay on another VT)
        try:
            import subprocess

            subprocess.run(["chvt", "1"], check=False, timeout=2, capture_output=True)
        except Exception:
            pass


def _install_progress_detail(phase: str, pct: int | None, msg: str) -> str:
    p = str(phase or "").strip()
    n = int(pct or 0)
    text = str(msg or "").strip()
    if text:
        return text[:120]
    hint = REMOTE_CC_PHASE_HINTS.get(p)
    if hint:
        return f"{hint[1]} ({n}%)" if n > 0 else hint[1]
    return ""


def _tty_ascii_snip(text: str, n: int = 100) -> str:
    """TTY has no Korean glyphs — keep pure ASCII, or pull ASCII error fragments."""
    s = str(text or "").strip()
    if not s:
        return ""
    if s.isascii():
        return s[:n]
    parts = re.findall(r"[A-Za-z0-9][A-Za-z0-9 ._/:()%+\-]{2,}", s)
    prefer = ("busy", "error", "fail", "mount", "deploy", "ubuntu", "grub", "rescue", "resource")
    for p in parts:
        low = p.lower()
        if any(k in low for k in prefer):
            return p[:n]
    return parts[-1][:n] if parts else ""


def _tty_install_detail(st: dict) -> str:
    detail = _tty_ascii_snip(st.get("progress_detail") or "")
    if detail:
        return detail
    msg = _tty_ascii_snip(st.get("progress_msg") or "")
    if msg:
        return msg
    phase = str(st.get("phase") or "")
    pct = _resolve_display_phase_pct(st)
    labels = {
        "install_linux": "Deploying Ubuntu to SSD",
        "install_docker": "Installing Docker",
        "install_runtime": "Deploying music server runtime",
        "reboot_pending": "Remove USB — reboot pending",
        "register_done": "Starting remote install",
        "failed": "Install failed — see phone portal",
    }
    base = labels.get(phase, "Installing")
    return f"{base} — {pct}%" if pct > 0 else base


def _tty_eth_fingerprint() -> str:
    """케이블 꽂힘(link)·IP만 바뀌어도 TTY가 다시 그려지도록."""
    parts: list[str] = []
    try:
        for name in list_eth_ifaces():
            parts.append(
                f"{name}:{1 if eth_carrier(name) else 0}:{iface_ipv4(name) or ''}"
            )
    except Exception:
        return "err"
    return ",".join(parts) or "none"


def _tty_fingerprint(st: dict) -> str:
    return "|".join(
        [
            str(st.get("phase") or ""),
            str(st.get("device_code") or ""),
            "1" if st.get("phone_seen") else "0",
            get_lan_ip() or "",
            _tty_eth_fingerprint(),
            str(st.get("progress_pct") or ""),
            str(st.get("progress_msg") or "")[:80],
            str(st.get("progress_detail") or "")[:80],
            str(st.get("error_code") or ""),
            str(st.get("connect_last_error_code") or ""),
            str(st.get("connect_last_error") or "")[:80],
            str(st.get("connect_last_rc") or ""),
            ",".join(st.get("connect_log_tail") or []),
            str(st.get("registered") or ""),
        ]
    )


_TTY_ERROR_HINT: dict[str, str] = {
    "network": "No internet on mini PC",
    "server_unreachable": "Cannot reach Whick server (health/DNS/SSL)",
    "server_register": "Whick session or link failed",
    "hw_identity": "Hardware report failed",
    "wifi_provision": "Wi-Fi connect failed — check SSID/password; re-download from Downloads page",
    "wifi_auth": "Wi-Fi password rejected — check SSID/password",
    "wifi_failed": "Wi-Fi connect failed — check signal and password",
    "unknown": "Connect failed — see log lines below",
}


def _tty_error_detail(st: dict, diag: dict) -> str:
    # 구체적 ascii 원인 우선 (generic wifi_provision 힌트가 실제 원인을 가림)
    for key in (
        "install_error_detail",
        "connect_last_error",
        "error_message",
        "error",
    ):
        em = str(st.get(key) or "").strip()
        if em and em.isascii() and em.lower() not in (
            "connect result missing or invalid",
            "wi-fi connect failed — check ssid/password; re-download from downloads page",
        ):
            return em[:120]
    ec = str(
        st.get("error_code")
        or st.get("connect_last_error_code")
        or diag.get("error_code")
        or ""
    ).strip()
    if ec in _TTY_ERROR_HINT:
        return _TTY_ERROR_HINT[ec]
    diag_em = str(diag.get("error") or "").strip()
    if diag_em and diag_em.isascii() and diag_em != "connect result missing or invalid":
        return diag_em[:120]
    raw = str(diag.get("result_raw") or "").strip()
    if raw and raw.isascii():
        return raw[:120]
    tail = diag.get("log_tail") or st.get("connect_log_tail") or []
    for ln in reversed(tail):
        s = str(ln).strip()
        if s and s.isascii():
            return s[:120]
    return "check /tmp/whick-connect.log on mini PC"


def write_tty_status(*, force: bool = False) -> None:
    """Mini PC console — English only (Live TTY may lack Korean font)."""
    global _tty_written_fingerprint
    tty = _tty_path()
    if not tty:
        return
    st = get_state()
    phase = st.get("phase") or ""

    fp = _tty_fingerprint(st)
    if not force and fp == _tty_written_fingerprint:
        return
    _tty_written_fingerprint = fp

    compact_install = phase in TTY_INSTALL_PHASES or str(phase).startswith("install_")
    lines = ["", "  Whick Music Server"]
    if compact_install:
        lines.append("  Remote install in progress — use phone portal for details")
        lines.append("")
    else:
        lines.extend([*tty_instruction_lines(), ""])
    ip = get_lan_ip()
    if (
        not compact_install
        and ip
        and (
            (eth_path_enabled() and eth_has_link())
            or st.get("wan_ok")
            or (is_wireless_usb_profile() and (get_wifi_sta_ip() or st.get("home_ssid")))
            or phase
            in (
                "wifi_reconnect",
                "connecting",
                "register_needed",
                "register_done",
                "install_linux",
                "install_docker",
                "install_runtime",
                "done",
            )
        )
    ):
        portal = resolve_customer_portal_url()
        if customer_portal_profile() and portal:
            lines.append(f"  portal: {portal}")
        elif ip:
            port_suffix = "" if PORT == 80 else f":{PORT}"
            lines.append(f"  http://{ip}{port_suffix}/")
        lines.append("")
    code = st.get("device_code") or ""
    if code:
        lines.append(f"  Device: {code}")
    if phase:
        no_wired = eth_path_enabled() and not eth_has_link()
        phase_label = {
            "booting": "starting",
            "connecting": "connecting to Whick",
            "await_phone": "waiting for phone (no timeout)",
            "lan_setup": "Wi-Fi setup" if is_wireless_usb_profile() else ("Wi-Fi setup (no USB-LAN)" if no_wired else "LAN setup"),
            "wifi_needed": "waiting for phone (no timeout)",
            "wifi_connecting": "connecting to home Wi-Fi",
            "wifi_reconnect": "home Wi-Fi connected — check email on phone",
            "register_needed": "auto registering device",
            "register_done": "registered",
            "install_linux": "Linux (1/3)",
            "install_docker": "Docker (2/3)",
            "install_runtime": "runtime (3/3)",
            "done": "complete — remove USB",
            "reboot_pending": "reboot pending — SSD boot",
            "post_install_verify": "verifying install",
            "error": "error",
        }.get(phase, phase)
        # 카운트다운 중 phase=done 이어도 "지금 제거"와 "재부팅까지 유지"가 동시에 보이지 않게
        done_pm = str(st.get("progress_msg") or "")
        if phase == "done" and (
            "USB 유지" in done_pm
            or "재부팅까지" in done_pm
            or "keep USB" in done_pm.lower()
            or "until reboot" in done_pm.lower()
        ):
            phase_label = "reboot soon — keep USB until reboot starts"
        pct = _resolve_display_phase_pct(st)
        if pct > 0 and (compact_install or str(phase).startswith("install_") or phase in ("reboot_pending", "post_install_verify", "register_done", "register_pending", "hw_analyzed")):
            lines.append(f"  Status: {phase_label} — {pct}%")
            detail = _tty_install_detail(st)
            if detail:
                lines.append(f"  {detail}")
        else:
            lines.append(f"  Status: {phase_label}")
            if phase == "done":
                done_detail = str(st.get("progress_msg") or "").strip()
                if done_detail and done_detail.isascii():
                    lines.append(f"  {done_detail}")
        if phase == "error":
            diag = load_boot_connect_diagnostics()
            ec = str(
                st.get("error_code")
                or st.get("connect_last_error_code")
                or diag.get("error_code")
                or ""
            ).strip()
            em = _tty_error_detail(st, diag)
            rc = st.get("connect_last_rc")
            lines.append(f"  Error: {ec or 'connect_failed'}")
            lines.append(f"  Detail: {em}")
            hw_e = str(st.get("connect_last_hw_error") or diag.get("hw_report_error") or "").strip()
            if hw_e:
                hw_show = hw_e[:100] if hw_e.isascii() else "hw-report failed"
                lines.append(f"  HW: {hw_show}")
            if rc is not None and rc != 0:
                lines.append(f"  Exit: {rc}")
            shown: set[str] = set()
            for ln in (st.get("connect_log_tail") or []) + (diag.get("log_tail") or []):
                s = str(ln).strip()
                if not s or s in shown:
                    continue
                shown.add(s)
                show = s[:100] if s.isascii() else s.encode("ascii", "replace").decode()[:100]
                lines.append(f"  log: {show}")
            if not shown:
                lines.append("  log: (empty — boot-connect may not have started)")
            if has_wan() and _retriable_install_error():
                lines.append("  Retry: auto (WAN OK)")
            elif has_wan():
                lines.append("  Retry: tap phone UI")
            else:
                lines.append("  Retry: need internet")
    if code or phase:
        lines.append("")
    for ln in eth_status_lines():
        lines.append(ln)
    lines.append(f"  Build: {WHICK_BUILD}")
    if WHICK_VERSION:
        lines.append(f"  Version: {WHICK_VERSION}")
    lines.append("")
    tty_write(lines)


def tty_status_loop() -> None:
    """TTY 갱신 — 원격 설치(register_done~install_*) 구간까지 유지."""
    if not _tty_path():
        return
    write_tty_status(force=True)
    while True:
        try:
            st = get_state()
            phase = st.get("phase") or ""
            if phase == "done":
                write_tty_status(force=True)
                return
            if phase in ("register_done",) or str(phase).startswith("install_"):
                handle_cc_remote_install()
                write_tty_status()
                time.sleep(_cc_remote_poll_interval())
                continue
            if phase == "error":
                write_tty_status(force=True)
                time.sleep(20)
                continue
            write_tty_status()
            # lan/boot 구간은 케이블·DHCP 변화를 빨리 반영 (20s면 'Setup server'에 고착된 것처럼 보임)
            time.sleep(2 if phase in ("booting", "lan_setup", "await_phone", "welcome") else 5)
            continue
        except Exception as e:
            log(f"tty status: {e}")
        time.sleep(5)


def run_http_server() -> None:
    def serve(port: int) -> None:
        try:
            log(f"HTTP 0.0.0.0:{port}")
            ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
        except Exception as e:
            log(f"HTTP :{port} failed: {e}")

    threading.Thread(target=serve, args=(PORT,), daemon=True).start()
    if PORT != LEGACY_PORT:
        threading.Thread(target=serve, args=(LEGACY_PORT,), daemon=True).start()

class Handler(BaseHTTPRequestHandler):
    server_version = "WhickCustomerSetup/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:
        log(fmt % args)

    def _json(self, code: int, body: dict) -> None:
        raw = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _html(self, html: str) -> None:
        raw = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        client = self.client_address[0] if self.client_address else ""
        if client and path in ("/", "/index.html", "/setup"):
            mark_phone_seen(client)
        if path in ("/", "/index.html", "/setup"):
            self._html(TEMPLATE.read_text(encoding="utf-8") if TEMPLATE.is_file() else "<h1>Whick</h1>")
            return
        if path == "/api/status":
            st = get_state()
            if st.get("phase") != "done" and (
                st.get("registered")
                or str(st.get("phase") or "") in REMOTE_CC_PHASES
            ):
                handle_cc_remote_install()
                st = get_state()
            if st.get("lan_url") or st.get("install_portal_url") or st.get("phone_login_url"):
                portal = (
                    st.get("install_portal_url")
                    or st.get("phone_login_url")
                    or ""
                ).strip()
                lan = (st.get("lan_url") or "").strip()
                if portal.startswith(WHICK_SITE_BASE):
                    fixed = portal
                    ssot = "portal"
                else:
                    fixed = lan or portal
                    ssot = "lan"
                st = {
                    **st,
                    "setup_url_ssot": ssot,
                    "setup_url_fixed": fixed,
                }
            # strip legacy AP fields from API response
            for k in (
                "ap_ssid",
                "ap_passphrase",
                "ap_ok",
                "ap_iface",
                "ap_client_ips",
                "ap_local_notify",
                "ap_local_notify_at",
                "phone_url_ap",
                "wifi_networks",
                "ap_sta",
                "ap_if",
                "ap_fail_reason",
                "ap_fail_final",
            ):
                st.pop(k, None)
            self._json(
                200,
                {
                    "ok": True,
                    "session_ready": session_ready(),
                    **st,
                    **(
                        {"connect_diag": load_boot_connect_diagnostics()}
                        if st.get("phase") == "error"
                        else {}
                    ),
                },
            )
            return
        self.send_error(404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length > MAX_POST_BODY:
            self._json(413, {"ok": False, "error": "요청 본문이 너무 큽니다."})
            return
        try:
            body = json.loads(self.rfile.read(length).decode() or "{}")
        except json.JSONDecodeError:
            self._json(400, {"ok": False, "error": "잘못된 요청"})
            return

        if path == "/api/reinstall-consent":
            agreed = body.get("agreed")
            if agreed is None:
                agreed = body.get("agree")
            if agreed is None:
                self._json(400, {"ok": False, "error": "agreed (true|false) required"})
                return
            token, _sid = _bootstrap_credentials()
            if not token:
                self._json(400, {"ok": False, "error": "설치 세션이 없습니다"})
                return
            try:
                result = submit_reinstall_consent(token, agreed=bool(agreed))
                cc_phase = str(result.get("phase") or "")
                status = str(result.get("status") or "")
                if cc_phase in REINSTALL_CONSENT_PHASES:
                    set_state(
                        cc_phase=cc_phase,
                        phase=cc_phase,
                        progress_msg=str(result.get("progress_msg") or (
                            "재설치 동의 완료 — 장비 등록을 진행합니다"
                            if result.get("agreed")
                            else "재설치 거부 — USB를 제거하고 미니PC를 재부팅해 주세요"
                        )),
                        reinstall_consent=result.get("reinstall_consent") or {
                            "status": status,
                            "agreed": result.get("agreed"),
                        },
                    )
                    write_tty_status(force=True)
                if result.get("agreed") and status == "granted":
                    threading.Thread(target=try_auto_register, daemon=True).start()
                self._json(200, {"ok": True, **result})
            except Exception as e:
                self._json(400, {"ok": False, "error": str(e)})
            return
        if path == "/api/register":
            st = get_state()
            if st.get("phase") != "register_done":
                try_auto_register()
            else:
                handle_cc_remote_install()
            self._json(
                200,
                {
                    "ok": True,
                    "phase": get_state().get("phase"),
                    "message": "자동 등록 진행 중 — 로그인 입력은 필요 없습니다",
                },
            )
            return

        if path == "/api/register-manual":
            login = str(body.get("login") or body.get("email") or "").strip()
            password = str(body.get("password") or "")
            server_name = str(body.get("server_name") or "Whick Music Server").strip()
            if not login or not password:
                self._json(400, {"ok": False, "error": "whick.org 아이디와 비밀번호를 입력해 주세요."})
                return
            st = get_state()
            token, _sid = _bootstrap_credentials()
            if not token:
                self._json(503, {"ok": False, "error": bi("설치 세션이 없습니다. Whick 연결을 다시 시도해 주세요.", "No install session. Please reconnect to Whick.")})
                return
            try:
                reg = register_product(token, login, password, server_name)
                set_state(
                    phase="register_done",
                    registered=True,
                    member_no=reg.get("member_no", ""),
                    device_id=reg.get("device_id"),
                    progress_pct=100,
                    progress_msg=bi("초기 연동 완료", "Initial link complete"),
                    progress_detail=reg.get("member_no", ""),
                )
                write_tty_status()
                handle_cc_remote_install()
                self._json(
                    200,
                    {
                        "ok": True,
                        "member_no": reg.get("member_no", ""),
                        "device_code": st.get("device_code") or get_state().get("device_code"),
                        "device_id": reg.get("device_id"),
                    },
                )
            except Exception as e:
                log(f"register error: {e}")
                msg = str(e)
                if "로그인" in msg or "login" in msg.lower() or "AUTH" in msg or "credentials" in msg.lower():
                    err = "whick.org 아이디 또는 비밀번호가 맞지 않습니다."
                else:
                    err = msg
                self._json(401, {"ok": False, "error": err, "error_code": "login_failed"})
            return

        if path == "/api/retry":
            self._json(200, retry_install())
            return

        self.send_error(404)

def provision_wifi_connect_worker() -> None:
    """무선 USB — provision.json Wi-Fi STA 연결 → WAN 후 on_internet_ready (유선과 동일 후속)."""
    global WIFI_IF, _wifi_connect_started
    ssid, pwd = provision_wifi_credentials()
    if not ssid:
        set_install_error(
            "무선 USB — Wi-Fi 정보(provision.json)가 없습니다. whick.org 다운로드 메뉴에서 SSID·비밀번호를 넣어 만든 «전용 설치 파일»로 USB를 다시 만들어 주세요.",
            code="wifi_provision",
        )
        return
    with _wifi_connect_lock:
        if _wifi_connect_started:
            return
        _wifi_connect_started = True
    try:
        ensure_wifi_sta_tools()
        ensure_kernel_modules()
        wifi = WIFI_IF or wait_for_wifi(max_sec=90)
        if not wifi:
            raise RuntimeError("Wi-Fi 어댑터를 찾을 수 없습니다")
        WIFI_IF = wifi
        set_state(
            home_ssid=ssid,
            phase="wifi_connecting",
            setup_mode="lan",
            progress_pct=10,
            progress_msg=bi(f"사전 등록 Wi-Fi «{ssid}» 연결 중…", f"Connecting to provisioned Wi-Fi «{ssid}»…"),
            progress_detail="",
        )
        ip = connect_wifi_sta(ssid, pwd, wifi)
        guide = customer_install_guide_url(fallback_lan=f"http://{ip}:{PORT}/")
        detail = guide or f"http://{ip}:{PORT}/"
        set_state(
            lan_url=f"http://{ip}:{PORT}/",
            progress_detail=detail,
            install_portal_url=guide or "",
            home_ssid=ssid,
        )
        log(f"provision Wi-Fi connected ssid={ssid} ip={ip}")
        on_internet_ready()
    except Exception as e:
        log(f"provision wifi connect: {e}")
        msg = str(e)
        err_code = None
        if "비밀번호" in msg or "거부" in msg or "password rejected" in msg.lower() or "AP denied" in msg:
            err_code = "wifi_auth"
        elif "어댑터" in msg:
            err_code = "wifi_failed"
        elif is_wireless_usb_profile():
            # 일시 실패는 wifi_provision 유지 → retry worker 가 재시도
            err_code = "wifi_provision"
        if not err_code:
            guide = classify_install_error(msg, {"net_profile": read_net_profile()})
            err_code = guide.get("error_code") or "wifi_failed"
        set_install_error(msg, code=err_code)
    finally:
        with _wifi_connect_lock:
            _wifi_connect_started = False


def provision_wifi_retry_worker() -> None:
    """provision STA 재시도 — 유선 network_worker eth 루프와 대칭."""
    backoff = 3
    while True:
        st = get_state()
        phase = st.get("phase")
        if phase in ("done", "register_done"):
            return
        if st.get("wan_ok") or phase in ("connecting", "register_needed", "register_done"):
            return
        if phase == "error" and not _retriable_install_error():
            return
        if has_wan() and get_wifi_sta_ip():
            on_internet_ready()
            return
        with _wifi_connect_lock:
            busy = _wifi_connect_started
        if not busy and phase in ("wifi_connecting", "lan_setup", "booting", "error"):
            threading.Thread(target=provision_wifi_connect_worker, daemon=True).start()
        time.sleep(backoff)
        backoff = min(30, backoff + 2)


def startup_network_wireless_only() -> None:
    """무선 전용 USB — provision Wi-Fi STA → WAN → boot-connect (유선과 동일 후속)."""
    global WIFI_IF
    init_provision_bootstrap()
    ensure_kernel_modules()
    time.sleep(0.3)
    ssid, _ = provision_wifi_credentials()
    set_state(
        setup_mode="lan",
        phase="wifi_connecting" if ssid else "error",
        progress_pct=8,
        progress_msg=(
            f"사전 등록 Wi-Fi «{ssid}» 연결 준비…"
            if ssid
            else "Wi-Fi provision 없음 — 다운로드 메뉴 «전용 설치 파일» zip 필요"
        ),
        progress_detail="",
    )
    log("wireless USB: provision STA only (no AP, no wired eth)")
    WIFI_IF = WIFI_IF or find_wifi_once() or ""
    threading.Thread(target=provision_wifi_connect_worker, daemon=True).start()
    threading.Thread(target=provision_wifi_retry_worker, daemon=True).start()
    threading.Thread(
        target=network_worker,
        args=(False,),
        kwargs={"skip_initial_eth_wait": True},
        daemon=True,
    ).start()


def startup_network_wired_only() -> None:
    """유선 전용 USB — LAN/WAN만 (Wi-Fi AP 사용 안 함)."""
    ensure_kernel_modules()
    time.sleep(0.3)
    set_state(
        setup_mode="lan",
        phase="lan_setup",
        progress_pct=8,
        progress_msg=bi("유선 LAN 연결 대기 중… (미니PC ↔ 공유기 LAN 포트)", "Waiting for wired LAN… (mini PC ↔ router LAN port)"),
        progress_detail="",
    )
    if eth_has_link():
        log("wired USB: link up — trying WAN")
        for _ in range(4):
            request_eth_dhcp()
            if has_wan():
                on_wired_ready()
                threading.Thread(
                    target=network_worker,
                    args=(False,),
                    kwargs={"skip_initial_eth_wait": True},
                    daemon=True,
                ).start()
                threading.Thread(target=late_wired_watch, daemon=True).start()
                return
            time.sleep(3)
        set_state(progress_msg=bi("유선 연결됨 — 인터넷 연결 확인 중…", "Wired link up — checking Internet…"))
    threading.Thread(
        target=network_worker,
        args=(False,),
        kwargs={"skip_initial_eth_wait": True},
        daemon=True,
    ).start()
    threading.Thread(target=late_wired_watch, daemon=True).start()


def startup_network() -> None:
    """프로필별 네트워크 기동 — wired=LAN only, wireless=provision STA, full=유선 대기(AP 금지)."""
    if is_wired_usb_profile():
        log("net-profile wired — LAN only, no Wi-Fi/AP")
        startup_network_wired_only()
        return
    if is_wireless_usb_profile():
        log("net-profile wireless — provision Wi-Fi STA, same post-WAN as wired")
        startup_network_wireless_only()
        return
    ensure_kernel_modules()
    time.sleep(0.3)

    if eth_has_link():
        log("wired link — trying WAN (max ~12s)")
        for _ in range(4):
            request_eth_dhcp()
            if has_wan():
                on_wired_ready()
                threading.Thread(
                    target=network_worker,
                    args=(False,),
                    kwargs={"skip_initial_eth_wait": True},
                    daemon=True,
                ).start()
                threading.Thread(target=late_wired_watch, daemon=True).start()
                return
            time.sleep(3)
        log("wired link but no WAN — keep waiting for eth (no AP)")

    log("full profile: waiting for eth/USB-LAN — never start AP")
    set_state(
        setup_mode="lan",
        phase="lan_setup",
        progress_pct=8,
        progress_msg=bi("유선 LAN 연결 대기 중… (미니PC ↔ 공유기 LAN 포트)", "Waiting for wired LAN… (mini PC ↔ router LAN port)"),
        progress_detail="",
    )
    threading.Thread(
        target=network_worker,
        args=(False,),
        kwargs={"skip_initial_eth_wait": True},
        daemon=True,
    ).start()
    threading.Thread(target=late_wired_watch, daemon=True).start()


def main() -> None:
    init_provision_bootstrap()
    set_state(
        phase="booting",
        setup_mode="lan",
        progress_pct=5,
        progress_msg=bi("Whick 설치 준비 중…", "Preparing Whick install…"),
        progress_detail="",
        hw_skip=SKIP_HW_ID,
    )

    threading.Thread(target=ensure_kernel_modules, daemon=True).start()
    threading.Thread(target=session_keepalive_loop, daemon=True).start()
    threading.Thread(target=cc_install_sync_loop, daemon=True).start()
    start_cc_install_device_ws()
    threading.Thread(target=run_http_server, daemon=True).start()
    threading.Thread(target=startup_network, daemon=True).start()
    threading.Thread(target=cc_connect_worker, daemon=True).start()
    threading.Thread(target=error_recovery_watch, daemon=True).start()
    # tty_status_loop가 LAN 안내를 그림. 여기서 'Setup server running…'을 덮어쓰면
    # fingerprint 미변화 시 유선 대기 멘트가 영구히 안 나오는 버그가 난다 (2026-08-26).
    threading.Thread(target=tty_status_loop, daemon=True).start()

    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
