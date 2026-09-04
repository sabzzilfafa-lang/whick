#!/usr/bin/env bash
# Whick OS Live — Ubuntu 26.04 live-server remaster (nocloud + /whick-os overlay)
# No unsquash required — bootable USB for field install
# SSOT: docs/WHICK-OS.md
set -euo pipefail

OS_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PRODUCT="$(cd "$OS_ROOT/.." && pwd)"
UAB="$PRODUCT/uab"
RECIPE="$OS_ROOT/recipe"
OUT="${WHICK_OS_LIVE_OUT:-$PRODUCT/dist/os}"
PROFILE="${WHICK_OS_NET_PROFILE:-wired}"
STAGE="${WHICK_OS_LIVE_STAGE:-/tmp/whick-os-live-build}"
BASE_ISO="${WHICK_OS_UBUNTU_LIVE_ISO:-}"
CACHE_ISO="/mnt/music/whick-cc/build-staging/whick-os/cache/ubuntu-26.04-live-server-amd64.iso"

usage() {
  cat <<EOF
Usage: WHICK_OS_NET_PROFILE=wired|wireless $(basename "$0") [--check|--payload|--iso]
EOF
}

check_only() {
  echo "==> check profile=$PROFILE"
  [[ -f "$RECIPE/live-extra.yaml" ]] || exit 1
  [[ -d "$UAB/live/phases" ]] || exit 1
  case "$PROFILE" in wired|wireless) ;; *) exit 1 ;; esac
  echo OK
}

pin_boot_connect_env() {
  local file="$1" key="$2" value="$3"
  python3 - "$file" "$key" "$value" <<'PY'
import pathlib, shlex, sys
path, key, value = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
lines = [
    line for line in path.read_text(encoding="utf-8").splitlines()
    if not line.startswith(f"export {key}=")
]
lines.append(f"export {key}={shlex.quote(value)}")
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
}

# 현장 USB(미니PC)는 절대 127.0.0.1/localhost CC 를 박으면 안 된다.
# (lab 전용은 WHICK_ALLOW_LOCALHOST_CC=1 명시 시에만 허용)
assert_device_safe_cc_url() {
  local url="${1:-}"
  if [[ -z "$url" ]]; then
    return 0
  fi
  if [[ "$url" == *127.0.0.1* || "$url" == *localhost* ]]; then
    if [[ "${WHICK_ALLOW_LOCALHOST_CC:-0}" == "1" ]]; then
      echo "WARN: baking localhost CC URL (WHICK_ALLOW_LOCALHOST_CC=1): $url" >&2
      return 0
    fi
    echo "ERROR: refusing to bake localhost CC URL into Live ISO: $url" >&2
    echo "  현장 미니PC는 서버의 127.0.0.1:18095 에 닿지 못한다." >&2
    echo "  test → https://test-admin.whick.org/api/v1" >&2
    echo "  stable → https://admin.whick.org/api/v1" >&2
    echo "  lab 예외만 WHICK_ALLOW_LOCALHOST_CC=1" >&2
    exit 1
  fi
}

