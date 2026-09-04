#!/bin/bash
# SSD Ubuntu 첫 부팅 — CC orchestrator (Docker/runtime) + 관제 연동
set -euo pipefail

MARKER=/var/lib/whick/firstboot-done
STATE=/var/lib/whick/bootstrap-session.json
LOG=/var/log/whick-firstboot.log
ORCH=/usr/local/sbin/whick-orchestrator-phases.sh
export WHICK_ORCH_LOG="${WHICK_ORCH_LOG:-/var/log/whick-orchestrator-phases.log}"

exec >>"$LOG" 2>&1
echo "=== whick-firstboot $(date -Is) ==="

if [[ -f "$MARKER" ]]; then
  echo "already done"
  exit 0
fi

if [[ ! -f "$STATE" ]]; then
  echo "ERROR no bootstrap session — cannot continue install"
  exit 1
fi

export WHICK_BOOTSTRAP_SESSION="$STATE"
if [[ -f /etc/default/whick-cc ]]; then
  # shellcheck source=/dev/null
  . /etc/default/whick-cc
fi
if [[ -z "${WHICK_CC_API_URL:-}" ]]; then
  WHICK_CC_API_URL="$(python3 - <<'PY' "$STATE"
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    print(str(d.get("cc_api_url") or "").strip())
except Exception:
    pass
PY
)"
fi
CANONICAL_CC_API_URL="${WHICK_CANONICAL_CC_API_URL:-https://admin.whick.org/api/v1}"
export WHICK_CC_API_URL="${WHICK_CC_API_URL:-$CANONICAL_CC_API_URL}"
# USB 세션에서 명시된 CC URL(공개 터널 호스트)이면 유지.
# resolve_working_cc_url 가 접속 가능 여부를 검증하므로 무조건 canonical 로 덮지 않는다.

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
      echo "[firstboot] CC unreachable at $candidate — using $fallback" >&2
      echo "$fallback"
      return 0
    fi
  fi
  echo "$candidate"
}

WHICK_CC_API_URL="$(resolve_working_cc_url "$WHICK_CC_API_URL")"
export WHICK_CC_API_URL
export WHICK_PHASE_DIR=/var/lib/whick/phases
export WHICK_REMOTE_PHASE_ROOT=/var/lib/whick/remote-phases
export WHICK_LINUX_INSTALL_DRY_RUN=0
export WHICK_USB_LIVE_INSTALL=0
export WHICK_PROD_INSTALL=1
export WHICK_RUNTIME_ROOT="${WHICK_RUNTIME_ROOT:-/opt/whick/runtime}"
export WHICK_COMPONENTS_LOCK="${WHICK_COMPONENTS_LOCK:-/opt/whick/runtime/components.lock.json}"
mkdir -p "$WHICK_PHASE_DIR" "$WHICK_REMOTE_PHASE_ROOT"

upload_firstboot_logs() {
  local rc="$1"
  set +e
  if [[ ! -f "$STATE" ]]; then
    return 0
  fi
  local journal_log=/run/whick-firstboot-journal.log
  if command -v journalctl >/dev/null 2>&1; then
    journalctl -u whick-install-firstboot.service -n 500 --no-pager >"$journal_log" 2>&1 || true
  fi
  python3 - <<'PY' "$STATE" "$WHICK_CC_API_URL" "$rc" "$LOG" "$WHICK_ORCH_LOG" "$journal_log" || true
import json
import os
import sys
import urllib.request

state_path, cc_url, rc_s, firstboot_log, orch_log, journal_log = sys.argv[1:]
try:
    state = json.load(open(state_path))
except Exception:
    raise SystemExit(0)
token = state.get("bootstrap_token") or state.get("token")
if not token:
    raise SystemExit(0)

def read_tail(path, limit=1500000):
    if not path or not os.path.isfile(path):
        return ""
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - limit))
        return f.read().decode("utf-8", errors="replace")

logs = []
for name, path in (
    ("whick-firstboot.log", firstboot_log),
    ("whick-orchestrator-phases.log", orch_log),
    ("whick-install-firstboot.journal", journal_log),
):
    content = read_tail(path)
    if content:
        logs.append({"name": name, "path": path, "content": content})

if not logs:
    raise SystemExit(0)

try:
    rc = int(rc_s)
except Exception:
    rc = 1
status = "complete" if rc == 0 else "failed"
boot_id = ""
try:
    boot_id = open("/proc/sys/kernel/random/boot_id").read().strip()
except Exception:
    pass
