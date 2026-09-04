#!/usr/bin/env bash
# SSD2(/whick-lab) loop — 실제 prod 설치 E2E (phase 5~7) · 소요 시간 측정
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LAB_SAFE="/data/whick-ai/7_ai_only/scripts/whick-lab-docker-safe.sh"
if [[ -f "$LAB_SAFE" ]]; then
  # shellcheck source=/dev/null
  source "$LAB_SAFE"
fi
PRODUCT="$(cd "$ROOT/.." && pwd)"
UAB="$ROOT"
LIVE="$UAB/live"
LAB_MOUNT="${WHICK_LAB_MOUNT:-/whick-lab}"
LOOPS_DIR="$LAB_MOUNT/loops"
CC="${WHICK_CC_API_URL:-http://127.0.0.1:8090/api/v1}"
BOOTSTRAP="${WHICK_BOOTSTRAP_ROOTFS:-$ROOT/../dist/uab/whick-bootstrap-rootfs.tar.xz}"
RUNTIME_DIST="${WHICK_MUSIC01_DIST:-$ROOT/../dist/music-01}"
PHASE_DIR="$(mktemp -d /tmp/whick-lab-e2e-XXXXXX)"
WORK="$PHASE_DIR/work"
LOG="$PHASE_DIR/e2e.log"
IMG=""
LOOP=""
ROOT_PART=""
MNT="$WORK/mnt"
START_TS=$(date +%s)

exec > >(tee -a "$LOG") 2>&1

die() { echo "ERROR: $*" >&2; exit 1; }
run_root() { "$@"; }
run_root_env() { "$@"; }
phase_time() { echo "[timing] $1: ${SECONDS}s (total ${SECONDS}s)"; }

report_lab_session_phase() {
  local phase="$1" message="$2"
  [[ -n "${LAB_SID:-}" && -n "${LAB_TOKEN:-}" ]] || return 0
  curl -fsS --max-time 15 -X PATCH \
    -H "Authorization: Bearer ${LAB_TOKEN}" \
    -H "X-Whick-VID-Secret: ${VID_SECRET:-}" \
    -H "X-Whick-VID-Mb-Id: ${VID_MB:-}" \
    -H 'Content-Type: application/json' \
    -d "{\"phase\":\"${phase}\",\"progress_pct\":$([[ "$phase" == complete ]] && echo 100 || echo 0),\"progress_msg\":\"${message}\"}" \
    "${CC}/install/sessions/${LAB_SID}/progress" >/dev/null
}

cleanup() {
  local main_rc=$?
  if [[ "$main_rc" -ne 0 ]]; then
    report_lab_session_phase failed "lab E2E failed — automatic cleanup" || true
  fi
  run_root umount -lf "$MNT/boot/efi" 2>/dev/null || true
  run_root umount -lf "$MNT" 2>/dev/null || true
  if [[ -n "${LOOP:-}" ]]; then run_root losetup -d "$LOOP" 2>/dev/null || true; fi
  [[ -n "${IMG:-}" && -f "$IMG" ]] && rm -f "$IMG"
  if declare -F lab_teardown >/dev/null 2>&1; then
    if ! lab_teardown; then
      exit 1
    fi
  fi
  if [[ "$main_rc" -ne 0 ]]; then
    exit "$main_rc"
  fi
}
trap cleanup EXIT

lab_enforce_central_bind

echo "========================================"
echo " Whick prod install lab E2E (SSD2 loop)"
echo " $(date -Is)"
echo " LOG=$LOG"
echo "========================================"

mountpoint -q "$LAB_MOUNT" || die "$LAB_MOUNT not mounted"
if declare -F lab_assert_prod_infra >/dev/null 2>&1; then
  lab_assert_prod_infra || die "CC/그누보드 확인 후 SSD2 E2E 실행"
fi
LAB_LOOP_GB="${WHICK_LAB_LOOP_GB:-256}"
if [[ "$LAB_LOOP_GB" -lt 32 ]]; then
  die "WHICK_LAB_LOOP_GB must be >= 32 (got ${LAB_LOOP_GB})"
