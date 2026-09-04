#!/usr/bin/env bash
# disk_plan 적용 후 Ubuntu bootstrap rootfs 배포 + GRUB (USB Live)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WHICK_ENV="${WHICK_BOOT_CONNECT_ROOT:-/opt/whick-boot-connect}/whick-env.sh"
if [[ -f "$WHICK_ENV" ]]; then
  # shellcheck source=/dev/null
  . "$WHICK_ENV"
fi
PLAN_JSON="${1:-${WHICK_PHASE_DIR:-/tmp/whick-phases}/disk_plan.json}"
PLAN_EXTRA_JSON="${2:-${WHICK_PHASE_DIR:-/tmp/whick-phases}/disk_plan_extra.json}"
BOOTSTRAP="${WHICK_BOOTSTRAP_ROOTFS:-}"

# shellcheck source=/dev/null
. "$(cd "$(dirname "$0")/.." && pwd)/lib/bootstrap_tar_check.sh"

# Real CC progress during deploy (avoids UI stuck on phase_tick ceiling ~87%).
deploy_progress() {
  local pct="$1" msg="$2"
  echo "[deploy_bootstrap] ${pct}% — ${msg}"
  python3 "$ROOT/bin/cc_progress.py" --phase install_linux --pct "$pct" --msg "$msg" 2>/dev/null || true
}

if [[ -n "$BOOTSTRAP" && -f "$BOOTSTRAP" ]] && ! bootstrap_tar_boot_ready "$BOOTSTRAP"; then
  echo "[deploy_bootstrap] WARN rejecting bootstrap (no initrd in archive): $BOOTSTRAP" >&2
  BOOTSTRAP=""
fi

if [[ -z "$BOOTSTRAP" || ! -f "$BOOTSTRAP" ]]; then
  for candidate in \
    "/opt/whick-boot-connect/bootstrap/whick-bootstrap-rootfs.tar.xz" \
    "/opt/whick-boot-connect/bootstrap/whick-bootstrap-rootfs.tar.gz" \
    "${WHICK_USB_ROOT:-}/whick-boot-connect/bootstrap/whick-bootstrap-rootfs.tar.xz" \
    "${WHICK_USB_ROOT:-}/whick-boot-connect/bootstrap/whick-bootstrap-rootfs.tar.gz"; do
    if [[ -n "$candidate" && -f "$candidate" ]] && bootstrap_tar_boot_ready "$candidate"; then
      BOOTSTRAP="$candidate"
      break
    fi
    if [[ -n "$candidate" && -f "$candidate" ]]; then
      echo "[deploy_bootstrap] WARN skipping USB bootstrap (no initrd in archive): $candidate" >&2
    fi
  done
fi

if [[ -z "$BOOTSTRAP" || ! -f "$BOOTSTRAP" ]]; then
  _session_json=""
  for p in "${WHICK_BOOTSTRAP_SESSION:-}" /tmp/whick-bootstrap-session.json; do
    if [[ -n "$p" && -f "$p" ]]; then
      _session_json="$p"
      export WHICK_BOOTSTRAP_SESSION="$p"
      break
    fi
  done
  if [[ "${WHICK_DEPLOY_NO_CC_FETCH:-0}" != "1" && -n "$_session_json" ]]; then
    CACHE="${WHICK_INSTALL_CACHE:-/var/lib/whick/install-cache}"
    DEST="$CACHE/whick-bootstrap-rootfs.tar.xz"
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    LOCK="${WHICK_COMPONENTS_LOCK:-$ROOT/lib/components.lock.json}"
    BOOT_SHA=""
    if [[ -f "$LOCK" ]]; then
      BOOT_SHA="$(python3 - <<'PY' "$LOCK"
import json, sys
lock = json.load(open(sys.argv[1]))
print(lock.get("components", {}).get("bootstrap_rootfs", {}).get("sha256", ""))
PY
)"
    fi
    CC="${WHICK_CC_API_URL:-https://admin.whick.org/api/v1}"
    echo "[deploy_bootstrap] CC fetch whick-bootstrap-rootfs.tar.xz"
    deploy_progress 55 "Downloading Ubuntu rootfs from CC…"
    if "$SCRIPT_DIR/whick-fetch-artifact.sh" \
      --name "whick-bootstrap-rootfs.tar.xz" \
      --dest "$DEST" \
      ${BOOT_SHA:+--sha256 "$BOOT_SHA"} \
      --url "$CC/install/bootstrap/artifact/whick-bootstrap-rootfs.tar.xz"; then
      if bootstrap_tar_boot_ready "$DEST"; then
        BOOTSTRAP="$DEST"
      else
        _got_sha="$(sha256sum "$DEST" | awk '{print $1}')"
        _got_sz="$(stat -c%s "$DEST" 2>/dev/null || echo 0)"
        echo "[deploy_bootstrap] ERROR CC bootstrap not boot-ready (initrd+vmlinuz)" >&2
        echo "[deploy_bootstrap]   file=$DEST sha256=$_got_sha size=$_got_sz expect_sha=${BOOT_SHA:-none}" >&2
        rm -f "$DEST"
      fi
    fi
  fi
fi

if [[ -n "$BOOTSTRAP" && -f "$BOOTSTRAP" ]] && ! bootstrap_tar_boot_ready "$BOOTSTRAP"; then
  echo "[deploy_bootstrap] ERROR bootstrap archive not boot-ready: $BOOTSTRAP" >&2
  exit 1
fi

if [[ -z "$BOOTSTRAP" || ! -f "$BOOTSTRAP" ]]; then
  echo "[deploy_bootstrap] ERROR: WHICK_BOOTSTRAP_ROOTFS not found (USB or CC)" >&2
  echo "  Build: scripts/build-whick-bootstrap-rootfs.sh" >&2
  exit 1
fi

if [[ ! -f "$PLAN_JSON" ]]; then
  echo "[deploy_bootstrap] missing plan: $PLAN_JSON" >&2
  exit 1
fi

MNT="${WHICK_DEPLOY_MNT:-/mnt/whick-target}"
EFI_MNT="${MNT}/boot/efi"
mkdir -p "$MNT"

DISK_DEV="${WHICK_TARGET_DISK:-}"
if [[ -z "$DISK_DEV" ]]; then
  DISK_DEV="$(python3 - <<'PY' "$PLAN_JSON"
import json, sys
print(json.load(open(sys.argv[1])).get("disk") or "")
PY
)"
fi

ROOT_DEV="$(blkid -L whick-root -o device 2>/dev/null || true)"
EFI_DEV="$(blkid -L WHICK-EFI -o device 2>/dev/null || true)"

resolve_efi_dev() {
  local d name ptype fstype
  d="$(blkid -L WHICK-EFI -o device 2>/dev/null || true)"
  if [[ -n "$d" && -b "$d" ]]; then
    echo "$d"
    return 0
  fi
  if [[ -n "${DISK_DEV:-}" && -b "$DISK_DEV" ]]; then
    # GPT ESP type GUID
    while read -r name ptype fstype; do
      ptype_l="$(printf '%s' "$ptype" | tr 'A-Z' 'a-z')"
      if [[ "$ptype_l" == *c12a7328* ]]; then
        echo "$name"
        return 0
      fi
    done < <(lsblk -nrpo NAME,PARTTYPE,FSTYPE "$DISK_DEV" 2>/dev/null || true)
    # fallback: first vfat on the install disk (typical ESP)
    while read -r name fstype; do
      if [[ "$fstype" == "vfat" || "$fstype" == "fat32" || "$fstype" == "fat" ]]; then
        echo "$name"
        return 0
      fi
    done < <(lsblk -nrpo NAME,FSTYPE "$DISK_DEV" 2>/dev/null || true)
  fi
  return 1
}

ensure_efi_whick_label() {
  local dev="$1" cur=""
  [[ -n "$dev" && -b "$dev" ]] || return 1
  cur="$(blkid -s LABEL -o value "$dev" 2>/dev/null || true)"
  if [[ "$cur" == "WHICK-EFI" ]]; then
    return 0
  fi
  echo "[deploy_bootstrap] relabel EFI $dev ($cur -> WHICK-EFI)" >&2
  if command -v fatlabel >/dev/null 2>&1; then
    fatlabel "$dev" WHICK-EFI 2>/dev/null || true
  elif command -v dosfslabel >/dev/null 2>&1; then
    dosfslabel "$dev" WHICK-EFI 2>/dev/null || true
  fi
  blkid "$dev" >/dev/null 2>&1 || true
}

if [[ -z "$ROOT_DEV" ]]; then
  for _wait in 1 2 3 4 5; do
    if command -v partprobe >/dev/null 2>&1 && [[ -n "${DISK_DEV:-}" && -b "$DISK_DEV" ]]; then
      partprobe "$DISK_DEV" 2>/dev/null || true
    fi
    if command -v mdev >/dev/null 2>&1; then
      mdev -s 2>/dev/null || true
    fi
    sleep 2
    ROOT_DEV="$(blkid -L whick-root -o device 2>/dev/null || true)"
    EFI_DEV="$(resolve_efi_dev || true)"
    [[ -n "$ROOT_DEV" && -b "$ROOT_DEV" ]] && break
  done
fi

# Prefer labeled ESP; otherwise discover by PARTTYPE/vfat (preserve reinstall often keeps OEM ESP label)
if [[ -z "$EFI_DEV" || ! -b "$EFI_DEV" ]]; then
  EFI_DEV="$(resolve_efi_dev || true)"
fi
if [[ -n "$EFI_DEV" && -b "$EFI_DEV" ]]; then
  ensure_efi_whick_label "$EFI_DEV" || true
  EFI_DEV="$(blkid -L WHICK-EFI -o device 2>/dev/null || echo "$EFI_DEV")"
fi

if [[ -z "$ROOT_DEV" ]]; then
  ROOT_DEV="$(python3 - <<'PY' "$PLAN_JSON"
import json, sys
plan = json.load(open(sys.argv[1]))
for c in plan.get("create") or []:
    if c.get("role") == "root":
        print(c.get("path") or "")
        break
PY
)"
fi

if [[ -z "$ROOT_DEV" || ! -b "$ROOT_DEV" ]]; then
  echo "[deploy_bootstrap] root partition not found (label whick-root)" >&2
  exit 1
fi

echo "[deploy_bootstrap] root=$ROOT_DEV bootstrap=$BOOTSTRAP"
deploy_progress 60 "Mounting target partitions…"

# Never use fuser -km (can hang forever or SIGKILL installer on USB Live).
# Never rely on `timeout` alone (busybox may not kill mount in D-state).
whick_deadline() {
  local secs="${1:-15}"
  shift
  "$@" &
  local pid=$!
  local i=0
  while kill -0 "$pid" 2>/dev/null; do
    i=$((i + 1))
    if [[ "$i" -ge "$secs" ]]; then
      kill -TERM "$pid" 2>/dev/null || true
      sleep 1
      kill -KILL "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
      return 124
    fi
    sleep 1
  done
  wait "$pid"
}

whick_release_blockdev() {
  local target="$1"
  [[ -n "$target" ]] || return 0
  # Fast lazy umount only — no fuser
  umount -l "$target" 2>/dev/null || umount -lf "$target" 2>/dev/null || true
}

