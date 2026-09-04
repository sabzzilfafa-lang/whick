#!/usr/bin/env bash
# Phase 7 — runtime 번들 배포 · docker load(오프라인) · compose up (pull 금지)
set -euo pipefail

RUNTIME_ROOT="${WHICK_RUNTIME_ROOT:-/opt/whick/runtime}"
CACHE="${WHICK_INSTALL_CACHE:-/var/lib/whick/install-cache}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Docker와 동일 — 미니PC에 없는 서버 경로(/data/whick-ai/…)를 lock으로 쓰지 않음
_resolve_runtime_lock() {
  local candidate
  for candidate in \
    "${WHICK_COMPONENTS_LOCK:-}" \
    "${WHICK_REMOTE_PHASE_ROOT:-}/lib/components.lock.json" \
    "/var/lib/whick/remote-phases/lib/components.lock.json" \
    "$SCRIPT_DIR/../lib/components.lock.json" \
    "$RUNTIME_ROOT/components.lock.json"; do
    [[ -n "$candidate" && -f "$candidate" ]] && { echo "$candidate"; return 0; }
  done
  return 1
}
LOCK_SRC="$(_resolve_runtime_lock || true)"
# shellcheck source=/dev/null
. "$SCRIPT_DIR/whick-dual-install-common.sh"

log() { echo "[install-runtime] $*"; }
if [[ -n "$LOCK_SRC" ]]; then
  log "using components lock: $LOCK_SRC"
else
  log "WARN: no local components.lock.json — CC runtime meta required"
fi

report_runtime_progress() {
  local pct="$1" msg="$2"
  local reporter=""
  for candidate in \
    "${WHICK_REMOTE_PHASE_ROOT:-}/bin/cc_progress.py" \
    "$SCRIPT_DIR/cc_progress.py" \
    "$SCRIPT_DIR/../bin/cc_progress.py"; do
    if [[ -f "$candidate" ]]; then
      reporter="$candidate"
      break
    fi
  done
  if [[ -n "$reporter" ]]; then
    python3 "$reporter" --phase install_runtime --pct "$pct" --msg "$msg" 2>/dev/null || true
  fi
  log "$msg"
}

configure_usb_dac_hotplug() {
  mkdir -p /etc/udev/rules.d
  # USB DAC hot-plug — 드라이버를 미리 로드하지 않고, DAC 연결 시에만 udev로 로드.
  # 부트 시 DAC가 이미 연결돼 있으면 systemd-udev-trigger가 자동 처리한다.
  # 고객이 DAC를 바꿔 꽂아도 컨테이너 재시작 없이 즉시 재탐지된다
  # (compose.override: /dev/snd bind mount + ALSA major 116 cgroup).
  cat >/etc/udev/rules.d/99-whick-usb-dac.rules <<'EOF'
# USB Audio Class 장치 연결 시 snd-usb-audio 자동 로드
ACTION=="add", SUBSYSTEM=="usb", ENV{PRODUCT}=="*/*/*", RUN+="/bin/sh -c 'cat /sys$devpath/bInterfaceClass 2>/dev/null | grep -qx 01 && /sbin/modprobe snd-usb-audio || true'"
# USB 오디오 장치 제거 시 ALSA 카드 재탐지 (camilla-pipe가 다음 재생 시 새 카드를 찾음)
ACTION=="remove", SUBSYSTEM=="usb", ENV{PRODUCT}=="*/*/*", RUN+="/bin/sh -c 'cat /sys$devpath/bInterfaceClass 2>/dev/null | grep -qx 01 && udevadm trigger --subsystem-match=sound || true'"
EOF
  udevadm control --reload-rules >/dev/null 2>&1 || true
  udevadm trigger --subsystem-match=usb >/dev/null 2>&1 || true  # cold-plug: 이미 꽂힌 DAC 인식

  log "USB DAC hot-plug policy installed"
}
configure_usb_dac_hotplug

configure_usb_storage_automount() {
  # USB 스토리지 자동마운트 — 리모트포털 탐색기·라이브러리 추가용 (2026-09-02).
  # Whick OS는 데스크톱이 없어 udisks2 자동마운트가 없음 → udev block rule로 마운트.
  # - 마운트 위치: /media/whick-usb-<디스크명> (플레이어 감지 경로 /media/*·/run/media/* 와 일치)
  # - vfat/exFat/ntfs/UTF-8: 한글 파일명 안전 (iocharset·codepage 지정)
  # - 제거 시 sync 후 언마운트 (데이터 손상 방지)
  # - 루트파일시스템·음악파티션은 제외 (device pattern으로 sda1 등 비-시스템 파티션만)
  mkdir -p /usr/local/lib/whick /etc/udev/rules.d
  cat >/usr/local/lib/whick/whick-usb-mount.sh <<'MOUNTEOF'
#!/bin/sh
# Whick USB storage auto-mount helper (called by udev)
ACTION="$1"; DEVNAME="$2"
LOG_TAG="whick-usb-mount"
log() { echo "$(date -Iseconds) [${LOG_TAG}] $*" >> /var/log/whick-usb.log 2>/dev/null || true; }
[ -n "$DEVNAME" ] || exit 0
case "$DEVNAME" in
  /dev/sd*[0-9]|/dev/nvme*n*p[0-9]) ;;   # 파티션만
  *) exit 0 ;;
esac
# 시스템·음악·부트 파티션 제외 (whick-data 위치 보호)
MUSIC_DEV="$(findmnt -n -o SOURCE /mnt/music 2>/dev/null | head -1)"
ROOT_DEV="$(findmnt -n -o SOURCE / 2>/dev/null | sed 's/\[.*\]$//')"
BOOT_DEV="$(findmnt -n -o SOURCE /boot/efi 2>/dev/null | head -1)"
if [ "$DEVNAME" = "$ROOT_DEV" ] || [ "$DEVNAME" = "$MUSIC_DEV" ] || [ "$DEVNAME" = "$BOOT_DEV" ]; then
  log "skip system partition: $DEVNAME"; exit 0
fi
# 같은 디스크의 시스템 파티션(root·music·boot와 같은 디스크)은 전부 제외 — 외장 USB만 대상.
DISK_OF_ROOT="$(echo "$ROOT_DEV" | sed 's/p*[0-9]*$//')"
DISK_OF_MUSIC="$(echo "$MUSIC_DEV" | sed 's/p*[0-9]*$//')"
DISK_OF_BOOT="$(echo "$BOOT_DEV" | sed 's/p*[0-9]*$//')"
DISK_OF_DEV="$(echo "$DEVNAME" | sed 's/p*[0-9]*$//')"
if [ "$DISK_OF_DEV" = "$DISK_OF_ROOT" ] || [ "$DISK_OF_DEV" = "$DISK_OF_MUSIC" ] || [ "$DISK_OF_DEV" = "$DISK_OF_BOOT" ]; then
  log "skip system disk partition: $DEVNAME"; exit 0
fi
BASENAME="$(basename "$DEVNAME")"
MOUNT="/media/whick-usb-${BASENAME}"
case "$ACTION" in
  add)
    mkdir -p "$MOUNT"
    # 이미 마운트된 경우 건너뜀 (player 컨테이너 ro-bind와 충돌 방지)
    if mountpoint -q "$MOUNT"; then log "already mounted: $MOUNT"; exit 0; fi
    FSTYPE="$(lsblk -no FSTYPE "/dev/${BASENAME}" 2>/dev/null | head -1)"
    case "$FSTYPE" in
      vfat) OPTS="rw,uid=1000,gid=1000,umask=000,shortname=mixed,utf8=1,codepage=949" ;;
      exfat) OPTS="rw,uid=1000,gid=1000,umask=000" ;;
      ntfs|ntfs3) OPTS="rw,uid=1000,gid=1000,umask=000" ;;
      "") log "no fstype: $BASENAME"; exit 0 ;;
      *) OPTS="rw" ;;
    esac
    if mount -t "$FSTYPE" -o "$OPTS" "/dev/${BASENAME}" "$MOUNT" 2>>/var/log/whick-usb.log; then
      log "mounted /dev/${BASENAME} → $MOUNT ($FSTYPE)"
      chmod 777 "$MOUNT" 2>/dev/null || true
    else
      log "mount FAILED /dev/${BASENAME} ($FSTYPE)"
      rmdir "$MOUNT" 2>/dev/null || true
    fi
    ;;
  remove)
    if mountpoint -q "$MOUNT"; then
      sync; umount "$MOUNT" 2>/dev/null; rmdir "$MOUNT" 2>/dev/null || true
      log "unmounted $MOUNT"
    fi
    ;;
esac
exit 0
MOUNTEOF
  chmod 755 /usr/local/lib/whick/whick-usb-mount.sh
  cat >/etc/udev/rules.d/99-whick-usb-storage.rules <<'EOF'
# Whick USB storage auto-mount (리모트포털 라이브러리 추가용)
# udevd는 격리 네임스페이스에서 mount 권한이 없어 permission denied 발생 →
# systemd-run으로 PID1(systemd)이 마운트를 대신 실행하게 한다 (2026-09-02 미니PC 실증).
ACTION=="add|change", KERNEL=="sd[a-z][0-9]*|nvme*n*p[0-9]*", SUBSYSTEM=="block", ENV{ID_FS_USAGE}=="filesystem", RUN+="/usr/bin/systemd-run --no-block --unit=whick-usb-mount-%k /usr/local/lib/whick/whick-usb-mount.sh add /dev/%k"
ACTION=="remove", KERNEL=="sd[a-z][0-9]*|nvme*n*p[0-9]*", SUBSYSTEM=="block", RUN+="/usr/bin/systemd-run --no-block --unit=whick-usb-umount-%k /usr/local/lib/whick/whick-usb-mount.sh remove /dev/%k"
EOF
  udevadm control --reload-rules >/dev/null 2>&1 || true
  udevadm trigger --subsystem-match=block >/dev/null 2>&1 || true  # cold-plug: 이미 꽂힌 USB 인식
  log "USB storage automount policy installed"
}