fi
[[ -f "$BOOTSTRAP" ]] || die "missing bootstrap: $BOOTSTRAP"
bootstrap_size="$(stat -c%s "$BOOTSTRAP")"
if [[ "$bootstrap_size" -lt 100000000 ]]; then
  die "bootstrap archive too small (${bootstrap_size}B): $BOOTSTRAP"
fi
bootstrap_magic="$(head -c 6 "$BOOTSTRAP" | od -An -tx1 | tr -d ' \n')"
if [[ "${bootstrap_magic:0:8}" != "fd377a58" ]]; then
  die "bootstrap not xz-compressed (magic=$bootstrap_magic): $BOOTSTRAP"
fi
[[ -f "$LIVE/phases/02_linux_install.sh" ]] || die "missing phases"

mkdir -p "$LOOPS_DIR" "$WORK" "$RUNTIME_DIST"

# --- lab runtime bundle (pinned dev images on lab) ---
LAB_BUNDLE="$RUNTIME_DIST/music-01-runtime-lab.tar.zst"
OLLAMA_IMG="${WHICK_LAB_OLLAMA_IMAGE:-ollama/ollama:latest}"
SAMPLE_AUDIO="${WHICK_SAMPLE_AUDIO_PATH:-$PRODUCT/../5_site/content/sample-audio}"
OLLAMA_SEED_VOL="${WHICK_LAB_OLLAMA_SEED_VOLUME:-docker_whick_ollama}"

rebuild_lab_bundle() {
  echo "==> build lab runtime bundle (dev images + ollama)"
  STAGE="$(mktemp -d)"
  cp -a "$PRODUCT/install/runtime/scripts" "$STAGE/scripts"
  cp "$PRODUCT/install/runtime/components.lock.json" "$STAGE/components.lock.json"
  cp "$PRODUCT/compose.yaml" "$STAGE/compose.yaml"
  mkdir -p "$STAGE/remote/api"
  cp "$PRODUCT/remote/api/init.sql" "$STAGE/remote/api/init.sql"
  cp "$PRODUCT/.env.example" "$STAGE/.env.example" 2>/dev/null || true
  cp "$STAGE/.env.example" "$STAGE/.env" 2>/dev/null || true
  mkdir -p "$STAGE/offline/images"
  for img in whick/agent:dev whick/audio:dev whick/monitor:dev whick/player:dev postgres:16-alpine tecnativa/docker-socket-proxy:0.3.0 "$OLLAMA_IMG"; do
    safe="${img//[:\/]/_}"
    docker image inspect "$img" >/dev/null 2>&1 || die "missing image $img — build/pull first"
    docker save -o "$STAGE/offline/images/${safe}.tar" "$img"
  done
  tar -cf - -C "$STAGE" . | zstd -T0 -q -f -o "$LAB_BUNDLE"
  rm -rf "$STAGE"
  echo "lab bundle $(du -h "$LAB_BUNDLE" | awk '{print $1}')"
}

if [[ "${WHICK_LAB_REBUILD_BUNDLE:-0}" == "1" ]] || [[ ! -f "$LAB_BUNDLE" ]]; then
  rebuild_lab_bundle
elif ! zstd -dc "$LAB_BUNDLE" 2>/dev/null | tar -t 2>/dev/null \
  | awk '/offline\/images\/ollama_ollama/ { found=1 } END { exit !found }'; then
  echo "==> lab bundle missing ollama image — rebuild"
  rebuild_lab_bundle
fi

# --- CC session + device register (VID — agent/monitor/robots) ---
echo "==> CC session + register (VID)"
VID_SECRET="${WHICK_VID_SECRET:-}"
if [[ -z "$VID_SECRET" ]]; then
  VID_SECRET="$(docker exec whick-cc-api-core printenv CC_SITE_SYNC_SECRET 2>/dev/null || true)"
