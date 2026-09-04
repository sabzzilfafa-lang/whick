#!/usr/bin/env python3
"""UAB bootstrap agent — CC /install/* outbound."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    print("pip3 install requests", file=sys.stderr)
    sys.exit(1)

CC_URL = os.environ.get("WHICK_CC_API_URL", "https://admin.whick.org/api/v1").rstrip("/")


def install_headers(extra: dict | None = None) -> dict:
    h = {"Content-Type": "application/json", "User-Agent": "Whick-UAB-BootstrapAgent/1.0"}
    secret = (
        os.environ.get("WHICK_INSTALL_BOOTSTRAP_SECRET")
        or os.environ.get("CC_INSTALL_BOOTSTRAP_SECRET")
        or ""
    ).strip()
    if secret:
        h["X-Whick-Install-Secret"] = secret
    if extra:
        h.update(extra)
    return h


def load_hw() -> tuple[dict, str]:
    raw_path = Path(os.environ.get("WHICK_HW_RAW", "/tmp/hw_raw.json"))
    hash_path = Path(os.environ.get("WHICK_HW_HASH", "/tmp/hw_id_hash"))
    if raw_path.is_file():
        raw = json.loads(raw_path.read_text())
        hw_hash = raw.get("hw_id_hash") or hash_path.read_text().strip()
        return raw, hw_hash
    raise SystemExit("hw_collect.sh 먼저 실행")


def api_data(resp: dict) -> dict:
    if resp.get("ok") is True and isinstance(resp.get("data"), dict):
        return resp["data"]
    if resp.get("ok") is False:
        err = resp.get("error") or {}
        raise RuntimeError(err.get("message") or "api error")
    return resp


def post_session() -> dict:
    r = requests.post(
        f"{CC_URL}/install/sessions",
        headers=install_headers(),
        json={
            "type": "install_session_create",
            "payload": {
                "install_path": os.environ.get("WHICK_INSTALL_PATH", "diy"),
                "hostname_hint": os.uname().nodename,
            },
        },
        timeout=30,
    )
    r.raise_for_status()
    return api_data(r.json())


def post_hw(token: str, session_id: int, hw_hash: str, fingerprint: dict) -> None:
    r = requests.post(
        f"{CC_URL}/install/hw-report",
        headers=install_headers({"Authorization": f"Bearer {token}"}),
        json={
            "type": "hw_report",
            "payload": {
                "session_id": session_id,
                "hw_id_hash": hw_hash,
                "fingerprint": fingerprint,
            },
        },
        timeout=30,
    )
    r.raise_for_status()


def post_register(
    token: str, session_id: int, mb_id: str, server_name: str, email: str = ""
) -> dict:
    r = requests.post(
        f"{CC_URL}/install/register-product",
        headers=install_headers({"Authorization": f"Bearer {token}"}),
        json={
            "type": "register_product",
            "payload": {
                "session_id": session_id,
                "mb_id": mb_id,
                "email": email or mb_id,
                "server_name": server_name,
                "mode": "diy",
            },
        },
        timeout=30,
    )
    r.raise_for_status()
    return api_data(r.json())


def save_state(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def marker_reports_real_progress(phase_dir: Path, marker: str) -> bool:
    """dry-run·USB defer·실패 시 CC progress 오보 방지."""
    if (phase_dir / "install_failed").is_file():
        return False
    if os.environ.get("WHICK_LINUX_INSTALL_DRY_RUN", "1").strip() == "1":
        return False
    usb_live = os.environ.get("WHICK_USB_LIVE_INSTALL", "0").strip() == "1"
    if usb_live and marker in ("docker_done", "runtime_done", "install_complete"):
        return False
    return True


def touch_phase(phase_dir: Path, name: str) -> None:
    phase_dir.mkdir(parents=True, exist_ok=True)
    (phase_dir / name).write_text("1\n")


def api_get(token: str, path: str) -> dict:
    r = requests.get(
        f"{CC_URL}{path}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    r.raise_for_status()
    return api_data(r.json())


def api_post(token: str, path: str, payload: dict) -> dict:
    r = requests.post(
        f"{CC_URL}{path}",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
        timeout=30,
    )
    r.raise_for_status()
    return api_data(r.json())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default="/tmp/whick-uab-state.json")
    ap.add_argument("--phase-dir", default="/tmp/whick-phases")
    args = ap.parse_args()
    state_path = Path(args.state)
    phase_dir = Path(args.phase_dir)
    phase_dir.mkdir(parents=True, exist_ok=True)

    if state_path.is_file():
        state = json.loads(state_path.read_text())
    else:
        fingerprint, hw_hash = load_hw()
        sess = post_session()
        token = sess["bootstrap_token"]
        sid = sess["session_id"]
        post_hw(token, sid, hw_hash, fingerprint)
        state = {
            "session_id": sid,
            "device_code": sess.get("device_code"),
            "bootstrap_token": token,
            "hw_id_hash": hw_hash,
            "cc_url": CC_URL,
            "phase": "await_phone",
        }
        save_state(state_path, state)
        print(f"[bootstrap] session={sid} code={state.get('device_code')}")

    # 백그라운드: CC 폴링 (원격 동의·등록) + register_done 감시 · Phase 5~7 progress
    token = state.get("bootstrap_token", "")
    sid = state.get("session_id")
    while True:
        # CC 폴링 — 원격 동의(consent)·자동등록 감지
        try:
            me = api_get(token, "/install/session/me")
            cc_phase = me.get("phase", "")
            cc_customer = me.get("customer_id")
            cc_device = me.get("device_id") or me.get("remote_install", {}).get("device_id")
            can_auto = me.get("can_auto_register", False)
            reinstall_c = me.get("reinstall_consent") or {}

            # 동의 완료 감지 → marker 생성 (await_phone → register_pending 전이 시에만)
            prev_cc_phase = state.get("cc_phase", "")
            state["cc_phase"] = cc_phase
            if cc_phase == "register_pending" and prev_cc_phase in ("await_phone", "") \
               and not state.get("consent_created"):
                touch_phase(phase_dir, "consent_done")
                touch_phase(phase_dir, "proceed_confirmed")
                state["consent_created"] = True
                save_state(state_path, state)
                print(f"[bootstrap] CC consent OK (await_phone→register_pending) → consent_done")

            # auto-register: 재설치 등 이미 고객정보가 있으면 자동등록
            if can_auto and cc_customer and cc_phase == "register_pending" and not state.get("registered"):
                reg = api_post(token, "/install/auto-register", {
                    "type": "auto_register",
                    "payload": {"server_name": "Whick Music Server"},
                })
                state["register_result"] = reg
                state["registered"] = True
                state["device_id"] = reg.get("device_id")
                save_state(state_path, state)
                print(f"[bootstrap] auto-register OK device_id={reg.get('device_id')}")
                # 등록 완료 marker도 생성
                touch_phase(phase_dir, "register_done")
            
            # device_id가 이미 배정된 경우 (자동등록 후)
            if cc_phase in ("register_done", "install_linux", "install_docker", "install_runtime") \
               and not state.get("registered"):
                state["registered"] = True
                save_state(state_path, state)
                touch_phase(phase_dir, "register_done")
                print(f"[bootstrap] device pre-registered → register_done")
        except Exception as e:
            # 네트워크 일시적 단절은 무시 (USB 초기 네트워크 안정화 전)
            pass
        if (phase_dir / "register_done").is_file() and not state.get("registered"):
            reg = state.get("register_result") or {}
            print(f"[bootstrap] registered device_id={reg.get('device_id')}")
            state["registered"] = True
            save_state(state_path, state)
        for marker, cc_phase, pct in (
            ("linux_install_done", "install_linux", 100),
            ("docker_done", "install_docker", 100),
            ("runtime_done", "install_runtime", 100),
            ("install_complete", "complete", 100),
        ):
            flag = phase_dir / marker
            key = f"reported_{marker}"
            if (
                flag.is_file()
                and not state.get(key)
                and token
                and sid
                and marker_reports_real_progress(phase_dir, marker)
            ):
                patch_progress(token, sid, cc_phase, pct, f"phase {marker}", phase_pct=pct)
                state[key] = True
                save_state(state_path, state)
        time.sleep(3)


def patch_progress(
    token: str, sid: int, phase: str, pct: int, msg: str, *, phase_pct: int | None = None
) -> None:
    step = phase_pct if phase_pct is not None else pct
    try:
        r = requests.patch(
            f"{CC_URL}/install/sessions/{sid}/progress",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "type": "install_progress",
                "payload": {
                    "phase": phase,
                    "progress_pct": pct,
                    "phase_progress_pct": step,
                    "progress_msg": msg,
                },
            },
            timeout=30,
        )
        r.raise_for_status()
        print(f"[bootstrap] progress {phase} {pct}%")
    except Exception as e:
        print(f"[bootstrap] progress failed: {e}")


if __name__ == "__main__":
    main()