# 컨테이너(docker:27-cli 등)에서 실행되면 /etc가 컨테이너 안에 생겨 소멸됨(--rm).
# → nsenter로 미니PC "호스트"에 직접 설치한다 (runtime_reinstall/OTA에서도 적용되도록).
# 어떤 실패도 재설치를 죽이지 않는다 — 항상 rc=0으로 복귀 (오류는 state 로그에만 기록).
install_usb_automount_on_host() {
  command -v docker >/dev/null 2>&1 || { log "skip USB automount (no docker)"; return 0; }
  log "install USB automount on host (nsenter)"
  local payload
  payload="$(sed -n "/^configure_usb_storage_automount()/,/^}/p" "$0"; echo configure_usb_storage_automount)"
  {
    docker run --rm --privileged --pid=host -i ubuntu:26.04 sh -c '
      nsenter -t 1 -m -u -i -n -p sh -c "cat > /tmp/whick-usb-mount-install.sh"
      nsenter -t 1 -m -u -i -n -p sh /tmp/whick-usb-mount-install.sh
    ' <<WHICK_USB_PAYLOAD
$payload
WHICK_USB_PAYLOAD
    echo "USB automount nsenter install rc=$?"
  } >>/var/lib/whick/usb-automount-install.log 2>&1 || log "WARN host USB automount install failed (see usb-automount-install.log)"
  return 0
}

install_usb_automount_on_host

install_hardware_health_probe() {
  local probe_src="$SCRIPT_DIR/whick-hardware-health.py"
  [[ -f "$probe_src" ]] || { log "WARN hardware health probe missing: $probe_src"; return 0; }
  # docker:27-cli sibling 등 systemd 없는 환경에서는 건너뛴다 (runtime compose 재설치는 계속)
  if [[ "${WHICK_SKIP_HOST_PROBES:-0}" == "1" ]] \
    || [[ ! -d /etc/systemd/system ]] \
    || ! command -v systemctl >/dev/null 2>&1; then
    log "WARN skip hardware health probe (no host systemd)"
    return 0
  fi

  if ! command -v smartctl >/dev/null 2>&1 \
    && [[ "${WHICK_SKIP_ONLINE_INSTALL:-0}" != "1" ]] \
    && command -v apt-get >/dev/null 2>&1; then
    log "smartmontools install attempt (SSD SMART hours)"
    timeout 120 apt-get update -qq >/dev/null 2>&1 \
      && timeout 120 apt-get install -y -qq smartmontools >/dev/null 2>&1 \
      || log "WARN smartmontools unavailable — SSD hours will show unavailable"
  fi

  install -d -m 0755 /usr/local/lib/whick /var/lib/whick/run
  install -m 0755 "$probe_src" /usr/local/lib/whick/whick-hardware-health.py
  cat >/etc/systemd/system/whick-hardware-health.service <<'EOF'
[Unit]
Description=Whick host hardware health snapshot
After=local-fs.target

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /usr/local/lib/whick/whick-hardware-health.py
EOF
  cat >/etc/systemd/system/whick-hardware-health.timer <<'EOF'
[Unit]
Description=Refresh Whick host hardware health snapshot

[Timer]
OnBootSec=30s
OnUnitActiveSec=15min
AccuracySec=1min
Persistent=true

[Install]
WantedBy=timers.target
EOF
  systemctl daemon-reload
  systemctl enable --now whick-hardware-health.timer >/dev/null 2>&1 || true
  systemctl start whick-hardware-health.service >/dev/null 2>&1 || true
  log "host hardware health probe installed"
}
install_hardware_health_probe

read_lock_field() {
  local field="$1"
  [[ -n "$LOCK_SRC" && -f "$LOCK_SRC" ]] || return 1
  python3 - <<PY "$field" "$LOCK_SRC"
import json, sys, pathlib
field = sys.argv[1]
p = pathlib.Path(sys.argv[2])
if not p.is_file():
    sys.exit(1)
data = json.load(open(p))
components = data.get("components") or {}
bundle = components.get("runtime_bundle") or {}
docker_ce = components.get("docker_ce") or {}
images = components.get("images") or {}
models = components.get("models") or {}
if field == "bundle_file":
    print(bundle.get("file") or "")
elif field == "bundle_sha":
    print(bundle.get("sha256") or "")
elif field == "deb_bundle":
    print(docker_ce.get("deb_bundle") or "")
elif field == "images":
    import json as j
    print(j.dumps(images))
elif field == "models":
    import json as j
    print(j.dumps(models))
elif field == "version":
    print(data.get("version") or "")
PY
}

# CC가 서빙하는 최신 runtime 번들 메타(sha·file) — bootstrap 토큰으로 조회.
# USB에 구워진 옛 번들/lock(sha 불일치)을 SSD 캐시가 그대로 쓰는 악순환을 끊는다.
fetch_cc_runtime_meta() {
  command -v python3 >/dev/null 2>&1 || return 0
  local session="" p
  for p in "${WHICK_BOOTSTRAP_SESSION:-}" /var/lib/whick/bootstrap-session.json /tmp/whick-bootstrap-session.json; do
    if [[ -n "$p" && -f "$p" ]]; then session="$p"; break; fi
  done
  [[ -n "$session" ]] || return 0
  local cc_base="${WHICK_CC_API_URL:-https://admin.whick.org/api/v1}"
  python3 - "$session" "$cc_base" <<'PY' || true
import json, sys, urllib.request
sess, cc = sys.argv[1], sys.argv[2].rstrip("/")
try:
    data = json.load(open(sess))
except Exception:
    raise SystemExit(0)
token = data.get("bootstrap_token") or data.get("token") or ""
if not token:
    raise SystemExit(0)
req = urllib.request.Request(
    cc + "/install/bootstrap/runtime-bundle/meta",
    headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
)
try:
    with urllib.request.urlopen(req, timeout=20) as r:
        resp = json.loads(r.read().decode("utf-8", errors="replace"))
except Exception as e:
    print(f"[install-runtime] CC runtime meta fetch failed: {e}", file=sys.stderr)
    raise SystemExit(0)
inner = resp.get("data") if isinstance(resp.get("data"), dict) else resp
if not isinstance(inner, dict):
    print("[install-runtime] CC runtime meta: unexpected response", file=sys.stderr)
    raise SystemExit(0)
sha = str(inner.get("sha256") or "").strip()
f = str(inner.get("file") or "").strip()
if not f:
    err = resp.get("error") if isinstance(resp, dict) else None
    print(f"[install-runtime] CC runtime meta empty file err={err}", file=sys.stderr)
    raise SystemExit(0)
print(f"{sha}\t{f}")
PY
}

ensure_runtime_tree() {
  # compose.yaml 만으로 조기 종료하면 init.sql 누락된 옛 번들이 그대로 남아
  # player 스키마 생성이 실패한다 — 핵심 산출물(init.sql)까지 있어야 완전 추출로 간주.
  if [[ -f "$RUNTIME_ROOT/compose.yaml" && -f "$RUNTIME_ROOT/remote/api/init.sql" ]]; then
    return 0
  fi
  local bundle_file bundle_sha
  bundle_file="$(read_lock_field bundle_file 2>/dev/null || true)"
  bundle_sha="$(read_lock_field bundle_sha 2>/dev/null || true)"
  # CC 메타가 authoritative — 로컬 lock(USB 옛 값)보다 우선해 캐시 검증·다운로드.
  local cc_meta cc_sha cc_file
  cc_meta="$(fetch_cc_runtime_meta 2>/dev/null || true)"
  cc_sha="$(printf '%s' "$cc_meta" | cut -f1)"
  cc_file="$(printf '%s' "$cc_meta" | cut -f2)"
  if [[ "$cc_sha" =~ ^[0-9a-fA-F]{64}$ ]]; then
    bundle_sha="$cc_sha"
    log "CC runtime meta sha=${cc_sha:0:16}…"
  fi
  [[ -n "$cc_file" ]] && bundle_file="$cc_file"
  [[ -n "$bundle_file" ]] || bundle_file="$(read_lock_field bundle_file 2>/dev/null || true)"
  [[ -n "$bundle_file" ]] || {
    log "FATAL: runtime_bundle.file missing (lock + CC meta empty)"
    return 1
  }

  local tar_path="$CACHE/$bundle_file"
  mkdir -p "$CACHE" "$RUNTIME_ROOT"

  if [[ -f "$tar_path" && -n "$bundle_sha" ]] && ! verify_file_sha256 "$tar_path" "$bundle_sha"; then
    log "stale runtime bundle removed (sha mismatch)"
    rm -f "$tar_path"
  fi

  if [[ ! -f "$tar_path" ]]; then
    report_runtime_progress 22 "runtime 번들 다운로드 중…"
    local cc_base="${WHICK_CC_API_URL:-https://admin.whick.org/api/v1}"
    "$SCRIPT_DIR/whick-fetch-artifact.sh" \
      --name "$bundle_file" \
      --dest "$tar_path" \
      ${bundle_sha:+--sha256 "$bundle_sha"} \
      --url "$cc_base/install/bootstrap/runtime-bundle" \
      || "$SCRIPT_DIR/whick-fetch-artifact.sh" \
        --name "$bundle_file" \
        --dest "$tar_path" \
        ${bundle_sha:+--sha256 "$bundle_sha"}
  fi

  # ensure zstd is available (base rootfs should have it, but guard just in case)
  if ! command -v zstd >/dev/null 2>&1; then
    log "zstd not found — installing…"
    apt-get update -qq && apt-get install -y -qq zstd || {
      log "FATAL: cannot install zstd — runtime extraction impossible"
      exit 1
    }
  fi

  log "extract $tar_path → $RUNTIME_ROOT"
  report_runtime_progress 28 "runtime 번들 압축 해제 중…"
  case "$tar_path" in
    *.tar.zst) tar -I zstd -xf "$tar_path" -C "$RUNTIME_ROOT" ;;
    *.tar.gz|*.tgz) tar -xzf "$tar_path" -C "$RUNTIME_ROOT" ;;
    *) log "unknown bundle format"; exit 1 ;;
  esac

  # The archive cannot embed its own final sha256 without a circular hash.
  # Replace its build-time lock with the authoritative phase/CC lock after
  # extraction so future reinstall/update runs never retain an old contract.
  if [[ -n "$LOCK_SRC" && -f "$LOCK_SRC" ]]; then
    install -m 0644 "$LOCK_SRC" "$RUNTIME_ROOT/components.lock.json"
    log "authoritative components lock installed after extraction"
  fi
}