fi
VID_SECRET="${VID_SECRET:-whick-cc-site-sync-dev}"
VID_MB="${WHICK_VID_MB_ID:-bkhkorea@gmail.com}"
export VID_SECRET VID_MB
LAB_EXPORTS="$(python3 - <<PY
import json, os, time, urllib.request, uuid

CC = "$CC".rstrip("/")
VID = os.environ["VID_SECRET"]
MB = os.environ["VID_MB"]
stamp = int(time.time())

def vid_headers(extra=None):
    h = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Whick-VID-Secret": VID,
        "X-Whick-VID-Mb-Id": MB,
    }
    if extra:
        h.update(extra)
    return h

def req(url, method="GET", data=None, headers=None, quiet=False):
    h = headers or {"Content-Type": "application/json", "Accept": "application/json"}
    body = json.dumps(data).encode() if data is not None else None
    r = urllib.request.Request(url, data=body, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            raw = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if not quiet:
            detail = e.read().decode(errors="replace")[:500]
            raise SystemExit(f"CC HTTP {e.code} {url}: {detail}")
        raw = {"ok": False, "error": {"code": "HTTP_" + str(e.code), "message": e.read().decode()[:200]}}
    if not raw.get("ok"):
        if not quiet:
            raise SystemExit(f"CC error: {raw.get('error')}")
        return None
    return raw["data"]

sess = req(f"{CC}/install/sessions", "POST", {
    "type": "install_session_create",
    "payload": {"install_path": "diy", "hostname_hint": f"lab-e2e-{stamp}"},
}, vid_headers())
token = sess["bootstrap_token"]
sid = int(sess["session_id"])
code = sess.get("device_code", "")
auth = vid_headers({"Authorization": f"Bearer {token}"})

def fail_session(message):
    req(f"{CC}/install/sessions/{sid}/progress", "PATCH", {
        "phase": "failed",
        "progress_pct": 0,
        "progress_msg": message,
    }, auth, quiet=True)

fp = {
    "source": "virtual-install-device",
    "vid_test": True,
    "kernel": "6.12.93-0-lts",
    "ram_gb": 32,
    "identity_source": "motherboard",
    "motherboard": {
        "manufacturer": "ASUSTeK COMPUTER INC.",
        "product": "H610M-E",
        "serial": f"LAB-E2E-{stamp}",
        "uuid": str(uuid.uuid4()),
    },
    "lan_url": "http://192.168.77.10:8765/",
    "access_mode": "lan",
    "nics": [{"kind": "eth", "pci_id": "10ec:8125", "name": "RTL8125"}],
}
try:
    hr = req(f"{CC}/install/hw-report", "POST", {
        "type": "hw_report",
        "payload": {"session_id": sid, "fingerprint": fp},
    }, auth)
except BaseException:
    fail_session("lab E2E hw-report failed")
    raise
hw = hr.get("hw_id_hash") or hr.get("hw_id_hash_server") or ""
if not hr.get("auth_ok"):
    import sys as _sys
    print(f"WARNING: hw-report auth_ok=false (lab env, IP mismatch) — continuing: {hr}", file=_sys.stderr)

reg = req(f"{CC}/install/auto-register", "POST", {
    "type": "auto_register",
    "payload": {"server_name": "Lab E2E Music Server"},
}, auth, quiet=True)
if reg is None:
    # auto-register returned error but may have succeeded server-side
    # fallback: read session state directly
    fallback = req(f"{CC}/install/sessions/{sid}")
    device_id = int(fallback.get("device_id") or 0)
    if not device_id:
        fail_session("lab E2E auto-register failed")
        raise SystemExit(f"auto-register failed and no device_id in session {sid}")
    print(f"WARNING: auto-register HTTP error — using session fallback (device={device_id})", file=__import__('sys').stderr)
else:
    device_id = int(reg["device_id"])
    hw = reg.get("serial_no") or hw

print(f"export LAB_TOKEN={token!r}")
print(f"export LAB_SID={sid!r}")
print(f"export LAB_CODE={code!r}")
print(f"export LAB_HW_HASH={hw!r}")
print(f"export LAB_DEVICE_ID={device_id!r}")
print(f"export LAB_MB_ID={MB!r}")
print(f"register OK session={sid} device={device_id} hw={hw[:12] if hw else '?'}…", file=__import__('sys').stderr)
PY
)"
eval "$LAB_EXPORTS"