whick_mount_required() {
  local dev="$1" mnt="$2"
  mkdir -p "$mnt"
  echo "[deploy_bootstrap] mount required: $dev -> $mnt"
  deploy_progress 61 "Mounting $dev…"
  # blkid with deadline (can block on bad NVMe)
  if ! whick_deadline 8 blkid "$dev" >/dev/null 2>&1; then
    echo "[deploy_bootstrap] ERROR blkid failed/timeout on $dev — wipe NVMe Linux partitions and retry" >&2
    lsblk -f "$dev" 2>/dev/null >&2 || true
    exit 1
  fi
  whick_release_blockdev "$mnt"
  whick_release_blockdev "$dev"
  # Mount with hard deadline (15s — Jul22 success was near-instant)
  if ! whick_deadline 15 mount "$dev" "$mnt"; then
    echo "[deploy_bootstrap] ERROR mount failed/timeout (15s): $dev -> $mnt" >&2
    echo "[deploy_bootstrap] HINT: dirty FS or partition busy. Wipe Linux partitions on NVMe, reboot USB, retry." >&2
    mount 2>/dev/null | grep -E "$(basename "$dev")|$mnt" >&2 || true
    lsblk -f "$dev" 2>/dev/null >&2 || true
    exit 1
  fi
  if ! mountpoint -q "$mnt"; then
    echo "[deploy_bootstrap] ERROR mount reported OK but $mnt not a mountpoint" >&2
    exit 1
  fi
  echo "[deploy_bootstrap] mount OK: $dev -> $mnt"
  deploy_progress 62 "Mounted $dev"
}

whick_mount_optional() {
  local dev="$1" mnt="$2"
  mkdir -p "$mnt"
  whick_release_blockdev "$mnt"
  whick_release_blockdev "$dev"
  if ! whick_deadline 10 mount "$dev" "$mnt"; then
    echo "[deploy_bootstrap] WARN mount failed/timeout (non-fatal): $dev -> $mnt" >&2
    return 1
  fi
  return 0
}

whick_mount_required "$ROOT_DEV" "$MNT"
deploy_progress 63 "Root mounted"
if [[ -z "$EFI_DEV" || ! -b "$EFI_DEV" ]]; then
  EFI_DEV="$(resolve_efi_dev || true)"
fi
if [[ -n "$EFI_DEV" && -b "$EFI_DEV" ]]; then
  ensure_efi_whick_label "$EFI_DEV" || true
  whick_mount_required "$EFI_DEV" "$EFI_MNT"
  deploy_progress 64 "EFI mounted"
else
  echo "[deploy_bootstrap] WARN no EFI partition found yet (will retry at grub-install)" >&2
fi

chroot_bind_mounts() {
  # Idempotent — apt + Wi-Fi dpkg both call this; remount under set -e used to
  # abort at 81% with no ERROR line (UI then showed stale "EFI mounted").
  mkdir -p "$MNT/dev" "$MNT/proc" "$MNT/sys" "$MNT/run"
  mountpoint -q "$MNT/dev" 2>/dev/null || mount --bind /dev "$MNT/dev"
  mountpoint -q "$MNT/proc" 2>/dev/null || mount --bind /proc "$MNT/proc"
  mountpoint -q "$MNT/sys" 2>/dev/null || mount --bind /sys "$MNT/sys"
  if ! mountpoint -q "$MNT/run" 2>/dev/null; then
    mount --bind /run "$MNT/run" 2>/dev/null || true
  fi
  if [[ -d /sys/firmware/efi/efivars ]]; then
    mkdir -p "$MNT/sys/firmware/efi/efivars"
    if ! mountpoint -q "$MNT/sys/firmware/efi/efivars" 2>/dev/null; then
      mount -t efivarfs efivarfs "$MNT/sys/firmware/efi/efivars" 2>/dev/null || \
        mount --bind /sys/firmware/efi/efivars "$MNT/sys/firmware/efi/efivars" 2>/dev/null || true
    fi
  fi
}

chroot_bind_umounts() {
  umount "$MNT/sys/firmware/efi/efivars" 2>/dev/null || true
  umount "$MNT/run" 2>/dev/null || true
  umount "$MNT/sys" 2>/dev/null || true
  umount "$MNT/proc" 2>/dev/null || true
  umount "$MNT/dev" 2>/dev/null || true
}

deploy_cleanup() {
  chroot_bind_umounts
  umount -lf "$MNT/../whick-rescue-mnt" 2>/dev/null || true
  if mountpoint -q "$EFI_MNT" 2>/dev/null; then umount -lf "$EFI_MNT" 2>/dev/null || true; fi
  if mountpoint -q "$MNT" 2>/dev/null; then umount -lf "$MNT" 2>/dev/null || true; fi
}
trap deploy_cleanup EXIT

avail_kb="$(df -k "$MNT" | awk 'NR==2 {print $4}')"
comp_kb="$(($(stat -c%s "$BOOTSTRAP") / 1024))"
need_kb=$((comp_kb * 10))
if [[ "$avail_kb" -lt "$need_kb" ]]; then
  echo "[deploy_bootstrap] ERROR: root too small — need ~${need_kb}KB (est), avail ${avail_kb}KB" >&2
  exit 1
fi

echo "[deploy_bootstrap] extracting… (avail=${avail_kb}KB est_need=${need_kb}KB)"
deploy_progress 65 "Extracting Ubuntu rootfs…"
case "$BOOTSTRAP" in
  *.tar.xz) tar -xJf "$BOOTSTRAP" -C "$MNT" ;;
  *.tar.gz|*.tgz) tar -xzf "$BOOTSTRAP" -C "$MNT" ;;
  *) echo "unsupported archive: $BOOTSTRAP" >&2; exit 1 ;;
esac
deploy_progress 72 "Rootfs extract done"

# bootstrap session → SSD first-boot (+ CC API URL the USB install actually used)
SESSION_SRC="${WHICK_BOOTSTRAP_SESSION:-/tmp/whick-bootstrap-session.json}"
if [[ -f "$SESSION_SRC" ]]; then
  mkdir -p "$MNT/var/lib/whick"
  cp -f "$SESSION_SRC" "$MNT/var/lib/whick/bootstrap-session.json"
  chmod 600 "$MNT/var/lib/whick/bootstrap-session.json"
fi
CANONICAL_CC_API_URL="${WHICK_CANONICAL_CC_API_URL:-https://admin.whick.org/api/v1}"
CC_ENV_URL="${WHICK_CC_API_URL:-}"
if [[ -z "$CC_ENV_URL" && -f "$SESSION_SRC" ]]; then
  CC_ENV_URL="$(python3 - <<'PY' "$SESSION_SRC"
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    print(str(d.get("cc_api_url") or "").strip())
except Exception:
    pass
PY
)"
fi
CC_ENV_URL="${CC_ENV_URL:-$CANONICAL_CC_API_URL}"
if [[ "${WHICK_PROD_INSTALL:-1}" == "1" && "${WHICK_ALLOW_NON_TUNNEL_CC:-0}" != "1" ]]; then
  CC_ENV_URL="$CANONICAL_CC_API_URL"
fi
mkdir -p "$MNT/etc/default"
printf 'WHICK_CC_API_URL=%s\n' "$CC_ENV_URL" >"$MNT/etc/default/whick-cc"
chmod 644 "$MNT/etc/default/whick-cc"
echo "[deploy_bootstrap] SSD CC URL → /etc/default/whick-cc ($CC_ENV_URL)"

# Field hardening: one live link is enough for firstboot, and console can inspect logs.
mkdir -p "$MNT/etc/systemd/system/systemd-networkd-wait-online.service.d"
cat >"$MNT/etc/systemd/system/systemd-networkd-wait-online.service.d/whick-any-link.conf" <<'WAIT'
[Service]
ExecStart=
ExecStart=/usr/lib/systemd/systemd-networkd-wait-online --any --timeout=45
WAIT
mkdir -p "$MNT/etc/systemd/system/whick-install-firstboot.service.d"
cat >"$MNT/etc/systemd/system/whick-install-firstboot.service.d/whick-no-online-block.conf" <<'UNIT'
[Unit]
After=
After=systemd-networkd.service whick-wifi-sta.service
Wants=
Wants=systemd-networkd.service whick-wifi-sta.service
UNIT
mkdir -p "$MNT/etc/sudoers.d"
cat >"$MNT/etc/sudoers.d/whick-remote" <<'SUDO'
# Whick 원격제어(CC agent) — 관제가 미니PC를 전권으로 운영 (설치·복구·진단).
# CC 터널/SSH·콘솔에서 whick 계정이 비밀번호 없이 모든 명령 실행.
whick ALL=(ALL) NOPASSWD: ALL
SUDO
chmod 440 "$MNT/etc/sudoers.d/whick-remote"

usb_artifact_path() {
  local name="$1" p
  for p in \
    "${WHICK_USB_ROOT:-}/whick-boot-connect/artifacts/$name" \
    "/opt/whick-boot-connect/artifacts/$name" \
    "${WHICK_USB_ROOT:-}/whick-boot-connect/bootstrap/$name" \
    "/opt/whick-boot-connect/bootstrap/$name"; do
    [[ -n "$p" && -f "$p" ]] && { echo "$p"; return 0; }
  done
  return 1
}

