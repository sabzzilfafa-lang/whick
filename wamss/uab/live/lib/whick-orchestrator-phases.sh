#!/bin/bash
# SSD Ubuntu — CC orchestrator 명령 pull → phase 스크립트 → ack (관제 트랙 SSOT)
set -euo pipefail

STATE="${WHICK_BOOTSTRAP_SESSION:-/var/lib/whick/bootstrap-session.json}"
PHASE_ROOT="${WHICK_REMOTE_PHASE_ROOT:-/var/lib/whick/remote-phases}"
LOG="${WHICK_ORCH_LOG:-/var/log/whick-orchestrator-phases.log}"
CC="${WHICK_CC_API_URL:-https://admin.whick.org/api/v1}"
MAX_ROUNDS="${WHICK_ORCH_MAX_ROUNDS:-180}"

exec >>"$LOG" 2>&1
echo "=== whick-orchestrator-phases $(date -Is) ==="

if [[ ! -f "$STATE" ]]; then
  echo "no bootstrap session"
  exit 1
fi

export WHICK_PHASE_DIR="${WHICK_PHASE_DIR:-/var/lib/whick/phases}"
export WHICK_LINUX_INSTALL_DRY_RUN="${WHICK_LINUX_INSTALL_DRY_RUN:-0}"
export WHICK_USB_LIVE_INSTALL="${WHICK_USB_LIVE_INSTALL:-0}"
export WHICK_PROD_INSTALL="${WHICK_PROD_INSTALL:-1}"
if [[ -f /etc/default/whick-cc ]]; then
  # shellcheck source=/dev/null
  . /etc/default/whick-cc
fi
CANONICAL_CC_API_URL="${WHICK_CANONICAL_CC_API_URL:-https://admin.whick.org/api/v1}"
export WHICK_CC_API_URL="${WHICK_CC_API_URL:-$CANONICAL_CC_API_URL}"
# USB 세션에서 명시된 CC URL 유지 (firstboot와 동일 규칙)

resolve_working_cc_url() {
  local candidate="$1"
  local fallback="${2:-$CANONICAL_CC_API_URL}"
  candidate="${candidate%/}"
  fallback="${fallback%/}"
  if command -v curl >/dev/null 2>&1; then
    if curl -4 -fsS -m 8 "${candidate}/system/health" >/dev/null 2>&1; then
      echo "$candidate"
      return 0
    fi
    if [[ "$fallback" != "$candidate" ]] && curl -4 -fsS -m 12 "${fallback}/system/health" >/dev/null 2>&1; then
      echo "[orchestrator] CC unreachable at $candidate — using $fallback" >&2
      echo "$fallback"
      return 0
    fi
  fi
  echo "$candidate"
}

WHICK_CC_API_URL="$(resolve_working_cc_url "$WHICK_CC_API_URL")"
export WHICK_CC_API_URL
export WHICK_BOOTSTRAP_SESSION="$STATE"
export WHICK_REMOTE_PHASE_ROOT="$PHASE_ROOT"
CC_CLIENT="$PHASE_ROOT/bin/cc_client.py"
if [[ ! -f "$CC_CLIENT" && -f /opt/whick-boot-connect/cc_client.py ]]; then
  CC_CLIENT=/opt/whick-boot-connect/cc_client.py
fi
export CC_CLIENT
mkdir -p "$WHICK_PHASE_DIR"

python3 <<PY
import json, os, subprocess, sys, time

state_path = os.environ["WHICK_BOOTSTRAP_SESSION"]
phase_root = os.environ["WHICK_REMOTE_PHASE_ROOT"]
cc = os.environ["WHICK_CC_API_URL"].rstrip("/")
cc_client = os.environ.get("CC_CLIENT", "")
max_rounds = int(os.environ.get("WHICK_ORCH_MAX_ROUNDS", "24"))

with open(state_path) as f:
    state = json.load(f)
token = state.get("bootstrap_token") or state.get("token")
if not token:
    raise SystemExit("no bootstrap token")

if cc_client and os.path.isfile(cc_client):
    sys.path.insert(0, os.path.dirname(cc_client))
    from cc_client import (  # type: ignore
        api_data,
        cc_request,
        fetch_remote_phase_bundle,
        ack_bootstrap_command,
    )
else:
    raise SystemExit("cc_client.py missing")

fetch_remote_phase_bundle(token, phase_root)

script_map = {
    "install_linux": os.path.join(phase_root, "phases", "02_linux_install.sh"),
    "install_docker": os.path.join(phase_root, "phases", "03_docker.sh"),
    "install_runtime": os.path.join(phase_root, "phases", "04_runtime.sh"),
}