payload = {
    "type": "bootstrap_logs",
    "payload": {
        "source": "ssd-firstboot",
        "stage": "firstboot",
        "status": status,
        "exit_code": rc,
        "boot_id": boot_id,
        "message": "SSD firstboot complete" if rc == 0 else "SSD firstboot failed; see uploaded logs",
        "logs": logs,
        "meta": {
            "hostname": os.uname().nodename,
            "runtime_root": os.environ.get("WHICK_RUNTIME_ROOT", ""),
        },
    },
}
req = urllib.request.Request(
    cc_url.rstrip("/") + "/install/bootstrap/logs",
    data=json.dumps(payload, ensure_ascii=False).encode(),
    headers={
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "Whick-SSD-Firstboot/1.0",
    },
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=45) as resp:
        print("[firstboot] log upload OK", resp.status)
except Exception as e:
    print("[firstboot] log upload failed", e)
PY
}

_whick_firstboot_finish() {
  local rc="$?"
  upload_firstboot_logs "$rc" || true
  exit "$rc"
}
trap _whick_firstboot_finish EXIT

ensure_ssd_network() {
  local iface name i=0
  local need_wifi=0
  # 무선 USB 이관 — provision STA (유선 없을 때 Docker/runtime 가능)
  if [[ -f /etc/whick/wpa_supplicant.conf ]]; then
    need_wifi=1
    if [[ -f /opt/whick-boot-connect/whick-kernel-modules.sh ]]; then
      # shellcheck source=/dev/null
      . /opt/whick-boot-connect/whick-kernel-modules.sh
      whick_load_net_modules 2>/dev/null || true
    fi
    if [[ -x /usr/local/sbin/whick-wifi-sta.sh ]]; then
      echo "[firstboot] starting provision Wi-Fi STA…"
      if ! /usr/local/sbin/whick-wifi-sta.sh; then
        echo "[firstboot] WARN Wi-Fi STA failed — will retry while waiting for route" >&2
      fi
    fi
  fi
  systemctl start systemd-networkd 2>/dev/null || true
  for iface in /sys/class/net/*; do
    name="${iface##*/}"
    [[ "$name" == "lo" ]] && continue
    ip link set "$name" up 2>/dev/null || true
    if command -v networkctl >/dev/null 2>&1; then
      networkctl renew "$name" 2>/dev/null || true
    fi
  done
  while [[ "$i" -lt 180 ]]; do
    if ip -4 route show default 2>/dev/null | grep -q .; then
      # CC health 확인 — default route 만으로 가짜 OK 방지
      if command -v curl >/dev/null 2>&1 && [[ -n "${WHICK_CC_API_URL:-}" ]]; then
        if curl -4 -fsS -m 8 "${WHICK_CC_API_URL%/}/system/health" >/dev/null 2>&1; then
          echo "network OK (default route + CC health)"
          ip -4 addr show || true
          return 0
        fi
        echo "[firstboot] default route present but CC health fail — keep waiting ($i s)" >&2
      else
        echo "network OK (default route present)"
        ip -4 addr show || true
        return 0
      fi
    fi
    # 유선 대기 중에도 Wi-Fi 재시도 (드라이버 늦게 뜸)
    if [[ $((i % 20)) -eq 0 && "$need_wifi" -eq 1 ]]; then
      /usr/local/sbin/whick-wifi-sta.sh || true
    fi
    sleep 3
    i=$((i + 3))
  done
  echo "ERROR network not ready after 180s — cannot reach CC for Docker/runtime" >&2
  ip -4 addr show || true
  ip -4 route || true
  return 1
}
ensure_ssd_network || exit 1