BOOT_JSON="$PHASE_DIR/bootstrap-session.json"
python3 - <<PY
import json
open("$BOOT_JSON", "w").write(json.dumps({
    "session_id": int("$LAB_SID"),
    "bootstrap_token": "$LAB_TOKEN",
    "device_code": "$LAB_CODE",
    "hw_id_hash": "$LAB_HW_HASH",
    "device_id": int("$LAB_DEVICE_ID"),
}, indent=2))
PY
chmod 600 "$BOOT_JSON"

# stale loops on old imgs
for l in $(losetup -a 2>/dev/null | grep whick-test | cut -d: -f1); do
  run_root losetup -d "$l" 2>/dev/null || true
done

IMG="$LOOPS_DIR/whick-prod-e2e-$(date +%Y%m%d-%H%M%S).img"
run_root truncate -s "${LAB_LOOP_GB}G" "$IMG"
LOOP="$(run_root losetup -fP --show "$IMG")"
echo "loop=$LOOP img=$IMG"
phase_time "loop setup"

# --- Phase 5 ---
export WHICK_PHASE_DIR="$PHASE_DIR"
export WHICK_BOOTSTRAP_SESSION="$BOOT_JSON"
export WHICK_CC_API_URL="$CC"
export WHICK_LINUX_INSTALL_DRY_RUN=0
export WHICK_DISK_APPLY=1
export WHICK_PROD_INSTALL=1
export WHICK_ALLOW_LIVE_DISK_APPLY=1
export WHICK_USB_LIVE_INSTALL=0
export WHICK_TARGET_DISK="$LOOP"
export WHICK_BOOTSTRAP_ROOTFS="$BOOTSTRAP"
export WHICK_MUSIC_MIN_GB="${WHICK_MUSIC_MIN_GB:-10}"
export WHICK_INSTALL_RESERVE_GB="${WHICK_INSTALL_RESERVE_GB:-64}"
export WHICK_INSTALL_MIN_GB="${WHICK_INSTALL_MIN_GB:-64}"
export WHICK_REMOTE_PHASE_DIR="$PHASE_DIR/cc-phases"

mkdir -p "$WHICK_REMOTE_PHASE_DIR"
python3 - <<PY
import os, sys, urllib.request, json, tarfile, io
CC = os.environ["WHICK_CC_API_URL"].rstrip("/")
token = os.environ.get("LAB_TOKEN", "")
dest = "$WHICK_REMOTE_PHASE_DIR"
if not token:
    boot = json.load(open("$BOOT_JSON"))
    token = boot.get("bootstrap_token") or ""
url = f"{CC}/install/bootstrap/phase-bundle"
req = urllib.request.Request(url, headers={
    "Authorization": f"Bearer {token}",
    "Accept": "application/gzip",
    "User-Agent": "Whick-Lab-E2E/1.0",
}, method="GET")
with urllib.request.urlopen(req, timeout=120) as r:
    raw = r.read()
os.makedirs(dest, exist_ok=True)
with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tf:
    tf.extractall(dest)
print("phase bundle OK", len(raw))
PY

echo "==> sync local UAB live (lab dev override)"
rsync -a "$LIVE/phases/" "$WHICK_REMOTE_PHASE_DIR/phases/"
rsync -a "$LIVE/bin/" "$WHICK_REMOTE_PHASE_DIR/bin/"
rsync -a "$LIVE/lib/" "$WHICK_REMOTE_PHASE_DIR/lib/"

T5=$SECONDS
bash "$WHICK_REMOTE_PHASE_DIR/phases/02_linux_install.sh" || bash "$LIVE/phases/02_linux_install.sh"
phase_time "phase 5 install_linux"
echo "phase5_elapsed=$((SECONDS - T5))s"