prefetch_ssd_install_artifacts() {
  local script_dir lock session_json bundle_name deb_sha deb_size dest runtime_name runtime_sha runtime_dest usb_src
  local cache_root="$MNT/var/lib/whick/install-cache"
  local deb_dir="$cache_root/docker-debs"
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  lock="${WHICK_COMPONENTS_LOCK:-$ROOT/lib/components.lock.json}"
  [[ -f "$lock" ]] || return 0
  session_json="${WHICK_BOOTSTRAP_SESSION:-}"
  [[ -n "$session_json" && -f "$session_json" ]] || return 0
  eval "$(python3 - "$lock" <<'PY'
import json, sys
lock = json.load(open(sys.argv[1]))
components = lock.get("components", {}) or {}
dc = components.get("docker_ce", {}) or {}
runtime = components.get("runtime_bundle", {}) or {}
def q(s):
    return "'" + str(s).replace("'", "'\"'\"'") + "'"
print(f"export BUNDLE_NAME={q(dc.get('deb_bundle', ''))}")
print(f"export DEB_SHA={q(dc.get('deb_sha256', ''))}")
print(f"export DEB_SIZE={q(dc.get('deb_size_bytes', ''))}")
print(f"export RUNTIME_NAME={q(runtime.get('file', ''))}")
print(f"export RUNTIME_SHA={q(runtime.get('sha256', ''))}")
PY
)"
  export WHICK_BOOTSTRAP_SESSION="$session_json"
  export WHICK_CC_API_URL="$CC_ENV_URL"
  mkdir -p "$cache_root" "$deb_dir"

  # Jul22 success path: install_linux = rootfs+GRUB only.
  # Docker/runtime download belongs to install_docker / install_runtime (do not block here).
  if [[ "${WHICK_DEPLOY_PREFETCH_DOCKER:-0}" == "1" && -n "$BUNDLE_NAME" ]]; then
    dest="$cache_root/$BUNDLE_NAME"
    if usb_src="$(usb_artifact_path "$BUNDLE_NAME" 2>/dev/null)"; then
      echo "[deploy_bootstrap] USB docker deb bundle → SSD cache ($BUNDLE_NAME)"
      cp -f "$usb_src" "$dest"
    else
      echo "[deploy_bootstrap] prefetch docker debs from CC → SSD ($BUNDLE_NAME)"
      deploy_progress 76 "Prefetching Docker packages…"
      if ! "$script_dir/whick-fetch-artifact.sh" \
        --name "$BUNDLE_NAME" \
        --dest "$dest" \
        ${DEB_SHA:+--sha256 "$DEB_SHA"} \
        --url "$CC_ENV_URL/install/bootstrap/artifact/$BUNDLE_NAME"; then
        echo "[deploy_bootstrap] WARN docker deb prefetch failed (SSD firstboot will retry)" >&2
        dest=""
      fi
    fi
    if [[ -n "${dest:-}" && -f "$dest" ]]; then
      rm -rf "$deb_dir"/*
      case "$dest" in
        *.tar.zst)
          if command -v zstd >/dev/null 2>&1; then
            tar -I zstd -xf "$dest" -C "$deb_dir"
          else
            echo "[deploy_bootstrap] WARN zstd missing — docker bundle kept as archive only" >&2
          fi
          ;;
        *.tar.gz|*.tgz) tar -xzf "$dest" -C "$deb_dir" ;;
      esac
      echo "[deploy_bootstrap] docker debs staged on SSD ($(find "$deb_dir" -maxdepth 1 -name '*.deb' | wc -l | tr -d ' ') packages)"
    fi
  elif [[ -n "$BUNDLE_NAME" ]]; then
    echo "[deploy_bootstrap] skip docker prefetch ($BUNDLE_NAME) — deferred to install_docker"
  fi

  if [[ "${WHICK_DEPLOY_PREFETCH_RUNTIME:-0}" == "1" && -n "${RUNTIME_NAME:-}" ]]; then
    runtime_dest="$cache_root/$RUNTIME_NAME"
    if usb_src="$(usb_artifact_path "$RUNTIME_NAME" 2>/dev/null)"; then
      echo "[deploy_bootstrap] USB runtime bundle → SSD cache ($RUNTIME_NAME)"
      cp -f "$usb_src" "$runtime_dest"
    else
      echo "[deploy_bootstrap] prefetch runtime bundle from CC → SSD ($RUNTIME_NAME)"
      deploy_progress 80 "Prefetching runtime bundle…"
      if ! "$script_dir/whick-fetch-artifact.sh" \
        --name "$RUNTIME_NAME" \
        --dest "$runtime_dest" \
        ${RUNTIME_SHA:+--sha256 "$RUNTIME_SHA"} \
        --url "$CC_ENV_URL/install/bootstrap/artifact/$RUNTIME_NAME"; then
        echo "[deploy_bootstrap] WARN runtime prefetch failed (SSD firstboot will retry)" >&2
        runtime_dest=""
      fi
    fi
    if [[ -f "$runtime_dest" && -n "${RUNTIME_SHA:-}" ]] && ! echo "$RUNTIME_SHA  $runtime_dest" | sha256sum -c - >/dev/null 2>&1; then
      echo "[deploy_bootstrap] WARN staged runtime sha mismatch; removing $runtime_dest" >&2
      rm -f "$runtime_dest"
    fi
  elif [[ -n "${RUNTIME_NAME:-}" ]]; then
    echo "[deploy_bootstrap] skip runtime prefetch ($RUNTIME_NAME) — deferred to install_runtime"
  fi
}
prefetch_ssd_install_artifacts || true

prefetch_ssd_remote_phases() {
  local script_dir live_root dest rel src
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  live_root="$(cd "$script_dir/.." && pwd)"
  dest="$MNT/var/lib/whick/remote-phases"
  mkdir -p "$dest/phases" "$dest/bin" "$dest/lib" "$dest/curtin"
  for rel in \
    phases/02_linux_install.sh phases/03_docker.sh phases/04_runtime.sh \
    bin/disk_plan.py bin/cc_progress.py bin/cc_client.py bin/phase_common.sh \
    bin/deploy_bootstrap_rootfs.sh bin/install-docker.sh bin/install-runtime.sh \
    bin/whick-fetch-artifact.sh bin/whick-dual-install-common.sh bin/whick-install-step.sh \
    lib/whick-disk.env lib/whick-firstboot.sh lib/whick-orchestrator-phases.sh \
    lib/bootstrap_tar_check.sh lib/components.lock.json \
    curtin/generate-curtin-config.py; do
    src="$live_root/$rel"
    [[ -f "$src" ]] || continue
    install -D -m 755 "$src" "$dest/$rel"
  done
  if [[ -f "$dest/phases/03_docker.sh" && -f "$dest/bin/cc_client.py" ]]; then
    echo "ssd-prefetch" >"$dest/.bundle-ok"
    echo "[deploy_bootstrap] SSD remote-phases prefetched from live bundle"
  fi
}
prefetch_ssd_remote_phases || true

# SSD must get DHCP on wired/USB-LAN without console setup (field: enp2s0 stayed DOWN)
mkdir -p "$MNT/etc/systemd/network"
cat >"$MNT/etc/systemd/network/10-whick-dhcp.network" <<'NET'
[Match]
Name=en* eth* enx*

[Network]
DHCP=yes
NET

# 무선 USB — SSID/PASS 를 SSD 에 이관 (재부팅 후 STA 자동 연결)
# 출처: ① provision env/json ② Live 가 이미 쓴 WPA conf (/tmp/whick-wpa.conf)
# Live 만 붙고 SSD 이관 없으면 USB 제거 후 네트워크 대기 고착 → wireless 는 FATAL
write_ssd_wifi_from_provision() {
  local ssid="" pass="" prov="" conf live_conf="" profile=""
  ssid="${WHICK_PROVISION_WIFI_SSID:-}"
  pass="${WHICK_PROVISION_WIFI_PASSWORD:-}"
  for prov in \
      /etc/whick/provision.json \
      /opt/whick/boot-connect/provision.json \
      /opt/whick-boot-connect/provision.json \
      "${WHICK_BOOT_CONNECT_SRC:-}/provision.json"
  do
    [[ -f "$prov" ]] || continue
    eval "$(python3 - "$prov" <<'PY'
import json, shlex, sys
try:
    d = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception:
    raise SystemExit(0)
ssid = str(d.get("wifi_ssid") or "").strip()
pwd = str(d.get("wifi_password") or "")
if ssid:
    print("ssid=" + shlex.quote(ssid))
    print("pass=" + shlex.quote(pwd))
PY
)" || true
    [[ -n "${ssid:-}" ]] && break
  done
  # DIY / Live STA — 이미 연결된 WPA conf 를 SSD 로 복사
  if [[ -z "$ssid" || -z "$pass" ]]; then
    for live_conf in \
        "${WHICK_LIVE_WPA_CONF:-}" \
        /tmp/whick-wpa.conf \
        /run/whick-wpa.conf \
        /etc/wpa_supplicant/wpa_supplicant.conf
    do
      [[ -n "$live_conf" && -f "$live_conf" ]] || continue
      grep -q 'network={' "$live_conf" 2>/dev/null || continue
      eval "$(python3 - "$live_conf" <<'PY'
import re, shlex, sys
from pathlib import Path
text = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
m = re.search(r'ssid=(?:"([^"]*)"|([^\s}\n]+))', text)
ssid = (m.group(1) if m and m.group(1) is not None else (m.group(2) if m else "")) or ""
ssid = ssid.strip()
if ssid:
    print("ssid=" + shlex.quote(ssid))
    print("live_conf=" + shlex.quote(sys.argv[1]))
PY
)" || true
      [[ -n "${ssid:-}" ]] && break
    done
  fi
  [[ -n "$ssid" ]] || {
    for profile in \
        "${WHICK_NET_PROFILE:-}" \
        "${WHICK_USB_PROFILE:-}"
    do
      profile="$(echo "$profile" | tr -d ' \r\n')"
      [[ -n "$profile" ]] && break
    done
    if [[ -z "$profile" ]]; then
      for prov in \
          /etc/whick/net-profile \
          /opt/whick/boot-connect/net-profile \
          /opt/whick-boot-connect/net-profile \
          "${WHICK_BOOT_CONNECT_SRC:-}/net-profile"
      do
        [[ -f "$prov" ]] || continue
        profile="$(tr -d ' \r\n' <"$prov")"
        [[ -n "$profile" ]] && break
      done
    fi
    if [[ "$profile" == "wireless" ]]; then
      echo "[deploy_bootstrap] FATAL: wireless USB but no SSID/PASS to hand off to SSD" >&2
      echo "[deploy_bootstrap] HINT: 맞춤 USB(다운로드 SSID·비밀번호) 또는 Live Wi-Fi 연결 후 재시도" >&2
      return 1
    fi
    echo "[deploy_bootstrap] no provision Wi-Fi — SSD wired DHCP only"
    return 0
  }
  mkdir -p "$MNT/etc/whick" "$MNT/var/run/wpa_supplicant" "$MNT/usr/local/sbin" \
    "$MNT/etc/systemd/system" "$MNT/etc/systemd/system/multi-user.target.wants"
  conf="$MNT/etc/whick/wpa_supplicant.conf"
  if [[ -n "${live_conf:-}" && -f "${live_conf:-}" && -z "$pass" ]]; then
    # Live 가 이미 만든 conf(PSK 포함) 를 그대로 SSD 에 복제
    cp -a "$live_conf" "$conf"
    # ctrl_interface 경로 통일
    if ! grep -q '^ctrl_interface=' "$conf" 2>/dev/null; then
      printf 'ctrl_interface=/var/run/wpa_supplicant\nupdate_config=1\n%s\n' "$(cat "$conf")" >"$conf"
    fi
    echo "[deploy_bootstrap] SSD Wi-Fi from Live WPA conf ($live_conf)"
  elif command -v wpa_passphrase >/dev/null 2>&1 && [[ -n "$pass" ]]; then
    {
      echo "ctrl_interface=/var/run/wpa_supplicant"
      echo "update_config=1"
      wpa_passphrase "$ssid" "$pass"
    } >"$conf"
  else
    # open / fallback (특수문자 최소 이스케이프)
    python3 - "$ssid" "$pass" "$conf" <<'PY'
import sys
from pathlib import Path
ssid, pwd, conf = sys.argv[1], sys.argv[2], Path(sys.argv[3])
def q(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')
lines = [
    "ctrl_interface=/var/run/wpa_supplicant",
    "update_config=1",
    "network={",
    f'\tssid="{q(ssid)}"',
]
if pwd:
    lines.append(f'\tpsk="{q(pwd)}"')
else:
    lines.append("\tkey_mgmt=NONE")
lines.append("}")
conf.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
  fi
  chmod 600 "$conf"
  printf '%s\n' "$ssid" >"$MNT/etc/whick/wifi-ssid"
  chmod 644 "$MNT/etc/whick/wifi-ssid"
  printf 'wireless\n' >"$MNT/etc/whick/net-profile"
  chmod 644 "$MNT/etc/whick/net-profile"
  cat >"$MNT/etc/systemd/network/20-whick-wifi.network" <<'WNET'
[Match]
Name=wlan* wlp* wl*

[Network]
DHCP=yes
WNET
  mkdir -p "$MNT/etc/systemd/system/systemd-networkd.service.d"
  cat >"$MNT/etc/systemd/system/systemd-networkd.service.d/whick-after-wifi-sta.conf" <<'NDROP'
[Unit]
After=whick-wifi-sta.service
Wants=whick-wifi-sta.service
NDROP
  cat >"$MNT/etc/systemd/system/whick-install-firstboot.service" <<'FBUNIT'
[Unit]
Description=Whick OS firstboot (runtime on SSD)
After=systemd-networkd.service whick-wifi-sta.service
Wants=systemd-networkd.service whick-wifi-sta.service
ConditionPathExists=!/var/lib/whick/firstboot-done

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/whick-firstboot.sh
RemainAfterExit=yes
Restart=on-failure
RestartSec=60

[Install]
WantedBy=multi-user.target
FBUNIT
  cat >"$MNT/usr/local/sbin/whick-wifi-sta.sh" <<'WIFI'
#!/bin/bash
# SSD first-boot — provision Wi-Fi STA (wireless USB install handoff)
# Wi-Fi 실패해도 systemd-networkd 를 되살려 유선(en*/enx*) DHCP 폴백 가능해야 함 (세션 323)
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
CONF=/etc/whick/wpa_supplicant.conf
LOG=/var/log/whick-wifi-sta.log
exec >>"$LOG" 2>&1
echo "=== whick-wifi-sta $(date -Is) ==="