build_payload() {
  echo "==> payload profile=$PROFILE"
  rm -rf "$STAGE/payload"
  mkdir -p "$STAGE/payload/opt/whick/uab" "$STAGE/payload/etc/whick" "$OUT"
  [[ -d "$UAB/live" ]] && cp -a "$UAB/live/." "$STAGE/payload/opt/whick/uab/"
  if [[ -d "$UAB/boot-connect" ]]; then
    mkdir -p "$STAGE/payload/opt/whick/boot-connect"
    cp -a "$UAB/boot-connect/." "$STAGE/payload/opt/whick/boot-connect/"
    # 채널별 CC 주소 고정 — release-connect-usb.sh 가 channel(test|stable)로 정해 넘긴다.
    # 여기서 굳히지 않으면 test ISO 도 기본값 admin.whick.org 로 붙어 실차를 두드린다.
    if [[ -n "${WHICK_CC_API_URL:-}" ]]; then
      assert_device_safe_cc_url "$WHICK_CC_API_URL"
      assert_device_safe_cc_url "${WHICK_CANONICAL_CC_API_URL:-$WHICK_CC_API_URL}"
      pin_boot_connect_env "$STAGE/payload/opt/whick/boot-connect/whick-env.sh" \
        WHICK_CC_API_URL "$WHICK_CC_API_URL"
      pin_boot_connect_env "$STAGE/payload/opt/whick/boot-connect/whick-env.sh" \
        WHICK_CANONICAL_CC_API_URL "${WHICK_CANONICAL_CC_API_URL:-$WHICK_CC_API_URL}"
      # test-admin 등 공개 HTTPS 는 named tunnel 이 아니어도 허용
      pin_boot_connect_env "$STAGE/payload/opt/whick/boot-connect/whick-env.sh" \
        WHICK_ALLOW_NON_TUNNEL_CC "${WHICK_ALLOW_NON_TUNNEL_CC:-1}"
    fi
  fi
  echo "$PROFILE" >"$STAGE/payload/etc/whick/net-profile"
  # customer-setup.py 는 /opt/whick/boot-connect/net-profile 도 읽는다 (etc 만 있으면 full 로 떨어짐)
  if [[ -d "$STAGE/payload/opt/whick/boot-connect" ]]; then
    echo "$PROFILE" >"$STAGE/payload/opt/whick/boot-connect/net-profile"
  fi
  cat >"$STAGE/payload/etc/whick/os-live-release" <<EOF
NAME=Whick OS Live
VERSION=1
PROFILE=$PROFILE
ID=whick-os-live
UBUNTU=26.04
EOF
  mkdir -p "$STAGE/payload/usr/local/sbin" "$STAGE/payload/etc/systemd/system" \
    "$STAGE/payload/etc/systemd/system/multi-user.target.wants"
  # Live USB — sshd 불필요(설치는 HTTPS). 기본 이미지 FAILED 스팸 차단 (보통 3~4줄)
  for _ssh_u in ssh.service ssh.socket sshd.service sshd.socket; do
    ln -sfn /dev/null "$STAGE/payload/etc/systemd/system/$_ssh_u"
  done
  # 테스트·현장: 오류 시 콘솔·파일에 확실히 남김 (기본 DEBUG)
  cat >"$STAGE/payload/etc/whick/live-debug.env" <<'ENV'
WHICK_OS_LIVE=1
WHICK_USB_LIVE_INSTALL=1
WHICK_OS_LIVE_DEBUG=1
PYTHONUNBUFFERED=1
WHICK_LOG_LEVEL=debug
# 실디스크 설치 (파파님 동의 후 진행) — dry-run 금지
WHICK_PROD_INSTALL=1
WHICK_LINUX_INSTALL_DRY_RUN=0
WHICK_ALLOW_LIVE_DISK_APPLY=1
WHICK_DISK_APPLY=1
ENV
  # 채널별 CC 주소·시크릿 — whick-os-live-start.sh 는 이 파일만 `set -a` 로 source 한다.
  # 이후 customer-setup → whick-boot-connect.sh 가 whick-env.sh 를 source 하므로
  # live-debug 와 whick-env 의 CC URL 은 반드시 같아야 한다 (한쪽만 고치면 덮어씀).
  # bootstrap secret 미주입 시 POST /install/sessions → 401 INSTALL_SECRET_REQUIRED.
  if [[ -n "${WHICK_CC_API_URL:-}" ]]; then
    assert_device_safe_cc_url "$WHICK_CC_API_URL"
    assert_device_safe_cc_url "${WHICK_CANONICAL_CC_API_URL:-$WHICK_CC_API_URL}"
    {
      printf 'WHICK_CC_API_URL=%s\n' "$WHICK_CC_API_URL"
      printf 'WHICK_CANONICAL_CC_API_URL=%s\n' "${WHICK_CANONICAL_CC_API_URL:-$WHICK_CC_API_URL}"
      printf 'WHICK_ALLOW_NON_TUNNEL_CC=%s\n' "${WHICK_ALLOW_NON_TUNNEL_CC:-1}"
    } >>"$STAGE/payload/etc/whick/live-debug.env"
  fi
  if [[ -z "${WHICK_INSTALL_BOOTSTRAP_SECRET:-}" ]]; then
    echo "ERROR: WHICK_INSTALL_BOOTSTRAP_SECRET required (Live ISO → POST /install/sessions)" >&2
    exit 1
  fi
  printf 'WHICK_INSTALL_BOOTSTRAP_SECRET=%s\n' "$WHICK_INSTALL_BOOTSTRAP_SECRET" \
    >>"$STAGE/payload/etc/whick/live-debug.env"
  if [[ -f "$STAGE/payload/opt/whick/boot-connect/whick-env.sh" ]]; then
    pin_boot_connect_env "$STAGE/payload/opt/whick/boot-connect/whick-env.sh" \
      WHICK_INSTALL_BOOTSTRAP_SECRET "$WHICK_INSTALL_BOOTSTRAP_SECRET"
  fi
  cat >"$STAGE/payload/usr/local/sbin/whick-os-live-start.sh" <<'BOOT'
#!/bin/bash
# Whick OS Live entry — 테스트용 상세 로그 (콘솔 + 파일)
set -eEuo pipefail
export WHICK_OS_LIVE=1 WHICK_USB_LIVE_INSTALL=1
export WHICK_OS_LIVE_DEBUG="${WHICK_OS_LIVE_DEBUG:-1}"
export PYTHONUNBUFFERED=1
export WHICK_LOG_LEVEL="${WHICK_LOG_LEVEL:-debug}"
# shellcheck disable=SC1091
[[ -f /etc/whick/live-debug.env ]] && set -a && . /etc/whick/live-debug.env && set +a
export WHICK_USB_PROFILE="$(cat /etc/whick/net-profile 2>/dev/null || echo wired)"
export WHICK_NET_PROFILE="${WHICK_NET_PROFILE:-$WHICK_USB_PROFILE}"

LOG_DIR=/var/log/whick
LOG="$LOG_DIR/whick-os-live.log"
mkdir -p "$LOG_DIR" /run/whick
# process substitution(> >(...))은 autoinstall early 환경에서 실패함 → 단순 리다이렉트
touch "$LOG"
exec >>"$LOG" 2>&1
# 콘솔에도 남기려면 호출측에서 tee. 여기서는 파일 SSOT.

ts() { date '+%Y-%m-%d %H:%M:%S'; }
banner() { echo ""; echo "======== $* ========"; echo ""; }
die() {
  banner "WHICK OS LIVE ERROR"
  echo "[$(ts)] FATAL: $*"
  echo "[$(ts)] full log: $LOG"
  # 콘솔 직접 시도 (early 환경 대비)
  {
    banner "WHICK OS LIVE ERROR"
    echo "[$(ts)] FATAL: $*"
    echo "[$(ts)] full log: $LOG"
  } > /dev/console 2>/dev/null || true
  echo "[$(ts)] 60초 대기..."
  sleep 60
  exit 1
}

trap 'rc=$?; [[ $rc -eq 0 ]] || die "command failed rc=$rc line=$LINENO"' ERR

# iODD/USB: cloud-init가 casper /cdrom 마운트보다 먼저 돌 수 있음 → 대기·탐색
find_whick_root() {
  shopt -s nullglob
  local candidate
  for candidate in \
      /mnt/whick-media/whick-os/opt/whick \
      /mnt/whick-media/casper/whick-os/opt/whick \
      /cdrom/whick-os/opt/whick \
      /cdrom/casper/whick-os/opt/whick \
      /run/live/medium/whick-os/opt/whick \
      /run/live/medium/casper/whick-os/opt/whick \
      /media/*/whick-os/opt/whick \
      /run/media/*/*/whick-os/opt/whick
  do
    [[ -d "$candidate" ]] && { echo "$candidate"; return 0; }
  done
  return 1
}

ensure_cdrom_mount() {
  [[ -d /cdrom/whick-os/opt/whick || -d /mnt/whick-media/whick-os/opt/whick ]] && return 0
  mkdir -p /cdrom /mnt/whick-media
  local label dev
  for label in WHICK_OS_wired WHICK_OS_WIRED WHICK_OS_wireless; do
    if [[ -e "/dev/disk/by-label/$label" ]]; then
      mountpoint -q /mnt/whick-media 2>/dev/null || mount -o ro "/dev/disk/by-label/$label" /mnt/whick-media 2>/dev/null || true
    fi
  done
  for dev in /dev/sr0 /dev/sr1 /dev/cdrom; do
    [[ -b "$dev" ]] || continue
    mountpoint -q /mnt/whick-media 2>/dev/null || mount -o ro "$dev" /mnt/whick-media 2>/dev/null || true
    mountpoint -q /cdrom 2>/dev/null || mount -o ro "$dev" /cdrom 2>/dev/null || true
  done
  findmnt -n -o TARGET,SOURCE -t iso9660 2>/dev/null || true
  return 1
}

WHICK_MEDIA_ROOT=""
wait_for_whick_media() {
  local i root
  echo "[$(ts)] waiting for Whick media (/cdrom/whick-os) ..."
  for i in $(seq 1 90); do
    ensure_cdrom_mount || true
    if root="$(find_whick_root)"; then
      echo "[$(ts)] found payload at $root (try=$i)"
      WHICK_MEDIA_ROOT="$root"
      return 0
    fi
    if (( i % 10 == 0 )); then
      echo "[$(ts)] still waiting try=$i — ls /cdrom:"
      ls -la /cdrom 2>/dev/null | head -20 || true
      lsblk -o NAME,TYPE,SIZE,MOUNTPOINT 2>/dev/null | head -20 || true
    fi
    sleep 1
  done
  return 1
}

banner "Whick OS Live start $(ts)"
echo "[$(ts)] profile=$WHICK_USB_PROFILE debug=$WHICK_OS_LIVE_DEBUG"
echo "[$(ts)] uname=$(uname -a)"
echo "[$(ts)] cmdline=$(cat /proc/cmdline 2>/dev/null || true)"
ip -br a 2>/dev/null || true
ip route 2>/dev/null || true

ROOT_WHICK=/opt/whick
if [[ -d /opt/whick/boot-connect ]]; then
  echo "[$(ts)] using /opt/whick (already installed)"
  ROOT_WHICK=/opt/whick
elif wait_for_whick_media; then
  ROOT_WHICK="$WHICK_MEDIA_ROOT"
  echo "[$(ts)] using media payload $ROOT_WHICK"
else
  die "Whick payload missing after wait (/cdrom/whick-os) — iODD/USB mount failed?"
fi
ls -la "$ROOT_WHICK" | head -20

# copy to /opt if only on media (writable runtime)
if [[ "$ROOT_WHICK" != /opt/whick ]]; then
  media_base="$(dirname "$(dirname "$ROOT_WHICK")")"  # .../whick-os
  echo "[$(ts)] copying payload to /opt/whick from $media_base ..."
  mkdir -p /opt /etc/whick /usr/local/sbin
  cp -a "$ROOT_WHICK" /opt/ || die "cp opt/whick failed"
  if [[ -d "$media_base/etc/whick" ]]; then
    cp -a "$media_base/etc/whick/." /etc/whick/ 2>/dev/null || true
  fi
  if [[ -d "$media_base/usr/local/sbin" ]]; then
    cp -a "$media_base/usr/local/sbin/." /usr/local/sbin/ 2>/dev/null || true
  fi
  ROOT_WHICK=/opt/whick
fi

SETUP="$ROOT_WHICK/boot-connect/whick-customer-setup.py"
BOOTSH="$ROOT_WHICK/uab/boot.sh"
echo "[$(ts)] SETUP=$SETUP exists=$([[ -f $SETUP ]] && echo yes || echo no)"
echo "[$(ts)] BOOTSH=$BOOTSH exists=$([[ -x $BOOTSH ]] && echo yes || echo no)"

# 무선 Live squashfs 에 wpasupplicant 없음 → ISO pool 에서 설치 (customer-setup 도 동일 보정)
if [[ "${WHICK_USB_PROFILE:-}" == "wireless" ]] && ! command -v wpa_supplicant >/dev/null 2>&1; then
  echo "[$(ts)] installing wpasupplicant from live ISO pool..."
  for media in /cdrom /mnt/whick-media /run/live/medium; do
    pcs=( "$media"/pool/main/p/pcsc-lite/libpcsclite1_*.deb )
    wpa=( "$media"/pool/main/w/wpa/wpasupplicant_*.deb )
    if [[ -f "${pcs[0]:-}" && -f "${wpa[0]:-}" ]]; then
      dpkg -i "${pcs[0]}" "${wpa[0]}" || dpkg --configure -a || true
      break
    fi
  done
  command -v wpa_supplicant >/dev/null 2>&1 && echo "[$(ts)] wpa_supplicant OK" || echo "[$(ts)] WARN: wpa_supplicant still missing"
fi

if [[ -f "$SETUP" ]]; then
  cd "$(dirname "$SETUP")"
  echo "[$(ts)] launching python3 whick-customer-setup.py ..."
  /usr/bin/python3 -u ./whick-customer-setup.py
  rc=$?
  echo "[$(ts)] customer-setup exit=$rc"
  [[ $rc -eq 0 ]] || die "whick-customer-setup.py exit $rc"
  exit 0
fi
if [[ -x "$BOOTSH" ]]; then
  echo "[$(ts)] launching uab/boot.sh ..."
  "$BOOTSH"
  rc=$?
  [[ $rc -eq 0 ]] || die "uab/boot.sh exit $rc"
  exit 0
fi
die "no setup entry (customer-setup.py / boot.sh)"
BOOT
  chmod 755 "$STAGE/payload/usr/local/sbin/whick-os-live-start.sh"

  # systemd oneshot — 부팅 후 자동 기동 + 실패 시 journal에 남김
  cat >"$STAGE/payload/etc/systemd/system/whick-os-live-setup.service" <<'UNIT'
[Unit]
Description=Whick OS Live setup (verbose test logging)
# casper가 /cdrom 마운트한 뒤·cloud-init과 경합 가능 → start.sh 내부에서 wait
After=local-fs.target media-cdrom.mount casper.service
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=-/etc/whick/live-debug.env
Environment=WHICK_OS_LIVE_DEBUG=1
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/local/sbin/whick-os-live-start.sh
StandardOutput=journal+console
StandardError=journal+console
Restart=on-failure
RestartSec=15
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
UNIT
  ln -sfn /etc/systemd/system/whick-os-live-setup.service \
    "$STAGE/payload/etc/systemd/system/multi-user.target.wants/whick-os-live-setup.service"

  PAYLOAD="$OUT/whick-os-live-payload-${PROFILE}.tar.zst"
  rm -f "$PAYLOAD"
  tar -C "$STAGE/payload" -cf - . | zstd -T0 -19 -o "$PAYLOAD"
  ls -lh "$PAYLOAD"; sha256sum "$PAYLOAD"
  echo "OK payload"
}