ROOT_PART="$(run_root blkid -L whick-root -o device 2>/dev/null || true)"
[[ -n "$ROOT_PART" && -b "$ROOT_PART" ]] || die "whick-root not found after phase 5"
MUSIC_PART="$(run_root blkid -L whick-music -o device 2>/dev/null || true)"
[[ -n "$MUSIC_PART" ]] && echo "music partition $MUSIC_PART OK"

run_root mkdir -p "$MNT"
run_root mount "$ROOT_PART" "$MNT"
grep -q 'LABEL=whick-root' "$MNT/etc/fstab" || die "fstab missing whick-root"
[[ -f "$MNT/usr/local/sbin/whick-firstboot.sh" ]] || die "firstboot script missing in rootfs"
[[ -f "$MNT/var/lib/whick/bootstrap-session.json" ]] || die "bootstrap session not on SSD"
phase_time "phase 5 verify"

# --- Phase 6~7 (host docker — SSD 첫 부팅 시뮬레이션) ---
T67=$SECONDS
LAB_RUNTIME="$WORK/runtime"
mkdir -p "$LAB_RUNTIME"
tar -I zstd -xf "$LAB_BUNDLE" -C "$LAB_RUNTIME"
cp -f "$PRODUCT/install/runtime/scripts/install-runtime.sh" "$LAB_RUNTIME/scripts/install-runtime.sh"
if [[ ! -f "$LAB_RUNTIME/.env" && -f "$LAB_RUNTIME/.env.example" ]]; then
  cp "$LAB_RUNTIME/.env.example" "$LAB_RUNTIME/.env"
fi
grep -q '^WHICK_DEVICE_SERIAL=' "$LAB_RUNTIME/.env" 2>/dev/null \
  && sed -i "s/^WHICK_DEVICE_SERIAL=.*/WHICK_DEVICE_SERIAL=$LAB_HW_HASH/" "$LAB_RUNTIME/.env" \
  || echo "WHICK_DEVICE_SERIAL=$LAB_HW_HASH" >>"$LAB_RUNTIME/.env"
grep -q '^WHICK_OWNER_MB_ID=' "$LAB_RUNTIME/.env" 2>/dev/null \
  && sed -i "s/^WHICK_OWNER_MB_ID=.*/WHICK_OWNER_MB_ID=$LAB_MB_ID/" "$LAB_RUNTIME/.env" \
  || echo "WHICK_OWNER_MB_ID=$LAB_MB_ID" >>"$LAB_RUNTIME/.env"
grep -q '^WHICK_CC_API_URL=' "$LAB_RUNTIME/.env" 2>/dev/null \
  || echo "WHICK_CC_API_URL=$CC" >>"$LAB_RUNTIME/.env"
echo "runtime credentials → WHICK_DEVICE_SERIAL + WHICK_OWNER_MB_ID"

export COMPOSE_PROJECT_NAME="whick-lab-prod-${LAB_SID}"
LAB_DATA_VOL="${COMPOSE_PROJECT_NAME}_whick-data"

# lab compose override — sample FLAC + ollama model seed volume (before down/teardown)
if [[ -L "$SAMPLE_AUDIO" ]]; then
  SAMPLE_AUDIO_ABS="$(readlink -f "$SAMPLE_AUDIO")"
else
  SAMPLE_AUDIO_ABS="$(cd "$(dirname "$SAMPLE_AUDIO")" && pwd)/$(basename "$SAMPLE_AUDIO")"
fi
[[ -d "$SAMPLE_AUDIO_ABS" ]] || die "sample audio missing: $SAMPLE_AUDIO_ABS"
cat >"$LAB_RUNTIME/compose.override.yaml" <<EOF
services:
  player:
    environment:
      WHICK_LIBRARY_SCAN_PATHS: /var/lib/whick/library/music:/var/lib/whick/library/samples/flac
      WHICK_LIBRARY_SCAN_ON_START: "1"
    volumes:
      - whick-data:/var/lib/whick
  monitor:
    environment:
      WHICK_MONITOR_INTERVAL_SEC: '5'
