#!/usr/bin/env python3
"""스마트폰 설치 UI — :8765 (모니터 없는 미니PC)."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

try:
    from flask import Flask, jsonify, render_template, request
    import requests
except ImportError:
    print("pip3 install flask requests", file=sys.stderr)
    sys.exit(1)

app = Flask(__name__, template_folder=str(Path(__file__).resolve().parent.parent / "templates"))
STATE_PATH = Path("/tmp/whick-uab-state.json")
PHASE_DIR = Path("/tmp/whick-phases")
CC_URL = os.environ.get("WHICK_CC_API_URL", "https://admin.whick.org/api/v1").rstrip("/")


def load_state() -> dict:
    if STATE_PATH.is_file():
        return json.loads(STATE_PATH.read_text())
    return {}


def save_state(data: dict) -> None:
    STATE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def touch_phase(name: str) -> None:
    PHASE_DIR.mkdir(parents=True, exist_ok=True)
    (PHASE_DIR / name).write_text("1\n")


def verify_whick_login(login: str, password: str) -> dict | None:
    """whick.org 회원 확인 — CC staff login 은 Lv6+ 만 되므로 site 연동 Phase 2."""
    login = login.strip()
    if not login or not password:
        return None
    # Phase 2 backlog: whick.org/install OAuth (현재 = LAN :8765)
    return {"mb_id": login.split("@")[0] if "@" not in login else login, "email": login}


@app.get("/")
def index():
    st = load_state()
    return render_template(
        "setup.html",
        device_code=st.get("device_code", "…"),
        cc_url=CC_URL,
        setup_ip=request.host.split(":")[0],
    )


@app.get("/api/status")
def api_status():
    st = load_state()
    return jsonify(
        {
            "device_code": st.get("device_code"),
            "phase": st.get("phase", "await_phone"),
            "registered": bool(st.get("registered")),
            "device_id": st.get("register_result", {}).get("device_id"),
        }
    )


@app.post("/api/consent")
def api_consent():
    body = request.get_json(force=True, silent=True) or {}
    if not body.get("wipe_ok") or not body.get("terms_ok"):
        return jsonify({"ok": False, "error": "동의 필요"}), 400
    touch_phase("consent_done")
    touch_phase("proceed_confirmed")
    # CC에 동의 전달 — 세션 phase를 register_pending 으로 전환
    st = load_state()
    token = st.get("bootstrap_token")
    sid = st.get("session_id")
    if token and sid:
        try:
            r = requests.post(
                f"{CC_URL}/install/consent",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "type": "consent",
                    "payload": {
                        "session_id": sid,
                        "wipe_ok": True,
                        "terms_ok": True,
                        "terms_version": "1.0",
                    },
                },
                timeout=30,
            )
            if r.ok:
                print("[local_web] CC consent OK")
            else:
                print(f"[local_web] CC consent failed: {r.status_code} {r.text}")
        except Exception as e:
            print(f"[local_web] CC consent error: {e}")
    return jsonify({"ok": True})


@app.post("/api/register")
def api_register():
    body = request.get_json(force=True, silent=True) or {}
    login = str(body.get("email") or body.get("login") or "").strip()
    password = str(body.get("password") or "")
    server_name = str(body.get("server_name") or "Whick Music Server").strip()
    mb_id = str(body.get("mb_id") or "").strip()

    if not login or not password:
        return jsonify({"ok": False, "error": "이메일과 비밀번호를 입력하세요"}), 400

    member = verify_whick_login(login, password)
    if not member:
        return jsonify({"ok": False, "error": "로그인 확인 실패"}), 401

    mb_id = mb_id or member.get("mb_id") or login
    st = load_state()
    token = st.get("bootstrap_token")
    sid = st.get("session_id")
    if not token or not sid:
        return jsonify({"ok": False, "error": "bootstrap 세션 없음"}), 503

    r = requests.post(
        f"{CC_URL}/install/register-product",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "type": "register_product",
            "payload": {
                "session_id": sid,
                "mb_id": mb_id,
                "email": member.get("email") or login,
                "server_name": server_name,
            },
        },
        timeout=30,
    )
    if not r.ok:
        return jsonify({"ok": False, "error": r.text}), r.status_code

    reg = r.json()
    st["register_result"] = reg
    st["registered"] = True
    st["mb_id"] = mb_id
    st["phase"] = "register_done"
    save_state(st)
    touch_phase("register_done")

    return jsonify(
        {
            "ok": True,
            "device_id": reg.get("device_id"),
            "remote_url": "https://whick.org/",
            "admin_hint": "admin.whick.org → 뮤직서버관제",
            "message": "미니PC와 스마트폰 계정이 연결되었습니다.",
        }
    )


def main() -> None:
    global STATE_PATH, PHASE_DIR, CC_URL
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default="/tmp/whick-uab-state.json")
    ap.add_argument("--phase-dir", default="/tmp/whick-phases")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="0.0.0.0")
    args = ap.parse_args()
    STATE_PATH = Path(args.state)
    PHASE_DIR = Path(args.phase_dir)
    CC_URL = os.environ.get("WHICK_CC_API_URL", CC_URL).rstrip("/")

    if not STATE_PATH.is_file():
        subprocess.run([str(Path(__file__).parent / "hw_collect.sh")], check=False)
        subprocess.run(
            [sys.executable, str(Path(__file__).parent / "bootstrap-agent.py"), "--state", str(STATE_PATH)],
            check=False,
        )

    app.run(host=args.host, port=args.port, threaded=True)


if __name__ == "__main__":
    main()