# CC 에 "SSD online" 조기 신호 — Docker UI 가 타이머만으로 0% 되는 것 방지
# Cloudflare 는 User-Agent 없는 urllib 를 403/1010 으로 막음 (세션 312)
report_ssd_online() {
  set +e
  python3 - <<'PY' "$STATE" "$WHICK_CC_API_URL" || true
import json, os, sys, urllib.request
state_path, cc_url = sys.argv[1], sys.argv[2]
UA = "Whick-SSD-Firstboot/1.0"
try:
    state = json.load(open(state_path))
except Exception:
    raise SystemExit(0)
token = state.get("bootstrap_token") or state.get("token")
if not token:
    raise SystemExit(0)
boot_id = ""
try:
    boot_id = open("/proc/sys/kernel/random/boot_id").read().strip()
except Exception:
    pass
payload = {
    "type": "bootstrap_logs",
    "payload": {
        "source": "ssd-firstboot",
        "stage": "network_ok",
        "status": "complete",
        "exit_code": 0,
        "boot_id": boot_id,
        "message": "SSD online — network ready for Docker/runtime",
        "logs": [{"name": "ssd-online.txt", "path": "/run/whick-ssd-online", "content": "network OK\n"}],
        "meta": {"hostname": os.uname().nodename},
    },
}
req = urllib.request.Request(
    cc_url.rstrip("/") + "/install/bootstrap/logs",
    data=json.dumps(payload).encode(),
    headers={
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "User-Agent": UA,
    },
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        print("[firstboot] ssd-online ping OK", resp.status)
except Exception as e:
    print("[firstboot] ssd-online ping failed", e)
PY
  set -e
}
report_ssd_online
# CC 가 network_ok 로 Docker 를 enqueue 할 시간 — orch 전 대기
wait_for_post_ssd_commands() {
  local i=0
  echo "[firstboot] waiting for install_docker command from CC…"
  while [[ "$i" -lt 90 ]]; do
    if python3 - <<'PY' "$STATE" "$WHICK_CC_API_URL"
import json, sys, urllib.request
state_path, cc = sys.argv[1], sys.argv[2].rstrip("/")
UA = "Whick-SSD-Firstboot/1.0"
state = json.load(open(state_path))
token = state.get("bootstrap_token") or state.get("token")
if not token:
    raise SystemExit(1)
req = urllib.request.Request(
    cc + "/install/session/me",
    headers={
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "User-Agent": UA,
    },
)
with urllib.request.urlopen(req, timeout=15) as r:
    data = json.loads(r.read().decode("utf-8", errors="replace"))
inner = data.get("data") if isinstance(data.get("data"), dict) else data
cmd = inner.get("command") or inner.get("pending_command") or {}
ctype = str(cmd.get("type") or cmd.get("command_type") or "")
if ctype in ("install_docker", "install_runtime"):
    raise SystemExit(0)
raise SystemExit(1)
PY
    then
      echo "[firstboot] post-SSD command ready"
      return 0
    fi
    sleep 2
    i=$((i + 2))
  done
  echo "[firstboot] WARN no install_docker yet — orchestrator will still run" >&2
  return 0
}
wait_for_post_ssd_commands || true

maybe_refresh_stale_phase_bundle() {
  local marker="$WHICK_REMOTE_PHASE_ROOT/.bundle-ok"
  local remote_ver="" local_ver=""
  [[ -f "$STATE" ]] || return 0
  if ! command -v curl >/dev/null 2>&1; then
    return 0
  fi
  remote_ver="$(python3 - <<'PY' "$STATE" "$WHICK_CC_API_URL"
import json, sys, urllib.request
state_path, cc = sys.argv[1], sys.argv[2].rstrip("/")
UA = "Whick-SSD-Firstboot/1.0"
try:
    state = json.load(open(state_path))
except Exception:
    raise SystemExit(0)
token = state.get("bootstrap_token") or state.get("token")
if not token:
    raise SystemExit(0)
try:
    req = urllib.request.Request(
        cc + "/install/bootstrap/phase-bundle/meta",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": UA,
        },
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode("utf-8", errors="replace"))
    inner = data.get("data") if isinstance(data.get("data"), dict) else data
    print(str(inner.get("version") or "").strip())
except Exception:
    raise SystemExit(0)
PY
)" || remote_ver=""
  if [[ -f "$marker" ]]; then
    local_ver="$(tr -d '\n' <"$marker")"
  fi
  if [[ -n "$remote_ver" && "$remote_ver" != "$local_ver" ]]; then
    echo "[firstboot] stale phase bundle ($local_ver -> $remote_ver) — refresh"
    rm -f "$marker"
  fi
}
maybe_refresh_stale_phase_bundle || true

if [[ -x "$ORCH" ]]; then
  echo "run orchestrator phases"
  if ! bash "$ORCH"; then
    echo "ERROR orchestrator phases failed — marker not set (retry on next boot)"
    exit 1
  fi
else
  echo "WARN $ORCH missing — legacy phase run"
  BC=/opt/whick-boot-connect
  ROOT="$WHICK_REMOTE_PHASE_ROOT"
  for script in "$ROOT/phases/03_docker.sh" "$ROOT/phases/04_runtime.sh"; do
    [[ -f "$script" ]] && bash "$script" || true
  done
fi

touch "$MARKER"
echo "firstboot complete $(date -Is)"