EOF
if docker volume inspect "$OLLAMA_SEED_VOL" >/dev/null 2>&1 && [[ "${WHICK_LOCAL_AI}" != "0" ]]; then
  cat >>"$LAB_RUNTIME/compose.override.yaml" <<EOF
  ollama:
    container_name: whick-lab-ollama-${LAB_SID}
    volumes:
      - ollama-seed:/root/.ollama
volumes:
  ollama-seed:
    external: true
    name: ${OLLAMA_SEED_VOL}
EOF
  echo "ollama seed volume=$OLLAMA_SEED_VOL (lab container whick-lab-ollama-${LAB_SID})"
fi

echo "==> lab runtime reset (prior agent token / device serial)"
if declare -F lab_remove_runtime_containers >/dev/null 2>&1; then
  lab_remove_runtime_containers
else
  for c in whick-agent whick-monitor whick-player whick-audio whick-docker-proxy whick-player-db; do
    docker rm -f "$c" 2>/dev/null || true
  done
fi
docker compose -f "$LAB_RUNTIME/compose.yaml" -f "$LAB_RUNTIME/compose.override.yaml" down -v --remove-orphans 2>/dev/null || true
if docker volume inspect "$LAB_DATA_VOL" >/dev/null 2>&1; then
  docker run --rm -v "${LAB_DATA_VOL}:/v" alpine sh -c 'rm -f /v/runtime-state.json' 2>/dev/null || true
fi

# volume에 샘플 FLAC 직접 복사 (Docker-in-Docker bind mount 이슈 회피)
if [[ -d "$SAMPLE_AUDIO_ABS/flac" ]]; then
  echo "==> seed sample FLAC into whick-data volume"
  docker volume create "$LAB_DATA_VOL" 2>/dev/null || true
  docker run --rm \
    -v "${LAB_DATA_VOL}:/v" \
    -v "${SAMPLE_AUDIO_ABS}:/samples:ro" \
    alpine sh -c 'mkdir -p /v/library/samples && cp -a /samples/flac /v/library/samples/flac && ls /v/library/samples/flac/ | wc -l'
fi

export WHICK_RUNTIME_ROOT="$LAB_RUNTIME"
export WHICK_INSTALL_CACHE="$WORK/cache"
export WHICK_COMPONENTS_LOCK="$LAB_RUNTIME/components.lock.json"
export WHICK_LOCAL_AI="${WHICK_LOCAL_AI:-0}"
mkdir -p "$WHICK_INSTALL_CACHE"

grep -q '^OLLAMA_URL=' "$LAB_RUNTIME/.env" 2>/dev/null || echo 'OLLAMA_URL=http://ollama:11434' >>"$LAB_RUNTIME/.env"
grep -q '^OLLAMA_MODEL=' "$LAB_RUNTIME/.env" 2>/dev/null || echo 'OLLAMA_MODEL=gemma4:e2b' >>"$LAB_RUNTIME/.env"
grep -q '^WHICK_LOCAL_AI=' "$LAB_RUNTIME/.env" 2>/dev/null || echo "WHICK_LOCAL_AI=${WHICK_LOCAL_AI}" >>"$LAB_RUNTIME/.env"
lab_patch_runtime_env_file "$LAB_RUNTIME/.env"
export WHICK_RUNTIME_FORCE_RECREATE="${WHICK_RUNTIME_FORCE_RECREATE:-1}"

# lab library scan — include sample FLAC mount
if grep -q '^WHICK_LIBRARY_SCAN_PATHS=' "$LAB_RUNTIME/.env" 2>/dev/null; then
  sed -i 's|^WHICK_LIBRARY_SCAN_PATHS=.*|WHICK_LIBRARY_SCAN_PATHS=/var/lib/whick/library/music:/var/lib/whick/library/samples/flac|' "$LAB_RUNTIME/.env"
else
  echo 'WHICK_LIBRARY_SCAN_PATHS=/var/lib/whick/library/music:/var/lib/whick/library/samples/flac' >>"$LAB_RUNTIME/.env"