resolve_base_iso() {
  [[ -n "$BASE_ISO" && -f "$BASE_ISO" ]] && { echo "$BASE_ISO"; return; }
  [[ -f "$CACHE_ISO" ]] && { echo "$CACHE_ISO"; return; }
  return 1
}

build_iso() {
  build_payload
  local PAYLOAD="$OUT/whick-os-live-payload-${PROFILE}.tar.zst"
  local ISO_OUT="$OUT/whick-os-live-${PROFILE}.iso"
  local base
  base="$(resolve_base_iso)" || { echo "ERROR: missing $CACHE_ISO" >&2; exit 1; }
  command -v xorriso >/dev/null || { echo "ERROR: xorriso required" >&2; exit 1; }

  local OVER="$STAGE/overlay"
  rm -rf "$OVER"
  mkdir -p "$OVER/whick-os" "$OVER/nocloud" "$OVER/boot/grub"

  echo "==> Prepare overlay (whick-os + nocloud + grub)"
  zstd -d -c "$PAYLOAD" | tar -C "$OVER/whick-os" -xf -

  cat >"$OVER/nocloud/meta-data" <<'MD'
instance-id: whick-os-live
local-hostname: whick-os-live
MD
  # network-config는 유지(별도 파일). user-data 최상단 network/datasource_list 금지
  # → subiquity가 autoinstall로 오인해 schema failure 냄
  cat >"$OVER/nocloud/network-config" <<'NC'
version: 2
ethernets:
  all-en:
    match: {name: "en*"}
    dhcp4: true
    dhcp4-overrides: {timeout: 15}
    optional: true
  all-eth:
    match: {name: "eth*"}
    dhcp4: true
    dhcp4-overrides: {timeout: 15}
    optional: true
NC
  # autoinstall early-commands: /cdrom 경로·스키마 문제를 우회하고 Whick만 기동
  # early에서 sleep infinity → 언어설치/디스크 설치로 진행 안 함
  cat >"$OVER/nocloud/user-data" <<'UD'
#cloud-config
autoinstall:
  version: 1
  early-commands:
    - |
      exec /bin/bash <<'EOS'
      set -x
      mkdir -p /var/log/whick /mnt/whick-media /opt /etc/whick /usr/local/sbin /cdrom
      EARLY=/var/log/whick/whick-os-live-early.log
      touch "$EARLY"
      logc() { echo "$*" | tee -a "$EARLY" /dev/console; }
      logc "=== whick autoinstall early $(date -Is) ==="
      systemctl mask --runtime --now subiquity.service subiquity-server.service 2>/dev/null || true
      systemctl stop subiquity.service subiquity-server.service 2>/dev/null || true
      # Live 설치는 SSH 불필요 — FAILED ssh*.service 콘솔 스팸 방지
      systemctl mask --runtime --now ssh.service ssh.socket sshd.service sshd.socket 2>/dev/null || true
      systemctl stop ssh.service ssh.socket sshd.service sshd.socket 2>/dev/null || true
      found=""
      try_mount() {
        local src="$1" dst="$2"
        mkdir -p "$dst"
        mountpoint -q "$dst" 2>/dev/null && return 0
        mount -o ro "$src" "$dst" 2>/dev/null
      }
      for i in $(seq 1 120); do
        for label in WHICK_OS_wired WHICK_OS_WIRED WHICK_OS_wireless; do
          [[ -e "/dev/disk/by-label/$label" ]] || continue
          try_mount "/dev/disk/by-label/$label" /mnt/whick-media || true
        done
        for dev in /dev/sr0 /dev/sr1 /dev/cdrom; do
          [[ -b "$dev" ]] || continue
          try_mount "$dev" /mnt/whick-media || true
          try_mount "$dev" /cdrom || true
        done
        for base in /mnt/whick-media /cdrom /run/live/medium /media/cdrom /media/cdrom0; do
          if [[ -d "$base/whick-os/opt/whick" ]]; then found="$base/whick-os"; break 2; fi
          if [[ -d "$base/casper/whick-os/opt/whick" ]]; then found="$base/casper/whick-os"; break 2; fi
        done
        if [ $((i % 15)) -eq 0 ]; then
          logc "still looking try=$i"
          lsblk -o NAME,TYPE,SIZE,LABEL,MOUNTPOINT 2>&1 | tee -a "$EARLY" /dev/console || true
        fi
        sleep 1
      done
      if [[ -z "$found" ]]; then
        logc "ERROR: whick-os media not found after 120s"
        sleep infinity
      fi
      logc "OK media $found"
      cp -a "$found/opt/whick" /opt/ || logc "WARN cp opt"
      cp -a "$found/etc/whick/." /etc/whick/ 2>/dev/null || true
      cp -a "$found/usr/local/sbin/." /usr/local/sbin/ 2>/dev/null || true
      cp -a "$found/etc/systemd/system/whick-os-live-setup.service" /etc/systemd/system/ 2>/dev/null || true
      mkdir -p /etc/systemd/system/multi-user.target.wants
      ln -sfn /etc/systemd/system/whick-os-live-setup.service \
        /etc/systemd/system/multi-user.target.wants/whick-os-live-setup.service 2>/dev/null || true
      chmod +x /usr/local/sbin/whick-os-live-start.sh || true
      ls -la /opt/whick/boot-connect/whick-customer-setup.py /usr/local/sbin/whick-os-live-start.sh 2>&1 | tee -a "$EARLY" /dev/console || true
      systemctl daemon-reload || true
      if systemctl start whick-os-live-setup.service 2>>"$EARLY"; then
        logc "OK systemctl start whick-os-live-setup"
      else
        logc "systemctl start failed — running start.sh in background"
        /bin/bash /usr/local/sbin/whick-os-live-start.sh >>/var/log/whick/whick-os-live.log 2>&1 &
        SPID=$!
        sleep 3
        if kill -0 "$SPID" 2>/dev/null; then
          logc "OK start.sh pid=$SPID"
        else
          logc "FATAL: start.sh exited early — tail log:"
          tail -80 /var/log/whick/whick-os-live.log 2>&1 | tee -a "$EARLY" /dev/console || true
        fi
      fi
      logc "blocking installer (sleep infinity) — Whick should be running"
      sleep infinity
      EOS
  interactive-sections: []
UD

  # GRUB: autoinstall 인식 + subiquity mask
  # noprompt·noeject: casper 재부팅 시 "remove installation medium, press ENTER" 무한대기 방지 (무인 설치 필수)
  WHICK_CMDLINE_EXTRA='systemd.mask=subiquity.service systemd.mask=subiquity-server.service systemd.mask=ssh.service systemd.mask=ssh.socket systemd.mask=sshd.service systemd.mask=sshd.socket noprompt noeject'
  cat >"$OVER/boot/grub/grub.cfg" <<GRUB
set timeout=10
set default=0
loadfont unicode
set menu_color_normal=white/black
set menu_color_highlight=black/light-gray

menuentry "Whick OS Live (install USB)" {
    set gfxpayload=keep
    linux  /casper/vmlinuz console=tty0 ${WHICK_CMDLINE_EXTRA} --- autoinstall ds=nocloud\\;s=/cdrom/nocloud/ cloud-config-url=/cdrom/nocloud/user-data
    initrd /casper/initrd
}
menuentry "Whick OS Live (install USB · DEBUG)" {
    set gfxpayload=keep
    linux  /casper/vmlinuz console=tty0 console=ttyS0,115200n8 systemd.log_level=info ${WHICK_CMDLINE_EXTRA} --- autoinstall ds=nocloud\\;s=/cdrom/nocloud/ cloud-config-url=/cdrom/nocloud/user-data
    initrd /casper/initrd
}
menuentry "Ubuntu Server live (stock · 언어설치)" {
    set gfxpayload=keep
    linux  /casper/vmlinuz console=tty0 ---
    initrd /casper/initrd
}
grub_platform
if [ "\$grub_platform" = "efi" ]; then
menuentry 'UEFI Firmware Settings' { fwsetup }
fi
GRUB

  cat >"$OVER/WHICK-OS-LIVE.txt" <<EOF
Whick OS Live USB ($PROFILE)
Boot: 표준설치 (default) · DEBUG는 메뉴 2번
v0.1.9: media OK 후 start 실패 수정 — process substitution 제거, start.sh 백그라운드+콘솔 로그
Logs: /var/log/whick/whick-os-live-early.log · whick-os-live.log
EOF

  echo "==> Remaster via extract + as_mkisofs (Ubuntu 26.04 hybrid 동일 옵션 · Gap1 포함)"
  # replay-only remaster는 Gap1 누락·CHS geometry 삽입 → Rufus DD 쓰기오류 유발 가능
  # SSOT: xorriso -indev BASE -report_system_area as_mkisofs
  command -v sgdisk >/dev/null || { echo "ERROR: sgdisk (gdisk) required" >&2; exit 1; }

  local TREE="$STAGE/iso-tree"
  local BOOTBITS="$STAGE/bootbits"
  rm -rf "$TREE" "$BOOTBITS"
  mkdir -p "$TREE" "$BOOTBITS"

  echo "==> Extract base ISO tree"
  xorriso -osirrox on -indev "$base" -extract / "$TREE"
  # Ubuntu live 트리는 casper 등이 0555로 풀림 — overlay 주입 전 쓰기 권한 필요
  chmod -R u+w "$TREE"

  echo "==> Inject Whick overlay into tree"
  rm -rf "$TREE/whick-os" "$TREE/nocloud" "$TREE/casper/whick-os"
  mkdir -p "$TREE/whick-os" "$TREE/nocloud" "$TREE/boot/grub" "$TREE/casper"
  cp -a "$OVER/whick-os/." "$TREE/whick-os/"
  # iODD/casper에서 /cdrom/whick-os 누락 대비 — casper 아래에도 복제
  cp -a "$OVER/whick-os/." "$TREE/casper/whick-os/"
  cp -a "$OVER/nocloud/." "$TREE/nocloud/"
  cp -f "$OVER/boot/grub/grub.cfg" "$TREE/boot/grub/grub.cfg"
  cp -f "$OVER/WHICK-OS-LIVE.txt" "$TREE/WHICK-OS-LIVE.txt"

  echo "==> Extract EFI appended partition + GRUB2 MBR from base"
  # part2 = EFI System (EF00) on Ubuntu live-server hybrid
  local efi_start efi_end efi_count
  efi_start="$(sgdisk -i 2 "$base" | awk -F: '/First sector/{match($2,/[0-9]+/); print substr($2,RSTART,RLENGTH); exit}')"
  efi_end="$(sgdisk -i 2 "$base" | awk -F: '/Last sector/{match($2,/[0-9]+/); print substr($2,RSTART,RLENGTH); exit}')"
  [[ -n "$efi_start" && -n "$efi_end" ]] || { echo "ERROR: cannot read EFI partition from base" >&2; exit 1; }
  efi_count=$((efi_end - efi_start + 1))
  [[ "$efi_count" -gt 100 && "$efi_count" -lt 65535 ]] || {
    echo "ERROR: bad EFI sector count: $efi_count (start=$efi_start end=$efi_end)" >&2
    exit 1
  }
  dd if="$base" of="$BOOTBITS/efi.img" bs=512 skip="$efi_start" count="$efi_count" status=none
  [[ "$(stat -c%s "$BOOTBITS/efi.img")" -eq $((efi_count * 512)) ]] || {
    echo "ERROR: efi.img size mismatch" >&2
    exit 1
  }
  ls -lh "$BOOTBITS/efi.img"
  echo "EFI sectors $efi_start-$efi_end count=$efi_count"

  echo "==> as_mkisofs rebuild (protective MBR + GPT + EFI append)"
  rm -f "$ISO_OUT"
  # MBR: base 0s-15s with zeroed partition tables (Ubuntu stock recipe)
  xorriso -as mkisofs \
    -r -J -joliet-long \
    -V "WHICK_OS_${PROFILE}" \
    -o "$ISO_OUT" \
    --grub2-mbr "--interval:local_fs:0s-15s:zero_mbrpt,zero_gpt:${base}" \
    --protective-msdos-label \
    -partition_cyl_align off \
    -partition_offset 16 \
    --mbr-force-bootable \
    -append_partition 2 28732ac11ff8d211ba4b00a0c93ec93b "$BOOTBITS/efi.img" \
    -appended_part_as_gpt \
    -iso_mbr_part_type a2a0d0ebe5b9334487c068b6b72699c7 \
    -c '/boot.catalog' \
    -b '/boot/grub/i386-pc/eltorito.img' \
    -no-emul-boot \
    -boot-load-size 4 \
    -boot-info-table \
    --grub2-boot-info \
    -eltorito-alt-boot \
    -e '--interval:appended_partition_2:all::' \
    -no-emul-boot \
    -boot-load-size "$efi_count" \
    "$TREE"

  echo "==> Verify hybrid GPT (EFI + Gap1 · no past-EOF · backup GPT at EOF)"
  python3 - "$ISO_OUT" "$efi_count" <<'PY'
import sys, subprocess, re
from pathlib import Path
p = Path(sys.argv[1])
efi_count = int(sys.argv[2])
size = p.stat().st_size
secs = size // 512
print("iso_size_mb", round(size/1024/1024, 1), "sectors", secs)
b = p.read_bytes()
assert b[510]==0x55 and b[511]==0xAA, "MBR 55AA missing"
gpt = b[512:1024]
assert gpt[0:8] == b"EFI PART", "GPT header missing"
backup = int.from_bytes(gpt[32:40], "little")
assert backup == secs - 1, f"backup GPT not at EOF: backup={backup} last={secs-1}"
out = subprocess.check_output(["fdisk", "-l", str(p)], text=True, stderr=subprocess.STDOUT)
print(out)
if "EFI System" not in out:
    raise SystemExit("FATAL: remaster lost EFI System partition — Rufus DD will fail")
# Ubuntu stock has 3 parts: ISO9660 + EFI + Gap1
nparts = len(re.findall(rf"{re.escape(str(p))}\d+", out))
print("partition_count", nparts)
if nparts < 2:
    raise SystemExit("FATAL: expected >=2 GPT partitions")
# El Torito EFI must not extend past EOF (Rufus rejects)
rep = subprocess.run(
    ["xorriso", "-indev", str(p), "-report_system_area", "plain"],
    capture_output=True, text=True,
)
blob = (rep.stdout or "") + (rep.stderr or "")
m = re.search(r"EFI image start and size:\s*(\d+)\s*\*\s*2048\s*,\s*(\d+)\s*\*\s*512", blob)
if m:
    start = int(m.group(1)) * 2048
    end = start + int(m.group(2)) * 512
    print(f"EFI eltorito [{start},{end}) past_eof={end>size}")
    if end > size:
        raise SystemExit("FATAL: El-Torito EFI past EOF — Rufus will fail")
    if int(m.group(2)) != efi_count:
        print(f"WARN: EFI boot-load-size {m.group(2)} != efi.img sectors {efi_count}")
print("hybrid GPT/EFI OK")
PY
  if xorriso -indev "$ISO_OUT" -pvd_info 2>&1 | grep -q 'Read start address.*larger'; then
    echo "FATAL: ISO still has past-EOF boot pointer" >&2
    exit 1
  fi
  # Fill trailing free space as Gap1 like Ubuntu stock (Rufus/isohybrid 호환)
  if command -v sgdisk >/dev/null; then
    local p2_end last_u start3
    p2_end="$(sgdisk -i 2 "$ISO_OUT" | awk -F: '/Last sector/{match($2,/[0-9]+/); print substr($2,RSTART,RLENGTH); exit}')"
    last_u="$(sgdisk -p "$ISO_OUT" 2>/dev/null | sed -n 's/.*last usable sector is //p' | head -1)"
    start3=$((p2_end + 1))
    if [[ -n "$p2_end" && -n "$last_u" && "$start3" -le "$last_u" ]]; then
      # only add if part3 missing
      if ! sgdisk -i 3 "$ISO_OUT" 2>/dev/null | grep -q 'Partition GUID code'; then
        echo "==> Add Gap1 partition ${start3}:${last_u}"
        sgdisk -n "3:${start3}:${last_u}" -t 3:0700 -c 3:Gap1 "$ISO_OUT" >/dev/null
        sgdisk -e "$ISO_OUT" >/dev/null || true
      fi
    fi
    sgdisk -p "$ISO_OUT" || true
    sgdisk -v "$ISO_OUT" || true
  fi
  xorriso -indev "$ISO_OUT" -ls /whick-os/etc/whick 2>/dev/null | head -5 || true
  rm -f "$OUT/whick-os-live-${PROFILE}.iso.pending"
  ls -lh "$ISO_OUT"; sha256sum "$ISO_OUT"
  echo "OK iso $ISO_OUT"
}

MODE="${1:---payload}"
case "$MODE" in
  -h|--help) usage; exit 0 ;;
  --check|check) check_only; exit 0 ;;
  --payload|payload) build_payload; exit 0 ;;
  --iso|iso) build_iso; exit 0 ;;
  *) echo "unknown: $MODE" >&2; usage; exit 1 ;;
esac