restore_networkd() {
  systemctl start systemd-networkd 2>/dev/null || systemctl restart systemd-networkd 2>/dev/null || true
}
trap restore_networkd EXIT

[[ -f "$CONF" ]] || { echo "no $CONF — skip"; exit 0; }
WPA_BIN=""
if [[ -x /usr/sbin/wpa_supplicant ]]; then
  WPA_BIN=/usr/sbin/wpa_supplicant
elif [[ -x /sbin/wpa_supplicant ]]; then
  WPA_BIN=/sbin/wpa_supplicant
else
  WPA_BIN="$(command -v wpa_supplicant 2>/dev/null || true)"
fi
if [[ -z "$WPA_BIN" ]]; then
  echo "wpa_supplicant missing — leave networkd for wired fallback"; exit 1
fi
if ldd "$WPA_BIN" 2>/dev/null | grep -qE 'libnl-(3|genl-3|route-3)\.so\.[0-9]+ => not found'; then
  echo "wpa_supplicant libnl missing — leave networkd for wired fallback"
  ldd "$WPA_BIN" 2>/dev/null | grep -i nl || true
  exit 1
fi
# Wi-Fi 칩·드라이버는 sysinit 직후엔 아직 없을 수 있음 (세션 320: no iface → WAN 없음)
if [[ -f /opt/whick-boot-connect/whick-kernel-modules.sh ]]; then
  # shellcheck source=/dev/null
  . /opt/whick-boot-connect/whick-kernel-modules.sh
  whick_load_net_modules 2>/dev/null || true