fi
export WHICK_LIBRARY_SCAN_PATHS="/var/lib/whick/library/music:/var/lib/whick/library/samples/flac"

if [[ "${WHICK_LOCAL_AI}" != "0" ]] && docker ps --format '{{.Names}}' | grep -qx whick-ollama; then
  echo "WARN: WHICK_LOCAL_AI=1 — 운영 whick-ollama는 lab에서 교체하지 않음 (host Ollama 사용)"
fi

bash "$LAB_RUNTIME/scripts/install-docker.sh"
touch "$PHASE_DIR/docker_done"
phase_time "phase 6 docker"

bash "$LAB_RUNTIME/scripts/install-runtime.sh"
touch "$PHASE_DIR/runtime_done"
touch "$PHASE_DIR/install_complete"
phase_time "phase 7 runtime"

ensure_player_schema() {
  local init="$LAB_RUNTIME/remote/api/init.sql"
  [[ -f "$init" ]] || die "missing player init.sql: $init"
  if ! docker exec whick-player-db psql -U whick -d whickdb -tAc "SELECT to_regclass('public.tracks')" 2>/dev/null | grep -q tracks; then
    echo "==> apply player DB schema (init.sql)"
    docker exec -i whick-player-db psql -U whick -d whickdb <"$init"
  fi
}
ensure_player_schema

# chroot 검증 — 배포된 rootfs에 runtime 마커·세션 유지
if mountpoint -q "$MNT"; then run_root umount "$MNT" 2>/dev/null || true; fi
run_root mount "$ROOT_PART" "$MNT"
[[ -f "$MNT/var/lib/whick/bootstrap-session.json" ]] || die "bootstrap session lost"
run_root umount "$MNT"

docker compose -f "$LAB_RUNTIME/compose.yaml" -f "$LAB_RUNTIME/compose.override.yaml" ps --format '{{.Name}}:{{.Status}}' 2>/dev/null | head -12 || true

echo "==> verify whick-player stable (no schema race restart)"
player_status="$(docker inspect whick-player --format '{{.State.Status}}' 2>/dev/null || echo missing)"
player_restarts="$(docker inspect whick-player --format '{{.RestartCount}}' 2>/dev/null || echo 99)"
if [[ "$player_status" != "running" ]] || [[ "${player_restarts:-99}" -gt 0 ]]; then
  die "whick-player unstable status=${player_status} restartCount=${player_restarts} (check player-db schema / init.sql)"
fi
ok_player_stable=1

# --- Phase 8: player + local AI ---
TAI=$SECONDS
PLAYER_URL="${WHICK_PLAYER_URL:-http://127.0.0.1:8080}"
echo "==> wait player /health"
ready=0
for i in $(seq 1 90); do
  if curl -fsS --max-time 5 "$PLAYER_URL/health" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 2
done
[[ "$ready" -eq 1 ]] || die "player health timeout"

echo "==> trigger library scan"
curl -fsS --max-time 30 -X POST "$PLAYER_URL/api/library/scan" >/tmp/whick-lab-scan-result.json 2>/dev/null || true
echo "==> wait library scan (sample FLAC)"
lib_ok=0
for i in $(seq 1 60); do
  curl -fsS --max-time 10 "$PLAYER_URL/api/library/status" >/tmp/whick-lab-lib.json 2>/dev/null || true
  lib_ok=$(python3 -c "import json; d=json.load(open('/tmp/whick-lab-lib.json')); print('1' if int(d.get('total_tracks') or 0)>=1 else '0')" 2>/dev/null || echo 0)
  [[ "$lib_ok" == "1" ]] && break
  sleep 3
done


