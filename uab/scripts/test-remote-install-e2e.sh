#!/usr/bin/env bash
# 원격 설치 Phase 5~7 E2E — CC orchestrator + phase scripts dry-run
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CC="${WHICK_CC_API_URL:-https://admin.whick.org/api/v1}"
PHASE_DIR="$(mktemp -d /tmp/whick-remote-e2e-XXXXXX)"
BOOT_JSON="$PHASE_DIR/bootstrap.json"
trap 'rm -rf "$PHASE_DIR"' EXIT

ok() { echo "  PASS  $*"; }
fail() { echo "  FAIL  $*" >&2; exit 1; }

echo "==> remote install E2E (CC + phases dry-run)"
echo "    CC=$CC"
echo "    PHASE_DIR=$PHASE_DIR"

python3 - <<PY
import json, os, subprocess, sys, time, urllib.error, urllib.request

CC = "$CC".rstrip("/")
PHASE_DIR = "$PHASE_DIR"
BOOT_JSON = "$BOOT_JSON"
ROOT = "$ROOT"
failures = []

def req(url, method="GET", data=None, headers=None):
    h = {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "Whick-Remote-E2E/1.0"}
    secret = (os.environ.get("WHICK_INSTALL_BOOTSTRAP_SECRET")
              or os.environ.get("CC_TEST_INSTALL_BOOTSTRAP_SECRET")
              or os.environ.get("CC_INSTALL_BOOTSTRAP_SECRET")
              or "").strip()
    if secret:
        h["X-Whick-Bootstrap-Secret"] = secret
    if headers:
        h.update(headers)
    body = json.dumps(data).encode() if data else None
    r = urllib.request.Request(url, data=body, headers=h, method=method)
    with urllib.request.urlopen(r, timeout=30) as resp:
        return json.loads(resp.read())

# 1) session + hw-report
raw = req(f"{CC}/install/sessions", "POST", {
    "type": "install_session_create",
    "payload": {"install_path": "diy", "hostname_hint": "remote-e2e"},
})
if not raw.get("ok"):
    failures.append(f"session create: {raw.get('error')}")
data = raw["data"]
token = data["bootstrap_token"]
sid = int(data["session_id"])
code = data["device_code"]

raw2 = req(f"{CC}/install/hw-report", "POST", {
    "type": "hw_report",
    "payload": {
        "session_id": sid,
        "fingerprint": {
            "source": "remote-e2e",
            "kernel": "6.12.93-0-lts",
            "ram_gb": 32,
            "identity_source": "motherboard",
            "motherboard": {
                "manufacturer": "ASUSTeK COMPUTER INC.",
                "product": "H610M-E",
                "serial": "REMOTE-E2E-001",
                "uuid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            },
            "lan_url": "http://192.168.77.10:8765/",
            "access_mode": "lan",
            "nics": [{"kind": "eth", "pci_id": "10ec:8125", "name": "RTL8125"}],
        },
    },
}, headers={"Authorization": f"Bearer {token}"})
if not raw2.get("ok"):
    failures.append(f"hw-report: {raw2.get('error')}")

# simulate register_done
raw3 = req(
    f"{CC}/install/sessions/{sid}/progress",
    "PATCH",
    {"phase": "register_done", "progress_pct": 100, "progress_msg": "registered (e2e)"},
    headers={"Authorization": f"Bearer {token}"},
)
if raw3.get("data", {}).get("phase") != "register_done":
    failures.append(f"register_done patch: {raw3}")

boot = {"session_id": sid, "bootstrap_token": token, "device_code": code}
open(BOOT_JSON, "w").write(json.dumps(boot))

env = os.environ.copy()
env["WHICK_PHASE_DIR"] = PHASE_DIR
env["WHICK_BOOTSTRAP_SESSION"] = BOOT_JSON
env["WHICK_PROD_INSTALL"] = "0"
env["WHICK_LINUX_INSTALL_DRY_RUN"] = "1"
env["WHICK_CC_API_URL"] = CC

# run phase scripts sequentially (CC orchestrator runs one at a time on device)
live = os.path.join(ROOT, "live")
for name in ("02_linux_install", "03_docker", "04_runtime"):
    script = os.path.join(live, "phases", f"{name}.sh")
    proc = subprocess.run(["bash", script], env=env, cwd=live, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        failures.append(f"{name} rc={proc.returncode}\n{proc.stdout[-500:]}\n{proc.stderr[-500:]}")
        break
for flag in ("linux_install_done", "docker_done", "runtime_done"):
    if not os.path.isfile(os.path.join(PHASE_DIR, flag)):
        failures.append(f"missing {flag}")

time.sleep(0.5)
raw4 = req(f"{CC}/install/sessions/{sid}")
phase = raw4.get("data", {}).get("phase")
pct = raw4.get("data", {}).get("progress_pct")
# USB live dry-run — complete는 host_reboot 이후 orchestrator가 설정 (04_runtime이 직접 complete 금지)
if phase not in ("install_runtime", "complete"):
    failures.append(f"expected install_runtime or complete got phase={phase} pct={pct}")

if failures:
    for f in failures:
        print(f"  FAIL  {f}", file=sys.stderr)
    sys.exit(1)

print(f"  PASS  session {sid} {code} → {phase} ({pct}%)")
print(f"  PASS  phase flags in {PHASE_DIR}")
PY

ok "remote install E2E"
echo ""
echo "OK  test-remote-install-e2e.sh"