fi
wifi=""
for _ in $(seq 1 120); do
  for p in /sys/class/net/*/wireless; do
    [[ -e "$p" ]] || continue
    wifi="$(basename "$(dirname "$p")")"
    break 2
  done
  sleep 1
done
[[ -n "$wifi" ]] || { echo "no wireless iface after 120s — wired fallback"; exit 1; }
echo "iface=$wifi ssid=$(cat /etc/whick/wifi-ssid 2>/dev/null || true)"
if command -v nmcli >/dev/null 2>&1; then
  nmcli device set "$wifi" managed no 2>/dev/null || true
fi
mkdir -p /var/run/wpa_supplicant
rfkill unblock all 2>/dev/null || true
systemctl stop systemd-networkd 2>/dev/null || true
killall wpa_supplicant 2>/dev/null || true
ip link set "$wifi" up
"$WPA_BIN" -B -i "$wifi" -c "$CONF"
ok=0
st=""
for _ in $(seq 1 75); do
  st="$(wpa_cli -i "$wifi" status 2>/dev/null | sed -n 's/^wpa_state=//p' || true)"
  if [[ "$st" == "COMPLETED" ]]; then
    ok=1
    break
  fi
  sleep 1
done
[[ "$ok" -eq 1 ]] || { echo "associate failed state=${st:-empty}"; exit 1; }
# 성공 시에도 trap 이 networkd 를 올림 — 여기서는 DHCP 만
restore_networkd
trap - EXIT
sleep 2
if command -v networkctl >/dev/null 2>&1; then
  networkctl renew "$wifi" 2>/dev/null || true
elif command -v dhcpcd >/dev/null 2>&1; then
  dhcpcd -w -t 20 "$wifi" 2>/dev/null || true
elif command -v dhclient >/dev/null 2>&1; then
  dhclient -1 -v -timeout 20 "$wifi" 2>/dev/null || true
fi
for _ in $(seq 1 40); do
  if ip -4 -o addr show "$wifi" 2>/dev/null | grep -q ' inet '; then
    echo "wifi STA OK ip=$(ip -4 -o addr show dev "$wifi" | awk '{print $4}')"
    exit 0
  fi
  sleep 1
done
ip -4 addr show "$wifi" || true
echo "wifi associated but no DHCP IPv4"
exit 1
WIFI
  chmod 755 "$MNT/usr/local/sbin/whick-wifi-sta.sh"
  cat >"$MNT/etc/systemd/system/whick-wifi-sta.service" <<'UNIT'
[Unit]
Description=Whick provision Wi-Fi STA (SSD first boot)
DefaultDependencies=no
After=systemd-udev-settle.service
Before=systemd-networkd.service network-online.target whick-install-firstboot.service
Wants=network-pre.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/sbin/whick-wifi-sta.sh
TimeoutStartSec=180
# Soft-fail: exit 1 from the script (no wireless iface / associate timeout) is not
# a systemd failure.  The firstboot service retries Wi-Fi via ensure_ssd_network()
# independently, and displaying FAILED is misleading when the install proceeds on
# wired DHCP anyway.
SuccessExitStatus=0 1
Restart=on-failure
RestartSec=45
StartLimitBurst=3

[Install]
WantedBy=multi-user.target
UNIT
  ln -sfn /etc/systemd/system/whick-wifi-sta.service \
    "$MNT/etc/systemd/system/multi-user.target.wants/whick-wifi-sta.service"
  # chroot apt 에 wpasupplicant 포함 요청
  export WHICK_SSD_NEED_WPA=1
  echo "[deploy_bootstrap] SSD Wi-Fi handoff written (ssid=$ssid)"
}
write_ssd_wifi_from_provision || {
  echo "[deploy_bootstrap] FATAL: SSD Wi-Fi handoff required for wireless install" >&2
  exit 1
}

# SSD Wi-Fi handoff post-write verification — reboot gate (2026-08-05 wireless USB)
# Confirms the SSD will have a working wpa_supplicant.conf BEFORE host_reboot.
# Silent failures here cause SSD firstboot to be networkless → unrecoverable offline.
verify_ssd_wifi_handoff() {
  local wifi_conf="$MNT/etc/whick/wpa_supplicant.conf"
  local wifi_ssid_file="$MNT/etc/whick/wifi-ssid"
  local net_profile="$MNT/etc/whick/net-profile"
  local profile=""

  if [[ -f "$net_profile" ]]; then
    profile="$(tr -d ' \r\n' <"$net_profile")"
  fi
  [[ "$profile" == "wireless" ]] || return 0

  # 1. Config file must exist
  if [[ ! -f "$wifi_conf" ]]; then
    echo "[deploy_bootstrap] FATAL: wireless install but SSD wpa_supplicant.conf missing — refusing reboot into networkless SSD" >&2
    return 1
  fi

  # 2. Must contain a valid network block
  if ! grep -q 'network={' "$wifi_conf" 2>/dev/null; then
    echo "[deploy_bootstrap] FATAL: SSD wpa_supplicant.conf has no network block" >&2
    return 1
  fi

  # 3. Permissions must be 600
  local perms
  perms="$(stat -c '%a' "$wifi_conf" 2>/dev/null || echo '')"
  if [[ "$perms" != "600" ]]; then
    echo "[deploy_bootstrap] FATAL: SSD wpa_supplicant.conf permissions $perms (need 600)" >&2
    return 1
  fi

  # 4. SSID must match wifi-ssid companion file
  local expected_ssid="" actual_ssid="" sz=""
  if [[ -f "$wifi_ssid_file" ]]; then
    expected_ssid="$(cat "$wifi_ssid_file")"
    actual_ssid="$(python3 - <<'PY' "$wifi_conf"
import re, sys
text = open(sys.argv[1]).read()
m = re.search(r'ssid="([^"]*)"', text)
if m:
    print(m.group(1))
PY
)" || true
    if [[ -n "$expected_ssid" && -n "$actual_ssid" && "$expected_ssid" != "$actual_ssid" ]]; then
      echo "[deploy_bootstrap] FATAL: SSD SSID mismatch — wifi-ssid=$expected_ssid vs wpa_conf=$actual_ssid" >&2
      return 1
    fi
  fi

  # 5. File size sanity (should not be empty/tiny)
  sz="$(stat -c%s "$wifi_conf" 2>/dev/null || echo 0)"
  if [[ "$sz" -lt 20 ]]; then
    echo "[deploy_bootstrap] FATAL: SSD wpa_supplicant.conf too small ($sz bytes)" >&2
    return 1
  fi

  echo "[deploy_bootstrap] SSD Wi-Fi handoff VERIFIED (ssid=$expected_ssid perms=$perms size=$sz)"
  return 0
}
verify_ssd_wifi_handoff || {
  echo "[deploy_bootstrap] FATAL: SSD Wi-Fi handoff verification failed — refusing to reboot into networkless SSD" >&2
  exit 1
}

# /tmp — tarball excludes ./tmp; avoid systemd tmp.mount FAILED on first SSD boot
mkdir -p "$MNT/tmp"
chmod 1777 "$MNT/tmp"
mkdir -p "$MNT/etc/systemd/system"
ln -sf /dev/null "$MNT/etc/systemd/system/tmp.mount"

ensure_ssd_networkd_package() {
  local need_pkgs=()
  local pkg
  for pkg in systemd-networkd iproute2 zstd linux-firmware; do
    if ! chroot "$MNT" dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "install ok installed"; then
      need_pkgs+=("$pkg")
    fi
  done
  if [[ "${WHICK_SSD_NEED_WPA:-0}" == "1" ]]; then
    # libnl-* — wpasupplicant 런타임 필수 (없으면 SSD first-boot Wi-Fi exit 127)
    for pkg in wpasupplicant iw wireless-regdb libnl-3-200 libnl-genl-3-200 libnl-route-3-200; do
      if ! chroot "$MNT" dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "install ok installed"; then
        need_pkgs+=("$pkg")
      fi
    done
  fi
  if [[ "${#need_pkgs[@]}" -eq 0 ]]; then
    echo "[deploy_bootstrap] systemd-networkd/iproute2/zstd/linux-firmware already installed"
    return 0
  fi
  echo "[deploy_bootstrap] installing SSD rootfs packages: ${need_pkgs[*]} (chroot apt)…"
  deploy_progress 80 "Installing SSD packages (apt)…"
  chroot_bind_mounts
  cp /etc/resolv.conf "$MNT/etc/resolv.conf" 2>/dev/null || true
  # apt can hang forever on bad DNS/mirrors — hard cap so install_linux does not sit frozen.
  if timeout 180 chroot "$MNT" apt-get update -qq 2>/dev/null \
    && timeout 300 chroot "$MNT" env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends \
         "${need_pkgs[@]}" 2>/dev/null; then
    echo "[deploy_bootstrap] SSD rootfs packages installed via chroot apt"
    timeout 120 chroot "$MNT" update-initramfs -u 2>/dev/null || true
  else
    echo "[deploy_bootstrap] WARN chroot apt could not install SSD packages (USB may lack WAN/DNS)" >&2
  fi
}

# SSD rootfs 에 wpa 있는지 — chroot `command -v` 는 PATH 에 /usr/sbin 없어
# 설치 성공인데도 missing 으로 오판했음 (세션 306: dpkg Unpacking over 반복).
ssd_has_wpa_supplicant() {
  [[ -x "$MNT/usr/sbin/wpa_supplicant" || -x "$MNT/sbin/wpa_supplicant" ]] && return 0
  chroot "$MNT" env PATH=/usr/sbin:/usr/bin:/sbin:/bin \
    command -v wpa_supplicant >/dev/null 2>&1
}

# 바이너리만 있고 libnl 누락이면 first-boot 에서 exit 127 (세션 323)
ssd_wpa_runtime_ok() {
  ssd_has_wpa_supplicant || return 1
  local bin=""
  if [[ -x "$MNT/usr/sbin/wpa_supplicant" ]]; then
    bin=/usr/sbin/wpa_supplicant
  elif [[ -x "$MNT/sbin/wpa_supplicant" ]]; then
    bin=/sbin/wpa_supplicant
  else
    bin="$(chroot "$MNT" env PATH=/usr/sbin:/usr/bin:/sbin:/bin command -v wpa_supplicant 2>/dev/null || true)"
  fi
  [[ -n "$bin" ]] || return 1
  local ldd_out
  ldd_out="$(chroot "$MNT" env PATH=/usr/sbin:/usr/bin:/sbin:/bin ldd "$bin" 2>/dev/null || true)"
  if echo "$ldd_out" | grep -qE 'libnl-(3|genl-3|route-3)\.so\.[0-9]+ => not found'; then
    echo "[deploy_bootstrap] WARN wpa_supplicant present but libnl not found (ldd)" >&2
    return 1
  fi
  return 0
}

# Live ISO pool → SSD chroot (apt 실패해도 무선 이관 가능)
install_ssd_wpa_from_iso_pool() {
  [[ "${WHICK_SSD_NEED_WPA:-0}" == "1" ]] || return 0
  if ssd_wpa_runtime_ok; then
    echo "[deploy_bootstrap] wpa_supplicant+libnl OK in SSD rootfs"
    return 0
  fi
  if ssd_has_wpa_supplicant; then
    echo "[deploy_bootstrap] wpa_supplicant binary present but libnl incomplete — installing deps" >&2
  fi
  deploy_progress 81 "Installing Wi-Fi tools onto SSD…"
  local attempt=0
  local root found dest="/var/tmp/whick-wifi-debs"
  local host_cache="/var/tmp/whick-wifi-debs"
  # Phase-bundle 동봉 deb — ISO remount/pool 불필요 (유선과 같은 안정 경로)
  local bundle_debs="$ROOT/wifi-debs"
  while [[ "$attempt" -lt 5 ]]; do
    attempt=$((attempt + 1))
    found=0
    mkdir -p "$MNT$dest"
    if [[ -d "$bundle_debs" ]]; then
      shopt -s nullglob
      local bundled=( "$bundle_debs"/*.deb )
      shopt -u nullglob
      if [[ "${#bundled[@]}" -gt 0 ]]; then
        cp -f "${bundled[@]}" "$MNT$dest/" && found=1
        echo "[deploy_bootstrap] Wi-Fi debs from phase-bundle ($bundle_debs)" >&2
      fi
    fi
    # Live 가 이미 설치할 때 캐시한 deb
    if [[ "$found" -ne 1 && -d "$host_cache" ]]; then
      shopt -s nullglob
      local cached=( "$host_cache"/*.deb )
      shopt -u nullglob
      if [[ "${#cached[@]}" -gt 0 ]]; then
        cp -f "${cached[@]}" "$MNT$dest/" && found=1
      fi
    fi
    # Wi-Fi 끊김과 무관 — ISO/USB 미디어 재탐색
    if [[ "$found" -ne 1 ]]; then
      for root in /cdrom /mnt/whick-media /run/live/medium /media/cdrom; do
        [[ -d "$root/pool" ]] || continue
        shopt -s nullglob
        local pcs=( "$root"/pool/main/p/pcsc-lite/libpcsclite1_*.deb )
        local wpa=( "$root"/pool/main/w/wpa/wpasupplicant_*.deb )
        local iwdebs=( "$root"/pool/main/i/iw/iw_*.deb )
        local nl3=( "$root"/pool/main/libn/libnl3/libnl-3-200_*.deb )
        local nlgenl=( "$root"/pool/main/libn/libnl3/libnl-genl-3-200_*.deb )
        local nlroute=( "$root"/pool/main/libn/libnl3/libnl-route-3-200_*.deb )
        local overlay=()
        [[ -d "$root/whick-os/debs" ]] && overlay=( "$root"/whick-os/debs/*.deb )
        shopt -u nullglob
        if [[ -f "${pcs[0]:-}" ]]; then cp -f "${pcs[0]}" "$MNT$dest/"; found=1; fi
        if [[ -f "${wpa[0]:-}" ]]; then cp -f "${wpa[0]}" "$MNT$dest/"; found=1; fi
        if [[ -f "${iwdebs[0]:-}" ]]; then cp -f "${iwdebs[0]}" "$MNT$dest/"; found=1; fi
        if [[ -f "${nl3[0]:-}" ]]; then cp -f "${nl3[0]}" "$MNT$dest/"; found=1; fi
        if [[ -f "${nlgenl[0]:-}" ]]; then cp -f "${nlgenl[0]}" "$MNT$dest/"; found=1; fi
        if [[ -f "${nlroute[0]:-}" ]]; then cp -f "${nlroute[0]}" "$MNT$dest/"; found=1; fi
        local f
        for f in "${overlay[@]:-}"; do
          [[ -f "$f" ]] && cp -f "$f" "$MNT$dest/" && found=1
        done
        [[ "$found" -eq 1 ]] && break
      done
    fi
    # Live 호스트에 wpa 있으면 (이미 STA 연결됨) apt-get download 폴백
    if [[ "$found" -ne 1 ]] && command -v apt-get >/dev/null 2>&1 \
        && command -v wpa_supplicant >/dev/null 2>&1; then
      echo "[deploy_bootstrap] Wi-Fi debs: apt-get download fallback (Live host)" >&2
      mkdir -p "$host_cache"
      if ( cd "$host_cache" && apt-get download -qq wpasupplicant iw libpcsclite1 \
            libnl-3-200 libnl-genl-3-200 libnl-route-3-200 2>/dev/null ); then
        shopt -s nullglob
        local dl=( "$host_cache"/*.deb )
        shopt -u nullglob
        if [[ "${#dl[@]}" -gt 0 ]]; then
          cp -f "${dl[@]}" "$MNT$dest/" && found=1
        fi
      fi
    fi
    if [[ "$found" -ne 1 ]]; then
      echo "[deploy_bootstrap] WARN Wi-Fi debs not found attempt=$attempt — remount wait" >&2
      sleep 4
      continue
    fi
    chroot_bind_mounts
    # dpkg 비0 이어도 바이너리만 있으면 통과 (의존성 warn / 이미 설치 over)
    chroot "$MNT" env PATH=/usr/sbin:/usr/bin:/sbin:/bin DEBIAN_FRONTEND=noninteractive \
      bash -c "dpkg -i $dest/*.deb || { dpkg --configure -a; dpkg -i $dest/*.deb; }" || true
    if ssd_wpa_runtime_ok; then
      echo "[deploy_bootstrap] SSD wpa_supplicant+libnl OK from ISO pool (attempt=$attempt)"
      return 0
    fi
    echo "[deploy_bootstrap] WARN dpkg wpa attempt=$attempt failed — binary/libnl still incomplete" >&2
    sleep 4
  done
  if ssd_wpa_runtime_ok; then
    return 0
  fi
  echo "[deploy_bootstrap] ERROR: wireless provision but wpa_supplicant/libnl still broken after retries" >&2
  return 1
}

ensure_ssd_networkd_package
if [[ "${WHICK_SSD_NEED_WPA:-0}" == "1" ]]; then
  install_ssd_wpa_from_iso_pool || {
    echo "[deploy_bootstrap] FATAL: cannot put Wi-Fi tools on SSD — wireless-only install would stall after reboot" >&2
    exit 1
  }
fi
deploy_progress 84 "Configuring SSD network / first-boot…"
if chroot "$MNT" sh -c 'command -v systemctl >/dev/null 2>&1'; then
  chroot "$MNT" systemctl enable systemd-networkd.service 2>/dev/null || true
  chroot "$MNT" systemctl enable systemd-networkd-wait-online.service 2>/dev/null || true
  if [[ "${WHICK_SSD_NEED_WPA:-0}" == "1" ]]; then
    chroot "$MNT" systemctl enable whick-wifi-sta.service 2>/dev/null || true
    chroot "$MNT" systemctl enable whick-install-firstboot.service 2>/dev/null || true
  fi
fi
echo "[deploy_bootstrap] SSD network DHCP config written (systemd-networkd)"

# persistent journal — SSD boot/firstboot errors survive a reboot (field debugging)
mkdir -p "$MNT/etc/systemd/journald.conf.d" "$MNT/var/log/journal"
cat >"$MNT/etc/systemd/journald.conf.d/whick-persistent.conf" <<'JRN'
[Journal]
Storage=persistent
JRN
echo "[deploy_bootstrap] SSD persistent journal enabled"

# Always refresh first-boot scripts from the live phase bundle (bootstrap tar may be stale)
DEPLOY_LIVE="$(cd "$(dirname "$0")/.." && pwd)"
for _fb in whick-firstboot.sh whick-orchestrator-phases.sh; do
  if [[ -f "$DEPLOY_LIVE/lib/$_fb" ]]; then
    install -m 755 "$DEPLOY_LIVE/lib/$_fb" "$MNT/usr/local/sbin/$_fb"
    echo "[deploy_bootstrap] refreshed /usr/local/sbin/$_fb from phase bundle"
  fi
done

# boot-connect for SSD first-boot (CC pull + agent)
BC_SRC="${WHICK_BOOT_CONNECT_SRC:-}"
if [[ -z "$BC_SRC" && -d "${WHICK_REMOTE_PHASE_ROOT:-}/../boot-connect" ]]; then
  BC_SRC="$(cd "${WHICK_REMOTE_PHASE_ROOT}/.." && pwd)/boot-connect"
fi
if [[ -z "$BC_SRC" && -d /opt/whick-boot-connect ]]; then
  BC_SRC=/opt/whick-boot-connect
fi
if [[ -n "$BC_SRC" && -d "$BC_SRC" ]]; then
  mkdir -p "$MNT/opt"
  cp -a "$BC_SRC" "$MNT/opt/whick-boot-connect" 2>/dev/null || true
  echo "[deploy_bootstrap] boot-connect from $BC_SRC"
fi

# fstab from plan (+ 2번째 이상 SSD -> /mnt/music/diskN, 있으면)
python3 - <<'PY' "$PLAN_JSON" "$PLAN_EXTRA_JSON" "$MNT/etc/fstab" "$MNT"
import json, sys
from pathlib import Path

plan = json.load(open(sys.argv[1]))
fstab = Path(sys.argv[3])
mnt_root = Path(sys.argv[4])
lines = []
mounts = []
if plan.get("uefi"):
    lines.append("LABEL=WHICK-EFI  /boot/efi  vfat  umask=0077  0  1")
lines.append("LABEL=whick-root  /  ext4  defaults  0  1")
preserve = plan.get("preserve") or []
for p in preserve:
    label = p.get("label") or "whick-music"
    mount = p.get("mount") or "/mnt/music"
    lines.append(f"LABEL={label}  {mount}  ext4  defaults  0  2")
    mounts.append(mount)
for spec in plan.get("create") or []:
    if spec.get("role") == "music":
        label = spec.get("label") or "whick-music"
        mount = spec.get("mount") or "/mnt/music"
        lines.append(f"LABEL={label}  {mount}  ext4  defaults  0  2")
        mounts.append(mount)

try:
    extra_plans = json.load(open(sys.argv[2]))
except (FileNotFoundError, json.JSONDecodeError):
    extra_plans = []
for extra in extra_plans or []:
    entries = list(extra.get("preserve") or [])
    entries += [s for s in (extra.get("create") or []) if s.get("role") == "music_extra"]
    for item in entries:
        label = item.get("label")
        mount = item.get("mount")
        if not label or not mount:
            continue
        lines.append(f"LABEL={label}  {mount}  ext4  defaults,nofail  0  2")
        mounts.append(mount)

fstab.write_text("\n".join(lines) + "\n")
for mount in mounts:
    (mnt_root / mount.lstrip("/")).mkdir(parents=True, exist_ok=True)
print(f"[deploy_bootstrap] fstab written ({len(mounts)} mount(s))")
PY

ensure_boot_artifacts_for_grub() {
  local kver=""
  kver="$(ls "$MNT/lib/modules" 2>/dev/null | head -1)"
  [[ -n "$kver" ]] || return 0
  if [[ -f "$MNT/boot/vmlinuz-${kver}" && ! -L "$MNT/boot/vmlinuz" ]]; then
    ln -sf "vmlinuz-${kver}" "$MNT/boot/vmlinuz"
  fi
  if [[ -f "$MNT/boot/initrd.img" && ! -f "$MNT/boot/initrd.img-${kver}" ]]; then
    cp -a "$MNT/boot/initrd.img" "$MNT/boot/initrd.img-${kver}"
    echo "[deploy_bootstrap] initrd.img-${kver} from prebuilt initrd.img"
  fi
  if [[ ! -f "$MNT/boot/initrd.img" && -f "$MNT/boot/initrd.img-${kver}" ]]; then
    cp -a "$MNT/boot/initrd.img-${kver}" "$MNT/boot/initrd.img"
  fi
}

# GRUB — target Ubuntu chroot (UEFI stub + /boot/grub/grub.cfg + initrd)
deploy_progress 86 "Installing bootloader (GRUB)…"
DISK_DEV="${WHICK_TARGET_DISK:-}"
if [[ -z "$DISK_DEV" ]]; then
  DISK_DEV="$(python3 - <<'PY' "$PLAN_JSON"
import json, sys
print(json.load(open(sys.argv[1])).get("disk") or "")
PY
)"
fi
PLAN_UEFI="$(python3 - <<'PY' "$PLAN_JSON"
import json, sys
print("1" if json.load(open(sys.argv[1])).get("uefi") else "0")
PY
)"

verify_grub_cfg_bootable() {
  local cfg="$MNT/boot/grub/grub.cfg"
  python3 - <<'PY' "$cfg" "$MNT"
import re, sys
from pathlib import Path

cfg = Path(sys.argv[1])
mnt = Path(sys.argv[2])
text = cfg.read_text()
linux_paths = re.findall(r"^\s*linux\s+(\S+)", text, re.M)
initrd_paths = re.findall(r"^\s*initrd\s+(\S+)", text, re.M)
if not linux_paths:
    raise SystemExit("grub.cfg has no linux lines")
if len(initrd_paths) < len(linux_paths):
    # UEFI Firmware Settings menuentry has linux-like lines without initrd — require any initrd
    if not initrd_paths:
        raise SystemExit(
            f"grub.cfg missing initrd lines (linux={len(linux_paths)} initrd={len(initrd_paths)}) "
            "— NVMe root needs initramfs; see github.com/jillravaliya/kernel-panic-study"
        )
for rel in initrd_paths:
    path = mnt / rel.lstrip("/")
    if not path.is_file():
        raise SystemExit(f"initrd missing on disk: {rel}")
for rel in linux_paths:
    path = mnt / rel.lstrip("/")
    if not path.is_file():
        raise SystemExit(f"vmlinuz missing on disk: {rel}")
print(f"[deploy_bootstrap] grub.cfg bootable ({len(linux_paths)} linux + initrd pairs)")
PY
}

patch_grub_root_uuid() {
  python3 - <<'PY' "$MNT/boot/grub/grub.cfg" "$ROOT_UUID"
import re, sys
from pathlib import Path

cfg = Path(sys.argv[1])
root_uuid = sys.argv[2].strip()
if not re.fullmatch(r"[0-9a-fA-F-]{36}", root_uuid):
    raise SystemExit(f"invalid root UUID: {root_uuid!r}")
text = cfg.read_text()
patched = text
patched = re.sub(r"root=/dev/\S+", f"root=UUID={root_uuid}", patched)
patched = re.sub(r"root=LABEL=whick-root\b", f"root=UUID={root_uuid}", patched)
if f"root=UUID={root_uuid}" not in patched:
    raise SystemExit(f"grub.cfg missing root=UUID={root_uuid}")
cfg.write_text(patched)
print(f"[deploy_bootstrap] grub.cfg root=UUID={root_uuid}")
PY
}

patch_grub_initrd_if_missing() {
  python3 - <<'PY' "$MNT/boot/grub/grub.cfg" "$MNT"
import re, sys
from pathlib import Path

cfg = Path(sys.argv[1])
mnt = Path(sys.argv[2])
text = cfg.read_text()
if re.search(r"^\s*initrd\s+", text, re.M):
    raise SystemExit(0)
mods = Path(mnt / "lib/modules")
if not mods.is_dir():
    raise SystemExit("no /lib/modules for initrd patch")
kver = next(p.name for p in mods.iterdir() if p.is_dir())
initrd = f"/boot/initrd.img-{kver}"
if not (mnt / initrd.lstrip("/")).is_file():
    initrd = "/boot/initrd.img"
if not (mnt / initrd.lstrip("/")).is_file():
    raise SystemExit("no initrd image on /boot")
out = []
for line in text.splitlines():
    out.append(line)
    if re.match(r"\s*linux\s+.*vmlinuz", line):
        out.append(f"	initrd  {initrd}")
cfg.write_text("\n".join(out) + "\n")
print(f"[deploy_bootstrap] grub.cfg patched initrd {initrd}")
PY
}

run_grub_mkconfig() {
  # Leftover Ubuntu on same disk (os-prober) can mount ESP/other parts and leave them busy.
  mkdir -p "$MNT/etc/default"
  if [[ -f "$MNT/etc/default/grub" ]]; then
    if grep -q '^GRUB_DISABLE_OS_PROBER=' "$MNT/etc/default/grub" 2>/dev/null; then
      sed -i 's/^GRUB_DISABLE_OS_PROBER=.*/GRUB_DISABLE_OS_PROBER=true/' "$MNT/etc/default/grub"
    else
      printf '\nGRUB_DISABLE_OS_PROBER=true\n' >>"$MNT/etc/default/grub"
    fi
  else
    printf 'GRUB_DISABLE_OS_PROBER=true\n' >"$MNT/etc/default/grub"
  fi
  if ! chroot "$MNT" env GRUB_DISABLE_OS_PROBER=true /usr/sbin/grub-mkconfig -o /boot/grub/grub.cfg; then
    echo "[deploy_bootstrap] ERROR grub-mkconfig failed — /boot/grub/grub.cfg missing" >&2
    return 1
  fi
  if [[ ! -f "$MNT/boot/grub/grub.cfg" ]]; then
    echo "[deploy_bootstrap] ERROR /boot/grub/grub.cfg not created after grub-mkconfig" >&2
    return 1
  fi
  patch_grub_root_uuid
  patch_grub_initrd_if_missing || true
  echo "[deploy_bootstrap] grub-mkconfig OK (os-prober disabled)"
}