ensure_runtime_tree
report_runtime_progress 35 "runtime 구성 확인 중…"

WHICK_LOCAL_AI_FROM_ENV="${WHICK_LOCAL_AI-}"

if [[ ! -f "$RUNTIME_ROOT/.env" && -f "$RUNTIME_ROOT/.env.example" ]]; then
  cp "$RUNTIME_ROOT/.env.example" "$RUNTIME_ROOT/.env"
  # Retail bundle ships 0.0.0.0 bind; legacy bundles may still have localhost-only.
  if grep -q '^WHICK_PLAYER_PORT_BIND=127\.0\.0\.1:8080' "$RUNTIME_ROOT/.env" 2>/dev/null; then
    sed -i 's|^WHICK_PLAYER_PORT_BIND=127\.0\.0\.1:8080|WHICK_PLAYER_PORT_BIND=0.0.0.0:8080|' "$RUNTIME_ROOT/.env"
    log "WHICK_PLAYER_PORT_BIND=0.0.0.0:8080 — customer LAN remote API"
  fi
fi
# LAN: http://IP/ (port 80) → player. Apply even when .env already existed.
# (OTA 경로도 docker-ops에서 동일 키를 넣음 — 여기 SSOT는 install·재설치)
if [[ -f "$RUNTIME_ROOT/.env" ]]; then
  if grep -qE '^WHICK_PLAYER_PORT_BIND=0\.0\.0\.0:' "$RUNTIME_ROOT/.env" 2>/dev/null; then
    if grep -q '^WHICK_PLAYER_PORT80_BIND=' "$RUNTIME_ROOT/.env" 2>/dev/null; then
      sed -i 's|^WHICK_PLAYER_PORT80_BIND=.*|WHICK_PLAYER_PORT80_BIND=0.0.0.0:80|' "$RUNTIME_ROOT/.env"
    else
      printf '\nWHICK_PLAYER_PORT80_BIND=0.0.0.0:80\n' >>"$RUNTIME_ROOT/.env"
    fi
    log "WHICK_PLAYER_PORT80_BIND=0.0.0.0:80 — LAN IP-only remote UI"
  fi
  # 설치 버전 stamp — .env.example placeholder(v0.1.0-dev)가 그대로 CC에 등록되어
  # 신규 설치 장비가 v0.1.0-dev로 보이던 버그 방지. lock version = 실제 설치 번들 버전.
  # (OTA 경로는 docker-ops가 target 버전을 동일 키에 기록 — 여기 SSOT는 install·재설치)
  _lock_version="$(read_lock_field version 2>/dev/null || true)"
  if [[ "$_lock_version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+ ]]; then
    if grep -q '^WHICK_SOFTWARE_VERSION=' "$RUNTIME_ROOT/.env" 2>/dev/null; then
      sed -i "s|^WHICK_SOFTWARE_VERSION=.*|WHICK_SOFTWARE_VERSION=${_lock_version}|" "$RUNTIME_ROOT/.env"
    else
      printf '\nWHICK_SOFTWARE_VERSION=%s\n' "$_lock_version" >>"$RUNTIME_ROOT/.env"
    fi
    log "WHICK_SOFTWARE_VERSION=${_lock_version} (components.lock)"
  else
    log "WARN: lock version 없음 — WHICK_SOFTWARE_VERSION stamp 생략"
  fi
  set -a
  # shellcheck source=/dev/null
  source "$RUNTIME_ROOT/.env"
  set +a
fi
if [[ -n "$WHICK_LOCAL_AI_FROM_ENV" ]]; then
  export WHICK_LOCAL_AI="$WHICK_LOCAL_AI_FROM_ENV"
fi

ensure_customer_cc_api_url() {
  [[ -f "$RUNTIME_ROOT/.env" ]] || return 0
  local cc_url="${WHICK_CC_API_URL:-}"
  if [[ -f /etc/default/whick-cc ]]; then
    # shellcheck source=/dev/null
    . /etc/default/whick-cc
    cc_url="${WHICK_CC_API_URL:-$cc_url}"
  fi
  cc_url="${cc_url:-https://admin.whick.org/api/v1}"
  if [[ "${WHICK_PROD_INSTALL:-1}" == "1" && "$cc_url" == *127.0.0.1* ]]; then
    cc_url="https://admin.whick.org/api/v1"
  fi
  if grep -q '^WHICK_CC_API_URL=' "$RUNTIME_ROOT/.env" 2>/dev/null; then
    sed -i "s|^WHICK_CC_API_URL=.*|WHICK_CC_API_URL=${cc_url}|" "$RUNTIME_ROOT/.env"
  else
    echo "WHICK_CC_API_URL=${cc_url}" >>"$RUNTIME_ROOT/.env"
  fi
  export WHICK_CC_API_URL="$cc_url"
  log "WHICK_CC_API_URL=${cc_url}"
}
ensure_customer_cc_api_url

# AI 날씨: 기존 .env 에 키가 비어 있으면 번들 .env.example 값을 채움
# (OTA 시 .env 보존만 하면 KMA 키가 영구 누락 → Open-Meteo ~30°C 고착)
ensure_customer_kma_weather_env() {
  [[ -f "$RUNTIME_ROOT/.env" ]] || return 0
  local example="$RUNTIME_ROOT/.env.example"
  local key="" base="" prov=""

  _kma_read_key() {
    local f="$1" k="$2"
    [[ -f "$f" ]] || return 0
    grep -E "^${k}=" "$f" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '\r' || true
  }

  key="$(_kma_read_key "$RUNTIME_ROOT/.env" WHICK_KMA_SERVICE_KEY)"
  if [[ -z "$key" && -f "$example" ]]; then
    key="$(_kma_read_key "$example" WHICK_KMA_SERVICE_KEY)"
  fi
  base="$(_kma_read_key "$RUNTIME_ROOT/.env" WHICK_KMA_BASE_URL)"
  if [[ -z "$base" && -f "$example" ]]; then
    base="$(_kma_read_key "$example" WHICK_KMA_BASE_URL)"
  fi
  base="${base:-https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0}"
  prov="$(_kma_read_key "$RUNTIME_ROOT/.env" WHICK_WEATHER_PROVIDER)"
  if [[ -z "$prov" && -f "$example" ]]; then
    prov="$(_kma_read_key "$example" WHICK_WEATHER_PROVIDER)"
  fi
  prov="${prov:-kma}"

  if [[ -n "$key" ]]; then
    if grep -q '^WHICK_KMA_SERVICE_KEY=' "$RUNTIME_ROOT/.env" 2>/dev/null; then
      sed -i "s|^WHICK_KMA_SERVICE_KEY=.*|WHICK_KMA_SERVICE_KEY=${key}|" "$RUNTIME_ROOT/.env"
    else
      echo "WHICK_KMA_SERVICE_KEY=${key}" >>"$RUNTIME_ROOT/.env"
    fi
  fi
  if grep -q '^WHICK_KMA_BASE_URL=' "$RUNTIME_ROOT/.env" 2>/dev/null; then
    sed -i "s|^WHICK_KMA_BASE_URL=.*|WHICK_KMA_BASE_URL=${base}|" "$RUNTIME_ROOT/.env"
  else
    echo "WHICK_KMA_BASE_URL=${base}" >>"$RUNTIME_ROOT/.env"
  fi
  if grep -q '^WHICK_WEATHER_PROVIDER=' "$RUNTIME_ROOT/.env" 2>/dev/null; then
    sed -i "s|^WHICK_WEATHER_PROVIDER=.*|WHICK_WEATHER_PROVIDER=${prov}|" "$RUNTIME_ROOT/.env"
  else
    echo "WHICK_WEATHER_PROVIDER=${prov}" >>"$RUNTIME_ROOT/.env"
  fi
  if [[ -n "$key" ]]; then
    log "WHICK_KMA weather env ready (provider=${prov})"
  else
    log "WARN: WHICK_KMA_SERVICE_KEY empty — Open-Meteo fallback only"
  fi
}
ensure_customer_kma_weather_env

ensure_customer_streaming_env() {
  [[ -f "$RUNTIME_ROOT/.env" ]] || return 0
  [[ "${WHICK_DISABLE_EXTERNAL_PROVIDERS:-0}" == "1" ]] && return 0

  # Spotify/Tidal are customer paid-account connections in the remote UI.
  # Provider app/client settings are system-managed and must not be presented as customer API keys.
  if grep -q '^WHICK_PLAYER_EXTERNAL_PROVIDERS=' "$RUNTIME_ROOT/.env" 2>/dev/null; then
    sed -i 's|^WHICK_PLAYER_EXTERNAL_PROVIDERS=.*|WHICK_PLAYER_EXTERNAL_PROVIDERS=1|' "$RUNTIME_ROOT/.env"
  else
    echo 'WHICK_PLAYER_EXTERNAL_PROVIDERS=1' >>"$RUNTIME_ROOT/.env"
  fi
  if grep -q '^WHICK_LIBRESPOT_AUTOSTART=' "$RUNTIME_ROOT/.env" 2>/dev/null; then
    sed -i 's|^WHICK_LIBRESPOT_AUTOSTART=.*|WHICK_LIBRESPOT_AUTOSTART=1|' "$RUNTIME_ROOT/.env"
  else
    echo 'WHICK_LIBRESPOT_AUTOSTART=1' >>"$RUNTIME_ROOT/.env"
  fi
  log "streaming providers enabled — Spotify Connect/Tidal paid-account linking"
}
ensure_customer_streaming_env

report_runtime_progress 38 "Docker 이미지 준비 중…"

# AI 에이전트 GPU 가속 — 외장(전용) GPU가 장착된 미니PC만 활성화.
# 내장GPU만(APU Renoir, Intel iGPU 등) 있는 모델은 CPU-only가 안정적이고 이득이 거의 없다.
# docker:27-cli sibling(WHICK_SKIP_HOST_PROBES=1) 에서는 lspci 불가 → CPU-only 기본.
has_external_pci_gpu() {
  if [[ "${WHICK_SKIP_HOST_PROBES:-0}" == "1" ]]; then
    return 1
  fi
  command -v lspci >/dev/null 2>&1 || return 1
  local vga
  vga="$(lspci -nn 2>/dev/null | grep -iE 'vga|3d|display' || true)"
  [[ -n "$vga" ]] || return 1
  # NVIDIA 전용(dGPU) — 거의 항상 외장
  if echo "$vga" | grep -qE '\[10de:[0-9a-fA-F]{4}\]'; then
    return 0
  fi
  # AMD 전용 — APU/iGPU PCI ID는 제외
  if echo "$vga" | grep -E '\[1002:[0-9a-fA-F]{4}\]' \
    | grep -qvE '\[1002:(1636|1638|164e|164d|15e7|15dd|15d8|13c0|15bf|15e4|98e4)\]'; then
    return 0
  fi
  return 1
}

ensure_customer_ollama_auto_env() {
  [[ -f "$RUNTIME_ROOT/.env" ]] || return 0
  [[ "${WHICK_LOCAL_AI:-1}" == "0" ]] && { log "WHICK_LOCAL_AI=0 — local AI disabled by explicit override"; return 0; }

  mem_kb="$(awk '/MemTotal:/ {print $2}' /proc/meminfo 2>/dev/null || echo 0)"
  local mem_gb=$((mem_kb / 1024 / 1024))

  # 2026-08-06: 32GB 미만 Ollama 미설치, 32GB 이상만 e2b
  # gemma4:e2b CPU-only = 8.4GB RSS. OS(1.5G)+Docker(1G)+e2b(8.4G)=10.9G
  # 16GB→68% 점유로 발열·swap, 24GB→45%로 발열 관리 어려움
  # 32GB→34%로 충분한 여유

  if [[ "${mem_kb:-0}" -lt 33554432 ]]; then
    persist_runtime_env WHICK_LOCAL_AI 0
    export WHICK_LOCAL_AI=0
    log "WHICK_LOCAL_AI=0 — RAM ${mem_gb}GB (<32GB), Ollama 미설치"
    return 0
  fi

  # ≥32GB: Ollama + gemma4:e2b 설치
  persist_runtime_env WHICK_LOCAL_AI 1
  export WHICK_LOCAL_AI=1
  log "WHICK_LOCAL_AI=1 — RAM ≥32GB (${mem_gb}GB), Ollama+e2b 활성화"

  if [[ "${WHICK_OLLAMA_CPU_ONLY:-0}" == "1" ]]; then
    if grep -q '^OLLAMA_NUM_GPU=' "$RUNTIME_ROOT/.env" 2>/dev/null; then
      sed -i 's|^OLLAMA_NUM_GPU=.*|OLLAMA_NUM_GPU=0|' "$RUNTIME_ROOT/.env"
    else
      echo 'OLLAMA_NUM_GPU=0' >>"$RUNTIME_ROOT/.env"
    fi
    log "OLLAMA_NUM_GPU=0 — forced CPU-only (WHICK_OLLAMA_CPU_ONLY=1)"
  elif has_external_pci_gpu; then
    if ! grep -q '^OLLAMA_NUM_GPU=' "$RUNTIME_ROOT/.env" 2>/dev/null; then
      echo 'OLLAMA_NUM_GPU=auto' >>"$RUNTIME_ROOT/.env"
      log "OLLAMA_NUM_GPU=auto — external GPU detected (dedicated GPU model)"
    fi
  else
    if ! grep -q '^OLLAMA_NUM_GPU=' "$RUNTIME_ROOT/.env" 2>/dev/null; then
      echo 'OLLAMA_NUM_GPU=0' >>"$RUNTIME_ROOT/.env"
      log "OLLAMA_NUM_GPU=0 — integrated GPU only; AI agent uses CPU"
    elif grep -q '^OLLAMA_NUM_GPU=auto$' "$RUNTIME_ROOT/.env" 2>/dev/null; then
      sed -i 's|^OLLAMA_NUM_GPU=auto$|OLLAMA_NUM_GPU=0|' "$RUNTIME_ROOT/.env"
      log "OLLAMA_NUM_GPU=0 — downgraded from auto (no external GPU on this model)"
    fi
  fi

  # ≥32GB: gemma4:e2b 로 고정 (WHICK_OLLAMA_MODEL 수동 핀 우선)
  local ollama_model
  if [[ -n "${WHICK_OLLAMA_MODEL:-}" ]]; then
    ollama_model="$WHICK_OLLAMA_MODEL"
    log "OLLAMA_MODEL=$ollama_model — WHICK_OLLAMA_MODEL pin"
  else
    ollama_model="gemma4:e2b"
    log "OLLAMA_MODEL=$ollama_model — RAM ${mem_gb}GB (≥32GB)"
  fi
  if grep -q '^OLLAMA_MODEL=' "$RUNTIME_ROOT/.env" 2>/dev/null; then
    if [[ -z "${WHICK_OLLAMA_MODEL:-}" ]]; then
      sed -i "s|^OLLAMA_MODEL=.*|OLLAMA_MODEL=${ollama_model}|" "$RUNTIME_ROOT/.env"
    fi
  else
    echo "OLLAMA_MODEL=${ollama_model}" >>"$RUNTIME_ROOT/.env"
  fi
}

persist_runtime_env() {
  local key="$1" val="$2"
  [[ -f "$RUNTIME_ROOT/.env" ]] || return 0
  if grep -q "^${key}=" "$RUNTIME_ROOT/.env" 2>/dev/null; then
    sed -i "s|^${key}=.*|${key}=${val}|" "$RUNTIME_ROOT/.env"
  else
    echo "${key}=${val}" >>"$RUNTIME_ROOT/.env"
  fi
}

# 리모컨 device_token 인증 — CC remote_device_token(SSOT)을 플레이어에 주입.
ensure_player_auth_env() {
  [[ -f "$RUNTIME_ROOT/.env" ]] || return 0
  local tok="${WHICK_REMOTE_DEVICE_TOKEN:-${WHICK_PLAYER_DEVICE_TOKEN:-}}"
  [[ -n "$tok" ]] || return 0
  persist_runtime_env WHICK_PLAYER_DEVICE_TOKEN "$tok"
  persist_runtime_env WHICK_PLAYER_AUTH_REQUIRED 1
  log "player device_token 인증 활성화 (리모컨 Bearer 필수)"
}
ensure_player_auth_env

# 외부·LTE named tunnel — 프로비저닝 번들 있으면 배포 + compose.tunnel.override.yaml 생성.
ensure_music_tunnel() {
  [[ -f "$RUNTIME_ROOT/.env" ]] || return 0
  local src="${WHICK_TUNNEL_BUNDLE_DIR:-}"
  if [[ -n "$src" && -f "$src/config.yml" ]]; then
    mkdir -p "$RUNTIME_ROOT/tunnel"
    cp -f "$src"/*.yml "$src"/*.json "$RUNTIME_ROOT/tunnel/" 2>/dev/null || true
    log "music tunnel 번들 배포 → $RUNTIME_ROOT/tunnel"
  fi
  # cloudflared는 nonroot(65532)로 실행 — 644 이상 아니면 permission denied 크래시 루프
  if [[ -d "$RUNTIME_ROOT/tunnel" ]]; then
    chmod 644 "$RUNTIME_ROOT/tunnel/"*.json "$RUNTIME_ROOT/tunnel/"*.yml "$RUNTIME_ROOT/tunnel/device-token" 2>/dev/null || true
  fi
  if [[ -f "$RUNTIME_ROOT/tunnel/config.yml" ]]; then
    cat >"$RUNTIME_ROOT/compose.tunnel.override.yaml" <<'EOF'
# 리모컨 외부·LTE named tunnel — install-runtime 자동 생성 (provision-music-tunnel 번들 존재 시)
services:
  tunnel:
    image: cloudflare/cloudflared:2026.6.1
    container_name: whick-tunnel
    restart: unless-stopped
    user: "0:0"
    command: ['tunnel', '--no-autoupdate', '--config', '/etc/cloudflared/config.yml', 'run']
    volumes:
      - ./tunnel:/etc/cloudflared:rw
    networks: [whick_net]
    depends_on:
      - player
EOF
    log "music tunnel 활성화 (compose.tunnel.override.yaml → COMPOSE_ARGS)"
  fi
}
ensure_music_tunnel

ensure_customer_ollama_auto_env

# ensure_customer_ollama_auto_env writes values to .env, while compose interpolates
# these variables from the current shell. Re-export them before compose up.
if [[ -f "$RUNTIME_ROOT/.env" ]]; then
  _onum="$(grep -oP '^OLLAMA_NUM_GPU=\K.+' "$RUNTIME_ROOT/.env" 2>/dev/null || true)"
  _omodel="$(grep -oP '^OLLAMA_MODEL=\K.+' "$RUNTIME_ROOT/.env" 2>/dev/null || true)"
  [[ -n "$_onum" ]] && export OLLAMA_NUM_GPU="$_onum" && log "export OLLAMA_NUM_GPU=$_onum"
  [[ -n "$_omodel" ]] && export OLLAMA_MODEL="$_omodel" && log "export OLLAMA_MODEL=$_omodel"
fi

ensure_host_aloop() {
  # 호스트 부팅 시 snd-aloop 선로드 — player 컨테이너 CAP_SYS_MODULE 없이도 Loopback 존재.
  # 재설치·재부팅마다 깨지던 MPD hang(목록 OK·재생 불가)의 1차 방어선.
  local conf="/etc/modules-load.d/whick-aloop.conf"
  if [[ ! -f "$conf" ]] || ! grep -qx 'snd-aloop' "$conf" 2>/dev/null; then
    install -d -m 755 /etc/modules-load.d
    printf '%s\n' 'snd-aloop' >"$conf"
    log "wrote ${conf}"
  fi
  if ! lsmod 2>/dev/null | grep -q '^snd_aloop'; then
    modprobe snd-aloop index=10 id=Loopback pcm_substreams=4 2>/dev/null \
      || modprobe snd-aloop 2>/dev/null \
      || log "WARN modprobe snd-aloop failed (kernel module missing?)"
  fi
  if [[ -r /proc/asound/cards ]] && grep -q Loopback /proc/asound/cards 2>/dev/null; then
    log "ALSA Loopback present"
  else
    log "WARN ALSA Loopback not in /proc/asound/cards yet — player will direct-ALSA if still missing"
  fi
}
ensure_host_aloop

ensure_customer_compose_override() {
  [[ "${WHICK_LAB_SKIP_CUSTOMER_OVERRIDE:-0}" == "1" ]] && return 0
  local target="$RUNTIME_ROOT/compose.override.yaml"
  # DAC 핫플러그 대응: `devices:`는 컨테이너 기동 시점의 사운드 노드만 등록하므로
  # 다른 DAC로 교체하면 재시작 전까지 인식되지 않는다. /dev/snd 를 bind mount 하고
  # ALSA major(116) 전체를 device cgroup 으로 허용해, 어떤 DAC를 꽂아도 노드가 즉시
  # 보이고 접근 가능하게 한다(camilla-pipe 가 재생마다 카드를 재탐지 → 재시작 불필요).
  local desired
  desired="$(cat <<'EOF'
# Customer mini-PC — ALSA hot-plug passthrough (camilla-pipe → WHICK_CAMILLA_ALSA_DEVICE)
# DAC 교체 시 컨테이너 재시작 없이 즉시 인식: /dev/snd bind + asound(proc) + ALSA(major 116) cgroup 허용.
# 최신 runc(1.2+/1.3.x)는 /proc 하위 bind mount 를 거부하므로 /proc/asound 를
# /run/whick/asound 로 bind 하고 WHICK_ASOUND_ROOT 로 참조한다.
# /lib/modules:ro + privileged — ensure-aloop.sh 가 snd-aloop 을 modprobe 하려면
# 모듈 파일과 CAP_SYS_MODULE 이 모두 필요. 없으면 Camilla fifo 폴백 → MPD hang
# (목록은 되고 재생만 실패).
services:
  player:
    privileged: true
    volumes:
      - /dev/snd:/dev/snd
      - /proc/asound:/run/whick/asound:ro
      - /lib/modules:/lib/modules:ro
    device_cgroup_rules:
      - 'c 116:* rmw'
    group_add:
      - audio
    environment:
      WHICK_CAMILLA_ENABLED: "1"
      WHICK_CAMILLA_ALSA_DEVICE: ${WHICK_CAMILLA_ALSA_DEVICE:-auto}
      WHICK_ASOUND_ROOT: /run/whick/asound
EOF
)"
  # 구버전(privileged 누락 · devices · /proc/asound · modules 누락) override 는
  # 항상 최신 형태(privileged + /run/whick/asound + /lib/modules)로 교체한다.
  if [[ -f "$target" ]] && grep -q 'privileged: true' "$target" 2>/dev/null \
    && grep -q 'device_cgroup_rules' "$target" 2>/dev/null \
    && grep -q '/run/whick/asound' "$target" 2>/dev/null \
    && grep -q '/lib/modules:/lib/modules' "$target" 2>/dev/null; then
    return 0
  fi
  printf '%s\n' "$desired" >"$target"
  log "compose.override.yaml — ALSA hot-plug (/dev/snd + cgroup 116 + asound /run + /lib/modules)"
}
ensure_customer_compose_override

# 고객 음원·라이브러리 상태 → /mnt/music/whick-data (root 파티션 docker volume 회피)
ensure_music_data_compose_override() {
  [[ "${WHICK_LAB_SKIP_MUSIC_DATA_BIND:-0}" == "1" ]] && return 0
  local music_mount="${WHICK_MUSIC_MOUNT:-/mnt/music}"
  local music_data="${music_mount}/whick-data"
  local out="$RUNTIME_ROOT/compose.music-data.override.yaml"

  if [[ ! -d "$music_mount" ]]; then
    log "music partition ${music_mount} 없음 — whick-data docker named volume 유지"
    return 0
  fi

  mount -o remount,rw "$music_mount" 2>/dev/null || true
  mkdir -p \
    "$music_data/library/music" \
    "$music_data/library/incoming" \
    "$music_data/camilla" \
    "$music_data/state"

  local old_mp=""
  old_mp="$(docker volume inspect whick-runtime_whick-data --format '{{.Mountpoint}}' 2>/dev/null || true)"
  if [[ -n "$old_mp" && -d "$old_mp" ]]; then
    local old_kb new_kb
    old_kb="$(du -sk "$old_mp" 2>/dev/null | awk '{print $1}')"
    new_kb="$(du -sk "$music_data" 2>/dev/null | awk '{print $1}')"
    if [[ "${old_kb:-0}" -gt "$(( ${new_kb:-0} + 1024 ))" ]]; then
      log "migrate whick-runtime_whick-data → ${music_data} (${old_kb}K)"
      rsync -a "$old_mp/" "$music_data/" 2>/dev/null \
        || cp -a "$old_mp/." "$music_data/" 2>/dev/null \
        || true
    fi
  fi

  cat >"$out" <<EOF
# Generated by install-runtime.sh — customer music partition (/mnt/music)
volumes:
  whick-data:
    driver: local
    driver_opts:
      type: none
      o: bind
      device: ${music_data}

services:
  player:
    volumes:
      # USB 자동마운트: rslave propagation으로 호스트의 새 마운트를 컨테이너에 전파.
      # USB 음원 복사(쓰기) 지원을 위해 rw로 마운트 — 음악 파티션(/mnt/music)은 여전히 ro 보호.
      - /media:/media:rw,rslave
      - /run/media:/run/media:rw,rslave
      - /proc/mounts:/host/proc/mounts:ro
  monitor:
    volumes:
      - ${music_mount}:${music_mount}:ro
      - /media:/media:ro,rslave
      - /run/media:/run/media:ro,rslave
      - /proc/mounts:/host/proc/mounts:ro
EOF
  log "compose.music-data.override.yaml — whick-data bind ${music_data} · monitor ${music_mount}:ro"
}
ensure_music_data_compose_override

# 시드 데모 음원 — 설치 후 바로 테스트 가능하도록 10곡 복사
# SCRIPT_DIR may be phase-bundle bin/ (no seed-music) — prefer RUNTIME_ROOT.
ensure_seed_music() {
  local music_mount="${WHICK_MUSIC_MOUNT:-/mnt/music}"
  local dest="${music_mount}/whick-data/library/music"
  local seed_src="" candidate n
  for candidate in \
    "${WHICK_RUNTIME_ROOT:-/opt/whick/runtime}/seed-music" \
    "$RUNTIME_ROOT/seed-music" \
    "$SCRIPT_DIR/../seed-music" \
    "/opt/whick/runtime/seed-music"; do
    if [[ -d "$candidate" ]] && find "$candidate" -maxdepth 1 -name '*.flac' 2>/dev/null | grep -q .; then
      seed_src="$candidate"
      break
    fi
  done
  if [[ -z "$seed_src" ]]; then
    log "WARN seed music skipped — no seed-music/*.flac (checked runtime + phase paths)"
    return 0
  fi
  if [[ ! -d "$music_mount" ]]; then
    log "WARN seed music skipped — music mount missing: $music_mount"
    return 0
  fi
  mkdir -p "$dest"
  if ! cp -f "$seed_src"/*.flac "$dest/"; then
    log "ERROR seed music copy failed src=$seed_src dest=$dest"
    return 1
  fi
  n=$(find "$dest" -maxdepth 1 -name '*.flac' 2>/dev/null | wc -l | tr -d ' ')
  log "seed demo music: ${n} tracks from ${seed_src} → ${dest}"
  if [[ "${n:-0}" -lt 1 ]]; then
    log "ERROR seed music copy produced 0 flac files"
    return 1
  fi
  return 0
}
ensure_seed_music || log "WARN ensure_seed_music failed — library may be empty until manual seed"

ensure_ollama_gpu_compose_override() {
  local out="$RUNTIME_ROOT/compose.gpu.override.yaml"
  [[ "${WHICK_LOCAL_AI:-1}" == "0" ]] && { rm -f "$out"; return 0; }
  [[ "${WHICK_OLLAMA_CPU_ONLY:-0}" == "1" ]] && { rm -f "$out"; return 0; }

  if ! has_external_pci_gpu; then
    rm -f "$out"
    log "Ollama GPU override skipped — no external GPU (integrated-only model)"
    return 0
  fi

  local has_dri=0 has_nvidia=0
  [[ -d /dev/dri ]] && has_dri=1
  [[ -e /dev/nvidiactl || -e /dev/nvidia0 ]] && has_nvidia=1

  if [[ "$has_dri" != "1" && "$has_nvidia" != "1" ]]; then
    rm -f "$out"
    log "Ollama GPU override skipped — external GPU present but no dri/nvidia device node yet"
    return 0
  fi

  {
    echo "# Generated by install-runtime.sh — external GPU model only"
    echo "services:"
    echo "  ollama:"
    if [[ "$has_dri" == "1" ]]; then
      echo "    devices:"
      echo "      - /dev/dri:/dev/dri"
      [[ -e /dev/kfd ]] && echo "      - /dev/kfd:/dev/kfd"
      echo "    group_add:"
      while read -r gid; do
        [[ -n "$gid" ]] && echo "      - \"$gid\""
      done < <(stat -c %g /dev/dri/card* /dev/dri/renderD* /dev/kfd 2>/dev/null | sort -u)
    fi
    echo "    environment:"
    echo "      OLLAMA_NUM_GPU: auto"
    if [[ "$has_nvidia" == "1" ]]; then
      cat <<'EOF'
      NVIDIA_VISIBLE_DEVICES: all
      NVIDIA_DRIVER_CAPABILITIES: compute,utility
    gpus: all
EOF
    fi
  } >"$out"
  log "compose.gpu.override.yaml — Ollama GPU passthrough (external GPU; dri=$has_dri nvidia=$has_nvidia)"
}
ensure_ollama_gpu_compose_override

# 호스트 워치독 — agent hang/네트워크 wedge 시 agent 재시작→호스트 재부팅 자동복구
ensure_host_watchdog() {
  local wd_src="$RUNTIME_ROOT/host/install-watchdog.sh"
  [[ -f "$wd_src" ]] || return 0
  sh "$wd_src" >/dev/null 2>&1 && log "host watchdog installed (auto-recovery)" || log "host watchdog install skipped"
}
ensure_host_watchdog

# GPU 펌웨어 — linux-firmware 미설치 시 amdgpu 등 early_init 실패(부팅 에러) 방지.
# AI 에이전트 GPU 가속은 외장 GPU 모델에서만 활성화; 펌웨어는 내장GPU 포함 best-effort 설치.
ensure_gpu_firmware() {
  [[ "${WHICK_SKIP_GPU_FIRMWARE:-0}" == "1" ]] && return 0
  command -v apt-get >/dev/null 2>&1 || return 0
  dpkg -l linux-firmware 2>/dev/null | grep -q '^ii' && return 0
  # GPU 존재 확인 (드라이버 로드 또는 DRM 노드)
  if ! lsmod 2>/dev/null | grep -qE '^(amdgpu|i915|nouveau|nvidia)' && [[ ! -e /dev/dri/card0 ]]; then
    return 0
  fi
  export DEBIAN_FRONTEND=noninteractive
  log "GPU firmware: installing linux-firmware (optional AI agent GPU accel)"
  if timeout "${WHICK_ONLINE_INSTALL_TIMEOUT:-300}" apt-get update -y >/dev/null 2>&1 \
    && timeout 900 apt-get install -y --no-install-recommends linux-firmware >/dev/null 2>&1; then
    update-initramfs -u >/dev/null 2>&1 || true
    log "GPU firmware installed — reboot to activate GPU"
  else
    log "GPU firmware install skipped (offline or apt busy)"
  fi
}
ensure_gpu_firmware

persist_install_credentials() {
  local mb="$1" hw="$2"
  [[ -n "$mb" || -n "$hw" ]] || return 0
  mkdir -p /var/lib/whick
  python3 - "$mb" "$hw" <<'PY' || true
import json, os, sys, time
mb, hw = sys.argv[1], sys.argv[2]
path = "/var/lib/whick/install-credentials.json"
prev = {}
try:
    prev = json.load(open(path))
except Exception:
    pass
next = dict(prev)
if mb:
    next["mb_id"] = mb
if hw:
    next["device_serial"] = hw
    next["hw_id_hash"] = hw
next["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
tmp = path + ".tmp"
with open(tmp, "w") as f:
    json.dump(next, f, ensure_ascii=False, indent=2)
os.rename(tmp, path)
os.chmod(path, 0o600)
PY
}

# 관제 에이전트 등록 자격 — bootstrap 세션 · CC /install/session/me → .env + install-credentials.json
ensure_owner_credentials() {
  [[ -f "$RUNTIME_ROOT/.env" ]] || return 0
  local have_mb have_serial
  have_mb="$(grep -E '^WHICK_OWNER_MB_ID=.+' "$RUNTIME_ROOT/.env" 2>/dev/null || true)"
  have_serial="$(grep -E '^WHICK_DEVICE_SERIAL=[0-9a-fA-F]{64}$' "$RUNTIME_ROOT/.env" 2>/dev/null || true)"
  if [[ -n "$have_mb" && -n "$have_serial" ]]; then
    return 0
  fi
  command -v python3 >/dev/null 2>&1 || { log "python3 없음 — 자격 주입 생략"; return 0; }

  local session=""
  local p
  for p in "${WHICK_BOOTSTRAP_SESSION:-}" /var/lib/whick/bootstrap-session.json /tmp/whick-bootstrap-session.json; do
    if [[ -n "$p" && -f "$p" ]]; then session="$p"; break; fi
  done
  [[ -n "$session" ]] || { log "bootstrap 세션 없음 — 자격 주입 생략"; return 0; }

  local cc_base="${WHICK_CC_API_URL:-https://admin.whick.org/api/v1}"
  local creds
  creds="$(python3 - "$session" "$cc_base" <<'PY' 2>&1 || true
import json, sys, urllib.request, re
sess_path, cc = sys.argv[1], sys.argv[2].rstrip("/")
HW = re.compile(r"^[0-9a-fA-F]{64}$")
try:
    data = json.load(open(sess_path))
except Exception as e:
    print(f"WARN bootstrap read: {e}", file=sys.stderr)
    raise SystemExit(0)
mb = str(data.get("mb_id") or "").strip()
hw = str(data.get("hw_id_hash") or data.get("hw_hash") or "").strip()
token = data.get("bootstrap_token") or data.get("token") or ""
if token and (not mb or not HW.match(hw or "")):
    req = urllib.request.Request(
        cc + "/install/session/me",
        headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            resp = json.loads(r.read().decode("utf-8", errors="replace"))
        inner = resp.get("data") if isinstance(resp.get("data"), dict) else resp
        mb = mb or str(inner.get("mb_id") or "").strip()
        hw = hw or str(inner.get("hw_id_hash") or "").strip()
    except Exception as e:
        print(f"WARN session/me: {e}", file=sys.stderr)
print(f"{mb}\t{hw}")
PY
)"
  local mb_id hw_hash
  mb_id="$(printf '%s' "$creds" | cut -f1)"
  hw_hash="$(printf '%s' "$creds" | cut -f2)"

  if [[ -n "$mb_id" ]]; then
    persist_runtime_env WHICK_OWNER_MB_ID "$mb_id"
    log "WHICK_OWNER_MB_ID 주입"
  else
    log "WARN mb_id 미확인 — 에이전트 등록은 .env 수동 설정 필요"
  fi
  if [[ "$hw_hash" =~ ^[0-9a-fA-F]{64}$ ]]; then
    persist_runtime_env WHICK_DEVICE_SERIAL "$hw_hash"
    log "WHICK_DEVICE_SERIAL 주입"
  else
    log "WARN hw_id_hash 미확인 — 에이전트 등록은 .env 수동 설정 필요"
  fi
  persist_install_credentials "$mb_id" "$hw_hash"
}
ensure_owner_credentials

# compose.yaml의 agent 서비스는 `environment: WHICK_DEVICE_SERIAL: ${WHICK_DEVICE_SERIAL:-}` 로
# env_file(.env)보다 우선한다. 셸에 export가 없으면 빈 값으로 덮어써져 agent가 등록 실패한다.
# .env에 기록된 값을 셸로 끌어올려 compose 보간이 실제 값을 받게 한다(신규·재시도 모두).
if [[ -f "$RUNTIME_ROOT/.env" ]]; then
  _serial="$(grep -E '^WHICK_DEVICE_SERIAL=' "$RUNTIME_ROOT/.env" 2>/dev/null | tail -1 | cut -d= -f2-)"
  _owner="$(grep -E '^WHICK_OWNER_MB_ID=' "$RUNTIME_ROOT/.env" 2>/dev/null | tail -1 | cut -d= -f2-)"
  [[ -n "$_serial" ]] && export WHICK_DEVICE_SERIAL="$_serial"
  [[ -n "$_owner" ]] && export WHICK_OWNER_MB_ID="$_owner"
  log "compose env: WHICK_DEVICE_SERIAL=${_serial:0:8}… WHICK_OWNER_MB_ID=${_owner:-<none>}"
fi

COMPOSE="$RUNTIME_ROOT/compose.yaml"
[[ -f "$COMPOSE" ]] || { log "missing $COMPOSE"; exit 1; }
COMPOSE_ARGS=(-f "$COMPOSE")
if [[ -f "$RUNTIME_ROOT/compose.override.yaml" ]]; then
  COMPOSE_ARGS+=(-f "$RUNTIME_ROOT/compose.override.yaml")
fi
if [[ -f "$RUNTIME_ROOT/compose.gpu.override.yaml" ]]; then
  COMPOSE_ARGS+=(-f "$RUNTIME_ROOT/compose.gpu.override.yaml")
fi
if [[ -f "$RUNTIME_ROOT/compose.tunnel.override.yaml" ]]; then
  COMPOSE_ARGS+=(-f "$RUNTIME_ROOT/compose.tunnel.override.yaml")
fi
if [[ -f "$RUNTIME_ROOT/compose.music-data.override.yaml" ]]; then
  COMPOSE_ARGS+=(-f "$RUNTIME_ROOT/compose.music-data.override.yaml")
fi

export COMPOSE_PROFILE=()
REUSE_HOST_OLLAMA=0
if [[ "${WHICK_LOCAL_AI:-1}" != "0" ]]; then
  if docker ps --format '{{.Names}}' | grep -qx whick-ollama; then
    if [[ "${WHICK_REUSE_HOST_OLLAMA:-0}" == "1" ]]; then
      REUSE_HOST_OLLAMA=1
      log "whick-ollama already running — reuse host (WHICK_REUSE_HOST_OLLAMA=1 · lab/dev only)"
    else
      export WHICK_OLLAMA_CONTAINER_NAME="${WHICK_OLLAMA_CONTAINER_NAME:-whick-runtime-ollama}"
      persist_runtime_env WHICK_OLLAMA_CONTAINER_NAME "$WHICK_OLLAMA_CONTAINER_NAME"
      COMPOSE_PROFILE=(--profile local-ai)
      log "whick-ollama on host — local-ai sidecar as ${WHICK_OLLAMA_CONTAINER_NAME} (HQ ollama kept separate)"
      log "  hint: reuse HQ ollama instead → WHICK_REUSE_HOST_OLLAMA=1"
    fi
  else
    COMPOSE_PROFILE=(--profile local-ai)
    log "local-ai profile — Ollama auto GPU/CPU fallback"
  fi
fi

IMG_DIR="$RUNTIME_ROOT/offline/images"
ONLINE_OK=0
if [[ "${WHICK_ALLOW_ONLINE_PULL:-0}" == "1" && "${WHICK_SKIP_ONLINE_INSTALL:-0}" != "1" ]]; then
  log "online compose pull attempt…"
  if timeout "${WHICK_ONLINE_INSTALL_TIMEOUT:-300}" docker compose "${COMPOSE_ARGS[@]}" "${COMPOSE_PROFILE[@]}" pull 2>/dev/null; then
    ONLINE_OK=1
    log "online compose pull OK"
  else
    log "online pull failed — offline/CC bundle images"
  fi
fi

if [[ "$ONLINE_OK" != "1" && -d "$IMG_DIR" ]]; then
  report_runtime_progress 45 "Docker 이미지 로드 중…"
  (
    pct=45
    while [[ $pct -le 58 ]]; do
      report_runtime_progress "$pct" "Docker 이미지 로드 중… (${pct}%)"
      sleep 2
      pct=$((pct + 1))
    done
  ) &
  IMG_TICK_PID=$!
  for img in "$IMG_DIR"/*.tar "$IMG_DIR"/*.tar.zst; do
    [[ -f "$img" ]] || continue
    log "docker load $img"
    case "$img" in
      *.tar.zst)
        if ! zstd -dc "$img" | docker load; then
          log "ERROR docker load failed: $img"
          exit 1
        fi
        ;;
      *)
        if ! docker load -i "$img"; then
          log "ERROR docker load failed: $img"
          exit 1
        fi
        ;;
    esac
  done
  kill "$IMG_TICK_PID" 2>/dev/null || true
  wait "$IMG_TICK_PID" 2>/dev/null || true
fi
report_runtime_progress 59 "이미지 로드 완료"

# Ollama image — CC 우선(핀 tar) · Hub pull은 동일 핀 태그 비상만 · latest 금지
if [[ "${WHICK_LOCAL_AI:-1}" != "0" ]]; then
  ollama_pin=""
  ollama_tar=""
  ollama_sha=""
  _ollama_lock=""
  for _cand in \
    "${WHICK_COMPONENTS_LOCK:-}" \
    "$RUNTIME_ROOT/components.lock.json" \
    "$RUNTIME_ROOT/lib/components.lock.json" \
    "$SCRIPT_DIR/../lib/components.lock.json"; do
    if [[ -n "$_cand" && -f "$_cand" ]]; then
      _ollama_lock="$_cand"
      break
    fi
  done
  if [[ -n "$_ollama_lock" ]] && command -v python3 >/dev/null 2>&1; then
    ollama_pin="$(python3 - "$_ollama_lock" <<'PY'
import json, sys
c = json.load(open(sys.argv[1])).get("components") or {}
print((c.get("images") or {}).get("ollama/ollama") or "")
PY
)"
    ollama_tar="$(python3 - "$_ollama_lock" <<'PY'
import json, sys
c = json.load(open(sys.argv[1])).get("components") or {}
print((c.get("ollama_image") or {}).get("file") or "")
PY
)"
    ollama_sha="$(python3 - "$_ollama_lock" <<'PY'
import json, sys
c = json.load(open(sys.argv[1])).get("components") or {}
print((c.get("ollama_image") or {}).get("sha256") or "")
PY
)"
  fi
  if [[ -z "$ollama_pin" ]]; then
    ollama_pin="$(grep -oP 'ollama/ollama:\K[^\s"'\'']+' "$RUNTIME_ROOT/compose.yaml" 2>/dev/null | head -1 || true)"
  fi
  if [[ -z "$ollama_pin" || "$ollama_pin" == "latest" ]]; then
    log "ERROR: ollama pin missing or latest forbidden — set components.images[\"ollama/ollama\"]"
    unset COMPOSE_PROFILE
  else
    ollama_img="ollama/ollama:${ollama_pin}"
    log "ollama pin: ${ollama_pin}"
    if ! docker image inspect "$ollama_img" >/dev/null 2>&1; then
      _ollama_loaded=0
      if [[ -n "$ollama_tar" ]]; then
        _ollama_cache="${WHICK_INSTALL_CACHE:-/var/lib/whick/install-cache}/$ollama_tar"
        if [[ ! -f "$_ollama_cache" ]] && [[ -f "$SCRIPT_DIR/whick-fetch-artifact.sh" ]]; then
          log "CC fetch ollama tar $ollama_tar (source=cc)"
          report_runtime_progress 62 "Ollama AI 이미지(CC) 다운로드…"
          set +e
          "$SCRIPT_DIR/whick-fetch-artifact.sh" \
            --name "$ollama_tar" \
            --dest "$_ollama_cache" \
            ${ollama_sha:+--sha256 "$ollama_sha"} \
            --prefer-cc
          _fr=$?
          set -e
          [[ "$_fr" -eq 0 ]] || rm -f "$_ollama_cache"
        fi
        if [[ -f "$_ollama_cache" ]]; then
          log "docker load ollama from CC tar"
          case "$_ollama_cache" in
            *.tar.zst) zstd -dc "$_ollama_cache" | docker load && _ollama_loaded=1 ;;
            *) docker load -i "$_ollama_cache" && _ollama_loaded=1 ;;
          esac || _ollama_loaded=0
        fi
      fi
      if [[ "$_ollama_loaded" != "1" ]] && [[ "${WHICK_SKIP_ONLINE_INSTALL:-0}" != "1" ]]; then
        log "ollama CC miss — internet emergency pull ${ollama_img}"
        report_runtime_progress 63 "Ollama AI 이미지 비상 pull…"
        if timeout 600 docker pull "$ollama_img" 2>/dev/null; then
          log "ollama pull OK source=internet-emergency"
          _ollama_loaded=1
        fi
      fi
      if [[ "$_ollama_loaded" != "1" ]]; then
        log "WARN ollama image unavailable — local-ai profile skip"
        unset COMPOSE_PROFILE
      fi
    fi
  fi
fi

ensure_player_db_schema() {
  INIT_SQL="$RUNTIME_ROOT/remote/api/init.sql"
  log "wait player DB schema (tracks)"
  local tracks_ok=0
  for _i in $(seq 1 90); do
    if docker compose "${COMPOSE_ARGS[@]}" exec -T player-db pg_isready -U whick -d whickdb >/dev/null 2>&1 \
      && docker compose "${COMPOSE_ARGS[@]}" exec -T player-db \
        psql -U whick -d whickdb -tAc "SELECT to_regclass('public.tracks')" 2>/dev/null | grep -q tracks; then
      tracks_ok=1
      break
    fi
    sleep 2
  done

  if [[ "$tracks_ok" != "1" ]]; then
    if [[ ! -f "$INIT_SQL" ]]; then
      log "missing $INIT_SQL — cannot create tracks table"
      return 1
    fi
    log "apply player DB schema (init.sql)"
    docker compose "${COMPOSE_ARGS[@]}" exec -T player-db \
      psql -v ON_ERROR_STOP=1 -U whick -d whickdb <"$INIT_SQL"
    if ! docker compose "${COMPOSE_ARGS[@]}" exec -T player-db \
      psql -U whick -d whickdb -tAc "SELECT to_regclass('public.tracks')" 2>/dev/null | grep -q tracks; then
      log "player DB schema apply failed — tracks missing"
      return 1
    fi
  fi
  return 0
}

log "compose up player-db (schema before player)"
report_runtime_progress 60 "뮤직서버 DB 준비 중…"
docker compose "${COMPOSE_ARGS[@]}" up -d --no-build --pull never player-db
ensure_player_db_schema || exit 1

# 고정 container_name 잔여물 제거 — 프로젝트/레이블 불일치·orphan 시
# "Conflict. The container name \"/whick-audio\" is already in use" 방지.
# player-db 는 스키마 직후라 유지한다.
remove_runtime_name_conflicts() {
  local cname proj
  for cname in \
    whick-audio \
    whick-agent \
    whick-tunnel \
    whick-player \
    whick-monitor \
    whick-docker-proxy \
    whick-runtime-ollama \
    whick-ollama
  do
    if ! docker inspect "$cname" >/dev/null 2>&1; then
      continue
    fi
    proj="$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' "$cname" 2>/dev/null || true)"
    log "pre-up remove leftover: $cname (compose.project=${proj:-none})"
    docker rm -f "$cname" >/dev/null 2>&1 || true
  done
}

log "compose up (all services)"
report_runtime_progress 75 "뮤직서버 서비스 기동 중…"
remove_runtime_name_conflicts
# 스키마 직후 player-db 는 절대 recreate/stop 하지 않는다.
# plain up / player 포함 force-recreate 는 depends_on(service_healthy) 대기 중
# player-db 를 재조정하며 exit 0 → "dependency failed … exited (0)" 로 실패한다.
# → player-db 유지 + 나머지 서비스는 --no-deps 로만 force-recreate.
mapfile -t _RECREATE_SVCS < <(
  docker compose "${COMPOSE_ARGS[@]}" "${COMPOSE_PROFILE[@]}" config --services 2>/dev/null \
    | grep -vx 'player-db' || true
)
if [[ ${#_RECREATE_SVCS[@]} -eq 0 ]]; then
  # config 실패 시에도 player-db 만은 no-recreate
  log "WARN compose config --services empty — using static service list"
  _RECREATE_SVCS=(docker-socket-proxy audio agent monitor player)
  if [[ ${#COMPOSE_PROFILE[@]} -gt 0 ]]; then
    _RECREATE_SVCS+=(ollama)
  fi
  if [[ -f "$RUNTIME_ROOT/compose.tunnel.override.yaml" ]]; then
    _RECREATE_SVCS+=(tunnel)
  fi
fi
(
  pct=65
  while [[ $pct -le 74 ]]; do
    sleep 2
    pct=$((pct + 1))
    report_runtime_progress "$pct" "뮤직서버 컨테이너 기동 중… (${pct}%)" 2>/dev/null || true
  done
) &
COMPOSE_TICK_PID=$!
compose_up_except_player_db() {
  log "keep player-db; force-recreate --no-deps: ${_RECREATE_SVCS[*]}"
  docker compose "${COMPOSE_ARGS[@]}" up -d --no-build --pull never --no-recreate player-db
  docker compose "${COMPOSE_ARGS[@]}" "${COMPOSE_PROFILE[@]}" up \
    -d --no-build --pull never --remove-orphans --force-recreate --no-deps \
    "${_RECREATE_SVCS[@]}"
}
if ! compose_up_except_player_db; then
  log "WARN compose up failed — ensure player-db then retry once"
  docker compose "${COMPOSE_ARGS[@]}" up -d --no-build --pull never --no-recreate player-db || true
  sleep 3
  ensure_player_db_schema || true
  compose_up_except_player_db
fi
kill "$COMPOSE_TICK_PID" 2>/dev/null || true
wait "$COMPOSE_TICK_PID" 2>/dev/null || true

if [[ "$REUSE_HOST_OLLAMA" == "1" ]]; then
  NET="$(docker inspect whick-player --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}' 2>/dev/null || true)"
  if [[ -n "$NET" ]]; then
    docker network connect "$NET" whick-ollama 2>/dev/null || true
    log "connected whick-ollama to $NET"
  fi
  if [[ -f "$RUNTIME_ROOT/.env" ]] && grep -q '^OLLAMA_URL=http://ollama:' "$RUNTIME_ROOT/.env" 2>/dev/null; then
    sed -i 's|^OLLAMA_URL=.*|OLLAMA_URL=http://whick-ollama:11434|' "$RUNTIME_ROOT/.env"
    log "recreate player for OLLAMA_URL=http://whick-ollama:11434"
    docker compose "${COMPOSE_ARGS[@]}" up -d --force-recreate --no-deps player
  fi
fi

# schema ensured before player start — verify once more for lab logs
ensure_player_db_schema || exit 1

# pinned model — lock 선언 우선, 없으면 .env OLLAMA_MODEL fallback
models_json="$(read_lock_field models 2>/dev/null || echo '{}')"
model=""
if [[ "${WHICK_LOCAL_AI:-1}" != "0" ]] && command -v python3 >/dev/null 2>&1; then
  model=$(python3 -c "
import json, sys
m = json.loads(sys.argv[1] or '{}')
print(next(iter(m.values()), '') if m else '')
" "${models_json}")
  # fallback: .env에 OLLAMA_MODEL 선언돼 있으면 그것도 pull
  if [[ -z "$model" ]] && [[ -f "$RUNTIME_ROOT/.env" ]]; then
    model=$(grep -oP '^OLLAMA_MODEL=\K.+' "$RUNTIME_ROOT/.env" 2>/dev/null | tr -d \"\'\  | head -1 || true)
    [[ -n "$model" ]] && log "ollama model from .env: $model"
  fi
  if [[ -n "$model" ]]; then
    ollama_c=""
    if [[ "$REUSE_HOST_OLLAMA" == "1" ]]; then
      ollama_c=whick-ollama
    elif [[ -n "${WHICK_OLLAMA_CONTAINER_NAME:-}" ]]; then
      ollama_c="$WHICK_OLLAMA_CONTAINER_NAME"
    fi
    if [[ -n "$ollama_c" ]] && docker ps --format '{{.Names}}' | grep -qx "$ollama_c"; then
      log "ollama model $model (background via $ollama_c)"
      docker exec "$ollama_c" ollama pull "$model" >/dev/null 2>&1 &
    elif docker compose "${COMPOSE_ARGS[@]}" "${COMPOSE_PROFILE[@]}" ps -q ollama 2>/dev/null | grep -q .; then
      log "ollama model $model (background via compose ollama service)"
      docker compose "${COMPOSE_ARGS[@]}" "${COMPOSE_PROFILE[@]}" exec -T ollama ollama pull "$model" >/dev/null 2>&1 &
    fi
  fi
fi

verify_agent_connected() {
  local timeout="${WHICK_AGENT_CONNECT_TIMEOUT_SEC:-120}"
  local elapsed=0
  log "wait whick-agent CC registration (${timeout}s)"
  (
    pct=88
    while [[ $pct -le 97 ]]; do
      report_runtime_progress "$pct" "관제 AI 연결 중… (${pct}%)"
      sleep 2
      pct=$((pct + 1))
    done
  ) &
  AGT_TICK_PID=$!
  while [[ "$elapsed" -lt "$timeout" ]]; do
    # 1차 확인 — runtime-state.json에 token이 저장됐으면 등록 완료 (가장 확실)
    local state_json
    state_json="$(docker exec whick-agent cat /var/lib/whick/runtime-state.json 2>/dev/null || true)"
    if [[ -n "$state_json" ]]; then
      local registered_device_id
      registered_device_id="$(echo "$state_json" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('device_id',''))" 2>/dev/null || true)"
      if [[ -n "$registered_device_id" && "$registered_device_id" != "null" ]]; then
        log "whick-agent registered with CC (device_id=${registered_device_id})"
        kill "$AGT_TICK_PID" 2>/dev/null || true
        wait "$AGT_TICK_PID" 2>/dev/null || true
        return 0
      fi
    fi
    # 2차 확인 — docker logs에서 registration 로그 확인 (--since 제거, 전체 로그 검사)
    local logs
    logs="$(docker logs whick-agent 2>&1 || true)"
    if printf '%s\n' "$logs" | grep -q '\[agent\] registered device_id'; then
      log "whick-agent registered with CC (log confirmed)"
      kill "$AGT_TICK_PID" 2>/dev/null || true
      wait "$AGT_TICK_PID" 2>/dev/null || true
      return 0
    fi
    sleep 5
    elapsed=$((elapsed + 5))
  done
  kill "$AGT_TICK_PID" 2>/dev/null || true
  wait "$AGT_TICK_PID" 2>/dev/null || true

  log "ERROR whick-agent did not register with CC"
  docker ps -a --filter name=whick-agent --format 'agent {{.Status}}' || true
  docker logs whick-agent --tail 120 2>&1 || true
  return 1
}
verify_agent_connected || exit 1
report_runtime_progress 100 "runtime 기동 완료"

log "OK runtime at $RUNTIME_ROOT"