if [[ "${WHICK_LOCAL_AI}" != "0" ]]; then
  echo "==> wait Ollama + gemma4:e2b"
  ai_ok=0
  for i in $(seq 1 120); do
    ai_ok=$(curl -fsS --max-time 10 "$PLAYER_URL/api/dashboard" 2>/dev/null \
      | python3 -c "import json,sys; d=json.load(sys.stdin); print('1' if d.get('ai',{}).get('ok') else '0')" 2>/dev/null || echo 0)
    if [[ "$ai_ok" == "1" ]]; then break; fi
    if [[ "$i" -eq 30 ]] && docker ps --format '{{.Names}}' | grep -qx whick-ollama; then
      docker compose -f "$LAB_RUNTIME/compose.yaml" -f "$LAB_RUNTIME/compose.override.yaml" \
        exec -T ollama ollama pull gemma4:e2b >/dev/null 2>&1 &
    fi
    sleep 3
  done
  [[ "$ai_ok" == "1" ]] || die "Ollama AI not ready (dashboard ai.ok=false)"

  QUERY=$(python3 -c "import urllib.parse; print(urllib.parse.quote('잔잔한 피아노'))")
  curl -fsS --max-time 120 "$PLAYER_URL/api/ai-search?q=$QUERY" >/tmp/whick-lab-ai-search.json \
    || die "GET /api/ai-search failed"
  python3 - <<'PY'
import json
with open("/tmp/whick-lab-ai-search.json") as f:
    d = json.load(f)
assert d.get("ai", {}).get("ok") is True, d.get("ai")
print(f"  ai-search ok query={d.get('query')!r}")
PY
  phase_time "phase 8 local AI"
  echo "phase8_elapsed=$((SECONDS - TAI))s"
fi

curl -fsS --max-time 60 "$PLAYER_URL/api/library/status" >/tmp/whick-lab-lib.json \
  || die "GET /api/library/status failed"
python3 - <<'PY'
import json
with open("/tmp/whick-lab-lib.json") as f:
    d = json.load(f)
total = int(d.get("total_tracks") or 0)
assert total >= 200, f"expected >=200 tracks, got {total}: {d}"
print(f"  library tracks={total}")
PY

# --- Phase 9: library robots (검수 + 분류) ---
TROB=$SECONDS
if [[ "${WHICK_LAB_SKIP_ROBOTS:-1}" != "1" ]]; then
  echo "==> phase 9 library robots (robot-auditor + robot-classifier)"
  export LAB_HW_HASH LAB_DEVICE_ID LAB_MB_ID
  bash "$ROOT/scripts/test-lab-library-robots.sh" "$LAB_RUNTIME"
  phase_time "phase 9 library robots"
  echo "phase9_elapsed=$((SECONDS - TROB))s"
else
  echo "==> phase 9 library robots SKIPPED (WHICK_LAB_SKIP_ROBOTS=1)"
fi

# persist log (host-writable path)
PERSIST_ROOT="${WHICK_LAB_PERSIST:-/whick-lab/runs}"
PERSIST="$PERSIST_ROOT/lab-prod-e2e-$(date +%Y%m%d-%H%M%S)"
if mkdir -p "$PERSIST" 2>/dev/null; then
  cp -a "$LOG" "$PERSIST/e2e.log"
  cp -a "$PHASE_DIR/disk_plan.json" "$PERSIST/" 2>/dev/null || true
  echo "persist=$PERSIST"
else
  echo "persist=skipped (read-only: $PERSIST_ROOT)"
fi

TOTAL=$(( $(date +%s) - START_TS ))
P5=$((T67 - T5))
P67=$((SECONDS - T67))
P8=0
P9=0
[[ "${WHICK_LOCAL_AI}" != "0" ]] && P8=$((SECONDS - TAI))
[[ "${WHICK_LAB_SKIP_ROBOTS:-0}" != "1" ]] && P9=$((SECONDS - TROB))
report_lab_session_phase post_install_verify "lab E2E operation verification passed"
report_lab_session_phase complete "lab E2E complete"
echo ""
echo "========================================"
echo " OK  lab prod E2E (+ local AI + library robots)"
echo "  total_wall=${TOTAL}s  phase5=${P5}s  phase6-7=${P67}s  phase8=${P8}s  phase9=${P9}s"
echo "  session=$LAB_SID $LAB_CODE"
echo "  log=$LOG"
echo "========================================"