if [[ ! -x "$MNT/usr/sbin/grub-install" ]]; then
  echo "[deploy_bootstrap] ERROR target rootfs missing /usr/sbin/grub-install (grub-efi-amd64)" >&2
  exit 1
fi

find_host_grub_install() {
  WHICK_MINI="${WHICK_MINI:-/opt/whick-boot-connect/mini}"
  if command -v grub-install >/dev/null 2>&1; then
    command -v grub-install
    return 0
  fi
  for candidate in \
    "${WHICK_MINI}/usr/sbin/grub-install" \
    "${WHICK_MINI}/sbin/grub-install"; do
    if [[ -x "$candidate" ]]; then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

find_target_grubx64() {
  local candidate
  for candidate in \
    "$MNT/usr/lib/grub/x86_64-efi/grubx64.efi" \
    "$MNT/usr/lib/grub/x86_64-efi/monolithic/grubx64.efi" \
    "$MNT/usr/lib/grub/x86_64-efi-signed/grubx64.efi.signed"; do
    if [[ -f "$candidate" ]]; then
      echo "$candidate"
      return 0
    fi
  done
  find "$MNT/usr/lib/grub" -name 'grubx64.efi*' -type f 2>/dev/null | head -1
}

manual_uefi_boot_files() {
  local shim="" grubx64="" mmx64=""
  for candidate in \
    "$MNT/usr/lib/shim/shimx64.efi" \
    "$MNT/usr/lib/shim/shim.efi"; do
    if [[ -f "$candidate" ]]; then
      shim="$candidate"
      break
    fi
  done
  grubx64="$(find_target_grubx64)"
  mmx64="$MNT/usr/lib/shim/mmx64.efi"
  [[ -n "$shim" && -n "$grubx64" && -f "$grubx64" ]] || {
    echo "[deploy_bootstrap] manual EFI: shim=${shim:-missing} grubx64=${grubx64:-missing}" >&2
    return 1
  }
  local ubuntu_dir="$EFI_MNT/EFI/ubuntu"
  local boot_dir="$EFI_MNT/EFI/BOOT"
  mkdir -p "$ubuntu_dir" "$boot_dir"
  cp -f "$shim" "$ubuntu_dir/shimx64.efi"
  cp -f "$grubx64" "$ubuntu_dir/grubx64.efi"
  [[ -f "$mmx64" ]] && cp -f "$mmx64" "$ubuntu_dir/mmx64.efi"
  cp -f "$shim" "$boot_dir/BOOTX64.EFI"
  cp -f "$grubx64" "$boot_dir/grubx64.efi"
  echo "[deploy_bootstrap] manual EFI shim+grubx64 copied to ESP"
  return 0
}

host_grub_uefi_install() {
  local host_grub target_grub_dir
  host_grub="$(find_host_grub_install)" || return 1
  target_grub_dir="$MNT/usr/lib/grub/x86_64-efi"
  [[ -d "$target_grub_dir" ]] || return 1
  "$host_grub" --target=x86_64-efi \
    --directory="$target_grub_dir" \
    --efi-directory="$EFI_MNT" \
    --boot-directory="$MNT/boot" \
    --root-directory="$MNT" \
    --recheck --no-floppy --no-nvram "$@"
}

chroot_grub_uefi_install() {
  chroot "$MNT" env PATH=/usr/sbin:/usr/bin:/sbin:/bin \
    /usr/sbin/grub-install --target=x86_64-efi \
    --efi-directory=/boot/efi --boot-directory=/boot \
    --bootloader-id=ubuntu --recheck --no-floppy --no-nvram "$@"
}

chroot_bind_mounts

echo "[deploy_bootstrap] grub-install…"
echo "[deploy_bootstrap] UEFI=${PLAN_UEFI} EFI_DEV=${EFI_DEV:-none} DISK=${DISK_DEV:-none}" >&2
_grub_ok=0
if [[ "$PLAN_UEFI" == "1" ]]; then
  if [[ -z "$EFI_DEV" || ! -b "$EFI_DEV" ]]; then
    EFI_DEV="$(resolve_efi_dev || true)"
  fi
  if [[ -z "$EFI_DEV" || ! -b "$EFI_DEV" ]]; then
    echo "[deploy_bootstrap] ERROR UEFI plan but EFI/ESP partition missing (no WHICK-EFI / ESP GUID / vfat)" >&2
    lsblk -f "${DISK_DEV:-}" 2>/dev/null >&2 || lsblk -f >&2 || true
    exit 1
  fi
  ensure_efi_whick_label "$EFI_DEV" || true
  if ! mountpoint -q "$EFI_MNT" 2>/dev/null; then
    whick_mount_required "$EFI_DEV" "$EFI_MNT"
  fi
  # USB Live: shim copy is reliable; grub-install from chroot/host often fails on the USB Live host.
  if manual_uefi_boot_files; then
    _grub_ok=1
    echo "[deploy_bootstrap] UEFI boot via shim copy (primary USB live path)"
  else
    echo "[deploy_bootstrap] WARN manual EFI shim copy failed" >&2
    ls -la "$MNT/usr/lib/shim" 2>/dev/null >&2 || true
    ls -la "$MNT/usr/lib/grub/x86_64-efi" 2>/dev/null >&2 || true
  fi
  if chroot_grub_uefi_install; then
    _grub_ok=1
    echo "[deploy_bootstrap] chroot grub-install EFI/ubuntu OK"
  else
    echo "[deploy_bootstrap] WARN chroot grub-install EFI/ubuntu failed" >&2
  fi
  if chroot_grub_uefi_install --removable; then
    _grub_ok=1
    echo "[deploy_bootstrap] chroot grub-install EFI/BOOT removable OK"
  else
    echo "[deploy_bootstrap] WARN chroot grub-install removable failed" >&2
  fi
  if [[ "$_grub_ok" -ne 1 ]] && host_grub_uefi_install --removable; then
    _grub_ok=1
    echo "[deploy_bootstrap] host grub-install EFI/BOOT removable OK"
  fi
  if [[ "$_grub_ok" -ne 1 ]] && host_grub_uefi_install; then
    _grub_ok=1
    echo "[deploy_bootstrap] host grub-install OK"
  fi
  if [[ "$_grub_ok" -ne 1 ]] && manual_uefi_boot_files; then
    _grub_ok=1
  fi
elif [[ -n "$DISK_DEV" && -b "$DISK_DEV" ]]; then
  if chroot "$MNT" env PATH=/usr/sbin:/usr/bin:/sbin:/bin \
    /usr/sbin/grub-install --boot-directory=/boot --recheck --no-floppy "$DISK_DEV"; then
    _grub_ok=1
  fi
fi
if [[ "$_grub_ok" -ne 1 ]]; then
  echo "[deploy_bootstrap] ERROR UEFI boot setup failed (shim copy + grub-install) EFI_DEV=${EFI_DEV:-none} EFI_MNT=$EFI_MNT" >&2
  ls -la "$EFI_MNT/EFI" 2>/dev/null >&2 || true
  exit 1
fi

# Fresh install has no swap — stale RESUME breaks update-initramfs (pop-os#3412 pattern)
if [[ -f "$MNT/etc/initramfs-tools/conf.d/resume" ]]; then
  echo 'RESUME=none' >"$MNT/etc/initramfs-tools/conf.d/resume"
fi

# initrd must carry the userspace libs that the systemd-based initramfs needs
# at boot (systemd-udevd, modprobe → libcrypto.so.3). A regeneration that runs
# from the USB Live chroot can silently drop these, leaving a boot that
# dies with "libcrypto.so.3: cannot open shared object file".
#
# Tri-state result — CRITICAL for not bricking the boot:
#   0  initrd is CONFIRMED boot-ready (libcrypto.so.3 + systemd-udevd present)
#   1  initrd is CONFIRMED bad        (lib/binary verified missing)
#   2  CANNOT verify here             (lsinitramfs absent or fails in this chroot)
# We must NOT treat "cannot verify" as "bad": doing so makes the USB Live
# chroot — where lsinitramfs routinely can't run against a glibc rootfs — fall
# through to regeneration, which is the exact path that drops libcrypto and
# bricks the SSD boot. "cannot verify" → trust the build-time-validated prebuilt.
initrd_boot_ready() {
  local img="$1"
  [[ -f "$MNT$img" ]] || return 1
  chroot "$MNT" sh -c 'command -v lsinitramfs >/dev/null 2>&1' || return 2
  local listing
  listing="$(chroot "$MNT" lsinitramfs "$img" 2>/dev/null)" || return 2
  [[ -n "$listing" ]] || return 2
  printf '%s\n' "$listing" | grep -Eq '(^|/)libcrypto\.so\.3$' || return 1
  printf '%s\n' "$listing" | grep -Eq '(^|/)systemd-udevd$' || return 1
  return 0
}

regenerate_initramfs() {
  local img="$1" kver="$2" rel=""
  # Refresh the dynamic linker cache first — copy_exec resolves initrd library
  # deps via the loader, and a stale/empty cache silently drops libcrypto.
  if chroot "$MNT" sh -c 'command -v ldconfig >/dev/null 2>&1'; then
    chroot "$MNT" ldconfig 2>/dev/null || true
  fi
  for rel in /usr/sbin/update-initramfs /sbin/update-initramfs /usr/bin/update-initramfs; do
    if [[ -x "$MNT$rel" ]]; then
      if timeout 180 chroot "$MNT" "$rel" -u -k all || timeout 180 chroot "$MNT" "$rel" -c -k all; then
        return 0
      fi
      echo "[deploy_bootstrap] WARN $rel failed" >&2
      return 1
    fi
  done
  if [[ -n "$kver" && -x "$MNT/usr/sbin/mkinitramfs" ]]; then
    chroot "$MNT" /usr/sbin/mkinitramfs -o "$img" "$kver" && return 0
  fi
  return 1
}

# Prebuilt-first: the initrd shipped in the rootfs tarball is built in a proper
# glibc debootstrap chroot and is known boot-ready (carries libcrypto.so.3 +
# systemd-udevd, MODULES=most for NVMe). Regenerating it here from the USB Live host
# USB Live chroot can silently drop libcrypto and brick the boot
# ("libcrypto.so.3: cannot open shared object file"). So trust the prebuilt and
# only regenerate when it is missing or fails validation.
run_update_initramfs() {
  local kver="" img="" prebuilt="" rc=0
  DEPLOY_INITRD_DECISION=""
  ensure_boot_artifacts_for_grub
  kver="$(ls "$MNT/lib/modules" 2>/dev/null | head -1)"
  img="/boot/initrd.img-${kver}"

  # 1) Prefer the prebuilt initrd from the rootfs tarball. It is generated in a
  #    proper glibc debootstrap chroot at image-build time and validated there,
  #    so it is the safest artifact. We regenerate ONLY when it is CONFIRMED bad
  #    (rc=1). On "cannot verify" (rc=2 — the normal case in the USB Live
  #    chroot) we keep the prebuilt untouched: regenerating here is what drops
  #    libcrypto.so.3 and bricks the boot.
  if [[ -n "$kver" && -f "$MNT$img" ]]; then
    initrd_boot_ready "$img"; rc=$?
    if [[ "$rc" -eq 0 ]]; then
      DEPLOY_INITRD_DECISION="prebuilt-verified"
      echo "[deploy_bootstrap] using verified prebuilt initrd (boot-ready — no regeneration)"
      return 0
    fi
    if [[ "$rc" -eq 2 ]]; then
      DEPLOY_INITRD_DECISION="prebuilt-trust-unverified"
      echo "[deploy_bootstrap] using prebuilt initrd (cannot re-verify in this chroot — trusting build-time validation, no regeneration)" >&2
      return 0
    fi

    # rc == 1 : prebuilt is CONFIRMED missing libcrypto/systemd-udevd.
    prebuilt="${img}.whick-prebuilt"
    cp -a "$MNT$img" "$MNT$prebuilt" 2>/dev/null || prebuilt=""
    echo "[deploy_bootstrap] prebuilt initrd CONFIRMED not boot-ready — regenerating" >&2
    regenerate_initramfs "$img" "$kver" || \
      echo "[deploy_bootstrap] WARN initramfs regeneration failed" >&2
    ensure_boot_artifacts_for_grub

    # Trust regeneration only if it validates as boot-ready; otherwise restore
    # the prebuilt backup (a confirmed-bad prebuilt still beats a confirmed-bad
    # regenerated one, and "cannot verify" means we keep the regenerated image).
    initrd_boot_ready "$img"; rc=$?
    if [[ "$rc" -eq 0 ]]; then
      [[ -n "$prebuilt" ]] && rm -f "$MNT$prebuilt"
      DEPLOY_INITRD_DECISION="regenerated-validated"
      echo "[deploy_bootstrap] initramfs regenerated + validated (libcrypto/systemd-udevd present)"
      return 0
    fi
    if [[ "$rc" -eq 1 && -n "$prebuilt" && -f "$MNT$prebuilt" ]]; then
      cp -a "$MNT$prebuilt" "$MNT$img"
      rm -f "$MNT$prebuilt"
      ensure_boot_artifacts_for_grub
      DEPLOY_INITRD_DECISION="regenerated-restored-prebuilt"
      echo "[deploy_bootstrap] WARN regenerated initrd still not boot-ready — restored prebuilt initrd" >&2
      return 0
    fi
    [[ -n "$prebuilt" ]] && rm -f "$MNT$prebuilt"
    DEPLOY_INITRD_DECISION="regenerated-unverified"
    echo "[deploy_bootstrap] WARN keeping regenerated initrd (could not re-verify)" >&2
    return 0
  fi

  # 2) No prebuilt initrd present at all — must generate one.
  echo "[deploy_bootstrap] no prebuilt initrd present — generating" >&2
  regenerate_initramfs "$img" "$kver" || \
    echo "[deploy_bootstrap] WARN initramfs generation failed" >&2
  ensure_boot_artifacts_for_grub
  DEPLOY_INITRD_DECISION="generated-fresh"

  # 3) Last resort — accept whatever kernel+initrd pair exists on /boot.
  if { [[ -f "$MNT/boot/initrd.img" ]] || [[ -n "$kver" && -f "$MNT$img" ]]; } && \
     { [[ -f "$MNT/boot/vmlinuz" ]] || [[ -n "$kver" && -f "$MNT/boot/vmlinuz-${kver}" ]]; }; then
    DEPLOY_INITRD_DECISION="${DEPLOY_INITRD_DECISION:-generated-unvalidated}"
    echo "[deploy_bootstrap] using kernel+initrd present on /boot (unvalidated)"
    return 0
  fi
  echo "[deploy_bootstrap] boot dir:" >&2
  ls -la "$MNT/boot" 2>/dev/null >&2 || true
  return 1
}

if ! run_update_initramfs; then
  echo "[deploy_bootstrap] ERROR initramfs missing — SSD NVMe boot needs initrd" >&2
  exit 1
fi
log_initrd_telemetry() {
  local kver="" rel="" sha="" sz="" vrc=""
  kver="$(ls "$MNT/lib/modules" 2>/dev/null | head -1)"
  rel="/boot/initrd.img-${kver}"
  [[ -n "$kver" && -f "$MNT$rel" ]] || rel="/boot/initrd.img"
  if [[ -f "$MNT$rel" ]]; then
    sha="$(sha256sum "$MNT$rel" | awk '{print $1}')"
    sz="$(stat -c%s "$MNT$rel" 2>/dev/null || echo 0)"
    initrd_boot_ready "$rel"; vrc=$?
  fi
  echo "[deploy_bootstrap] INITRD_TELEMETRY decision=${DEPLOY_INITRD_DECISION:-unknown} path=${rel} sha256=${sha:-none} size=${sz:-0} verify_rc=${vrc:-na}"
}
log_initrd_telemetry
echo "[deploy_bootstrap] initramfs OK"
ensure_boot_artifacts_for_grub

ROOT_UUID="$(blkid -s UUID -o value "$ROOT_DEV")"
[[ -n "$ROOT_UUID" ]] || {
  echo "[deploy_bootstrap] ERROR whick-root UUID not found on $ROOT_DEV" >&2
  exit 1
}

run_grub_mkconfig || exit 1

verify_grub_cfg_bootable || {
  echo "[deploy_bootstrap] WARN grub.cfg missing initrd — regenerating after initramfs" >&2
  run_grub_mkconfig || exit 1
  verify_grub_cfg_bootable || exit 1
}

if [[ "$PLAN_UEFI" == "1" ]]; then
  EFI_STUB_DIR="$EFI_MNT/EFI/BOOT"
  mkdir -p "$EFI_STUB_DIR"
  cat >"$EFI_STUB_DIR/grub.cfg" <<EOF
search.fs_uuid ${ROOT_UUID} root
set prefix=(\$root)/boot/grub
configfile \$prefix/grub.cfg
EOF
  if [[ -d "$EFI_MNT/EFI/ubuntu" ]]; then
    cat >"$EFI_MNT/EFI/ubuntu/grub.cfg" <<EOF
search.fs_uuid ${ROOT_UUID} root
set prefix=(\$root)/boot/grub
configfile \$prefix/grub.cfg
EOF
  fi
  echo "[deploy_bootstrap] EFI stub grub.cfg written (search.fs_uuid + configfile chain)"
  [[ -f "$EFI_STUB_DIR/BOOTX64.EFI" ]] || [[ -f "$EFI_MNT/EFI/ubuntu/shimx64.efi" ]] || {
    echo "[deploy_bootstrap] ERROR missing EFI boot loader (BOOTX64.EFI or shimx64.efi)" >&2
    exit 1
  }
  grep -q 'configfile \$prefix/grub.cfg' "$EFI_STUB_DIR/grub.cfg" || {
    echo "[deploy_bootstrap] ERROR EFI stub missing configfile chain" >&2
    exit 1
  }
  grep -q "search.fs_uuid ${ROOT_UUID}" "$EFI_STUB_DIR/grub.cfg" || {
    echo "[deploy_bootstrap] ERROR EFI stub missing search.fs_uuid ${ROOT_UUID}" >&2
    exit 1
  }
  grep -qE 'vmlinuz|menuentry' "$MNT/boot/grub/grub.cfg" || {
    echo "[deploy_bootstrap] ERROR /boot/grub/grub.cfg has no kernel menuentry" >&2
    exit 1
  }
  ls "$MNT/boot/initrd"* >/dev/null 2>&1 || {
    echo "[deploy_bootstrap] ERROR no initrd on /boot" >&2
    exit 1
  }
  echo "[deploy_bootstrap] UEFI boot chain verified (EFI loader + stub → /boot/grub/grub.cfg + initrd)"
fi

echo "[deploy_bootstrap] grub.cfg generated"
deploy_progress 90 "Bootloader done — finishing…"

# ── Rescue partition deploy ─────────────────────────────────────────────
# Default OFF (WHICK_RESCUE_ENABLE=0) — pre-v0.9.3 install path; no create/preserve/deploy.
# When ENABLE=1: non-fatal if mount busy (rootfs+GRUB already done).
_RESCUE_ENABLE="${WHICK_RESCUE_ENABLE:-0}"
case "${_RESCUE_ENABLE}" in
  1|true|yes|TRUE|YES) _RESCUE_ON=1 ;;
  *) _RESCUE_ON=0 ;;