def session_me():
    return api_data(cc_request("/install/session/me", token=token))

def persist_install_credentials(me):
    import re
    mb = str(me.get("mb_id") or state.get("mb_id") or "").strip()
    hw = str(me.get("hw_id_hash") or state.get("hw_id_hash") or "").strip()
    if not mb and not re.match(r"^[0-9a-fA-F]{64}$", hw or ""):
        return
    cred_path = "/var/lib/whick/install-credentials.json"
    prev = {}
    try:
        with open(cred_path) as f:
            prev = json.load(f)
    except Exception:
        pass
    nxt = dict(prev)
    if mb:
        nxt["mb_id"] = mb
        state["mb_id"] = mb
    if re.match(r"^[0-9a-fA-F]{64}$", hw or ""):
        nxt["device_serial"] = hw
        nxt["hw_id_hash"] = hw
        state["hw_id_hash"] = hw
    nxt["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    os.makedirs(os.path.dirname(cred_path), exist_ok=True)
    tmp = cred_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(nxt, f, ensure_ascii=False, indent=2)
    os.rename(tmp, cred_path)
    os.chmod(cred_path, 0o600)
    with open(state_path, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def run_round():
    me = session_me()
    persist_install_credentials(me)
    phase = me.get("phase")
    ri = me.get("remote_install") or {}
    cmd = ri.get("command")
    if not cmd or not cmd.get("id"):
        return phase, None
    ctype = str(cmd.get("type") or "")
    cid = int(cmd["id"])
    script = script_map.get(ctype)
    if not script or not os.path.isfile(script):
        ack_bootstrap_command(token, cid, success=False, message=f"missing script {ctype}")
        return phase, ctype
    env = os.environ.copy()
    env["WHICK_PHASE_DIR"] = os.environ["WHICK_PHASE_DIR"]
    env["WHICK_LINUX_INSTALL_DRY_RUN"] = "0"
    env["WHICK_USB_LIVE_INSTALL"] = "0"
    try:
        proc = subprocess.run(
            ["bash", script],
            env=env,
            cwd=phase_root,
            capture_output=True,
            text=True,
            timeout=7200,
        )
    except subprocess.TimeoutExpired as e:
        stdout = e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        stderr = e.stderr.decode(errors="replace") if isinstance(e.stderr, bytes) else (e.stderr or "")
        print(f"--- {ctype} STDOUT (timeout) ---")
        print(stdout)
        print(f"--- {ctype} STDERR (timeout) ---", file=sys.stderr)
        print(stderr, file=sys.stderr)
        msg = f"{ctype} timeout after 7200s"
        ack_bootstrap_command(token, cid, success=False, message=msg)
        return phase, ctype
    if proc.stdout:
        print(f"--- {ctype} STDOUT ---")
        print(proc.stdout)
    if proc.stderr:
        print(f"--- {ctype} STDERR ---", file=sys.stderr)
        print(proc.stderr, file=sys.stderr)
    combined = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    ok = proc.returncode == 0
    # Prefer deploy FATAL/ERROR lines; else LAST 512 (old [:512] of [-2000:] hid real errors
    # behind dpkg Unpacking mid-text — session 306 Wi-Fi tools false fail).
    err_lines = [
        ln.strip()
        for ln in combined.splitlines()
        if "FATAL" in ln or "[deploy_bootstrap] ERROR" in ln or ln.startswith("ERROR ")
    ]
    if not ok and err_lines:
        msg = " | ".join(err_lines[-3:])
    else:
        msg = combined[-512:] if combined else ctype
    if ok and ctype == "install_linux":
        msg = "Linux 파티션 설치 완료 — SSD Ubuntu deploy"
    ack_bootstrap_command(token, cid, success=ok, message=msg[:512])
    me = session_me()
    return me.get("phase"), ctype

last = None
for i in range(max_rounds):
    phase, ctype = run_round()
    print(f"round={i+1} phase={phase} cmd={ctype}")
    if phase in ("complete", "failed", "post_install_verify"):
        break
    if phase == "reboot_pending":
        if ctype == "host_reboot":
            continue
        time.sleep(2)
        continue
    if phase == last and not ctype:
        time.sleep(2)
    last = phase
else:
    raise SystemExit("orchestrator rounds exhausted")

final = session_me().get("phase")
print(f"final phase={final}")
if final in ("complete", "post_install_verify"):
    sys.exit(0)
if final == "failed":
    sys.exit(1)
if final == "reboot_pending":
    raise SystemExit("stuck reboot_pending — docker/runtime not delivered")
sys.exit(0)
PY