esac

if [[ "$_RESCUE_ON" -ne 1 ]]; then
  echo "[deploy_bootstrap] rescue disabled (WHICK_RESCUE_ENABLE=${_RESCUE_ENABLE}) — skip rescue deploy"
else
RESCUE_DEV="$(blkid -L whick-rescue -o device 2>/dev/null || true)"
RESCUE_MNT="$MNT/../whick-rescue-mnt"
RESCUE_MOUNTED=0

if [[ -n "$RESCUE_DEV" && -b "$RESCUE_DEV" ]]; then
  echo "[deploy_bootstrap] rescue partition found: $RESCUE_DEV"
  if whick_mount_optional "$RESCUE_DEV" "$RESCUE_MNT"; then
    RESCUE_MOUNTED=1
  else
    echo "[deploy_bootstrap] WARN rescue mount Resource busy/failed — skip rescue image deploy (main OS OK)" >&2
  fi

  if [[ "$RESCUE_MOUNTED" -eq 1 ]]; then
    RESCUE_IMAGE="${WHICK_RESCUE_IMAGE:-}"
    if [[ -z "$RESCUE_IMAGE" ]]; then
      # Resolve product root: deploy lives at uab/live/bin, product is uab/../.. (3_product)
      _deploy_product="$(cd "$ROOT/../.." && pwd)"
      for candidate in \
        "$_deploy_product/dist/rescue/whick-rescue-image" \
        "/opt/whick-boot-connect/rescue/whick-rescue-image" \
        "${WHICK_USB_ROOT:-}/whick-boot-connect/rescue/whick-rescue-image"; do
        if [[ -d "$candidate" ]]; then
          RESCUE_IMAGE="$candidate"
          break
        fi
      done
    fi

    if [[ -n "$RESCUE_IMAGE" && -d "$RESCUE_IMAGE" ]]; then
      echo "[deploy_bootstrap] deploying rescue image from $RESCUE_IMAGE"
      cp -a "$RESCUE_IMAGE/." "$RESCUE_MNT/"
      echo "[deploy_bootstrap] rescue image deployed ($(find "$RESCUE_MNT" -type f | wc -l) files)"
    else
      echo "[deploy_bootstrap] rescue image not found locally — trying CC fetch"
      _rescue_tgz="/tmp/whick-rescue-image.tar.gz"
      _rescue_session=""
      for p in "${WHICK_BOOTSTRAP_SESSION:-}" /tmp/whick-bootstrap-session.json; do
        if [[ -n "$p" && -f "$p" ]]; then
          _rescue_session="$p"
          export WHICK_BOOTSTRAP_SESSION="$p"
          break
        fi
      done
      if [[ "${WHICK_DEPLOY_NO_CC_FETCH:-0}" != "1" && -n "$_rescue_session" ]]; then
        _rescue_script_dir="$(cd "$(dirname "$0")" && pwd)"
        _rescue_cc="${WHICK_CC_API_URL:-https://admin.whick.org/api/v1}"
        if "$_rescue_script_dir/whick-fetch-artifact.sh" \
          --name "whick-rescue-image.tar.gz" \
          --dest "$_rescue_tgz" \
          --url "$_rescue_cc/install/bootstrap/artifact/whick-rescue-image.tar.gz" \
          && tar tzf "$_rescue_tgz" >/dev/null 2>&1; then
          tar xzf "$_rescue_tgz" -C "$RESCUE_MNT" --strip-components=1
          rm -f "$_rescue_tgz"
          echo "[deploy_bootstrap] rescue image deployed from CC ($(find "$RESCUE_MNT" -type f | wc -l) files)"
        else
          echo "[deploy_bootstrap] WARN CC rescue image fetch failed — rescue partition left empty" >&2
        fi
      else
        echo "[deploy_bootstrap] WARN rescue partition exists but no image found (no bootstrap session for CC fetch)" >&2
      fi
    fi
    umount -lf "$RESCUE_MNT" 2>/dev/null || true
  fi

  # GRUB rescue menu entry needs UUID only (no mount)
  _grub_cfg="$MNT/boot/grub/grub.cfg"
  if [[ -f "$_grub_cfg" ]]; then
    RESCUE_UUID="$(blkid -s UUID -o value "$RESCUE_DEV" 2>/dev/null || true)"
    ROOT_UUID="$(blkid -s UUID -o value "$ROOT_DEV" 2>/dev/null || true)"
    if [[ -n "$RESCUE_UUID" ]] && ! grep -q "Whick Rescue" "$_grub_cfg" 2>/dev/null; then
      cat >>"$_grub_cfg" <<GRUB

# Whick Rescue — 원격 시스템 재설치용
menuentry "Whick Rescue (system reinstall)" --id whick-rescue {
    search --no-floppy --fs-uuid --set=root $RESCUE_UUID
    linux /boot/vmlinuz-lts root=UUID=$RESCUE_UUID ro modules=loop,squashfs,sd-mod,usb-storage quiet console=tty0
    initrd /boot/initramfs-lts
}
menuentry "Ubuntu (main OS)" --id ubuntu-main {
    search --no-floppy --fs-uuid --set=root $ROOT_UUID
    linux /boot/vmlinuz root=UUID=$ROOT_UUID ro
    initrd /boot/initrd.img
}
GRUB
      echo "[deploy_bootstrap] GRUB rescue entry added (rescue UUID=$RESCUE_UUID)"
    fi
  fi
else
  echo "[deploy_bootstrap] no whick-rescue partition — skip rescue deploy"
fi
fi
# ── end rescue deploy ──────────────────────────────────────────────────

sync
trap - EXIT
deploy_cleanup

deploy_progress 94 "Ubuntu SSD deploy complete"
echo "[deploy_bootstrap] OK — USB 제거 후 SSD Ubuntu 부팅"
