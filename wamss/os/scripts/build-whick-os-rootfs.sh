#!/usr/bin/env bash
# Whick OS v1 — Ubuntu 26.04 LTS SSD rootfs (generic kernel · firmware · Docker bake)
# SSOT: docs/WHICK-OS.md · 3_product/os/recipe/
set -euo pipefail

OS_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PRODUCT="$(cd "$OS_ROOT/.." && pwd)"
UAB="$PRODUCT/uab"
RECIPE="$OS_ROOT/recipe"
OUT="${WHICK_OS_OUT:-${WHICK_BOOTSTRAP_OUT:-$PRODUCT/dist/os}}"
STAGE="${WHICK_OS_STAGE:-/tmp/whick-os-rootfs-build}"
ARCH="${WHICK_OS_ARCH:-amd64}"
SUITE="${WHICK_OS_SUITE:-resolute}"
MIRROR="${WHICK_OS_MIRROR:-http://archive.ubuntu.com/ubuntu/}"
DOCKER_IMAGE="${WHICK_OS_DOCKER_IMAGE:-ubuntu:resolute}"
DOCKER_BUNDLE="${WHICK_DOCKER_CE_BUNDLE:-}"
LOCK="${WHICK_MUSIC01_LOCK:-/data/whick-ai/2_control_center/config/solutions/music-01.json}"
# compat alias for install Artifact registry
ARCHIVE_NAME_OS="whick-os-rootfs.tar.xz"
ARCHIVE_NAME_LEGACY="whick-bootstrap-rootfs.tar.xz"

usage() {
  cat <<EOF
Usage: $(basename "$0") [--check|build]

  --check   recipe · lock · docker bundle 존재만 검증 (debootstrap 안 함)
  build     기본 — rootfs 생성
EOF
}

publish_os_release() {
  local archive="$1"
  local product_map="$PRODUCT/scripts/apply-product-map.py"
  [[ -f "$archive" ]] || { echo "ERROR: archive missing: $archive" >&2; return 1; }
  if [[ ! -f "$LOCK" || ! -w "$LOCK" || ! -f "$product_map" ]]; then
    echo "NOTE: skip lock/map publish in this environment"
    return 0
  fi
  local sha size
  sha="$(sha256sum "$archive" | awk '{print $1}')"
  size="$(stat -c%s "$archive")"
  python3 - "$LOCK" "$sha" "$size" "$ARCHIVE_NAME_LEGACY" "$ARCHIVE_NAME_OS" <<'PY'
import json, sys
lock_path, sha, size, legacy, osname = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4], sys.argv[5]
lock = json.load(open(lock_path))
comp = lock.setdefault("components", {}).setdefault("bootstrap_rootfs", {})
comp["file"] = legacy
comp["sha256"] = sha
comp["size_bytes"] = size
comp["suite"] = "resolute"
comp["whick_os"] = osname
comp["kernel"] = "linux-image-generic"
host = lock.setdefault("host_os", {})
host["distro"] = "ubuntu-server"
host["release"] = "26.04"
host["codename"] = "resolute"
host["variant"] = "whick-os"
host["kernel"] = "linux-image-generic"
open(lock_path, "w").write(json.dumps(lock, indent=2, ensure_ascii=False) + "\n")
print("lock updated", legacy, sha, size)
PY
  python3 "$product_map" apply --scope release 2>/dev/null || true
  python3 "$product_map" verify --scope all 2>/dev/null || true
}

resolve_docker_bundle() {
  if [[ -n "$DOCKER_BUNDLE" && -f "$DOCKER_BUNDLE" ]]; then
    echo "$DOCKER_BUNDLE"
    return 0
  fi
  local candidates=(
    "/mnt/music/whick-cc/build-staging/music-01/docker-ce-resolute-amd64.tar.gz"
    "$PRODUCT/dist/music-01/docker-ce-resolute-amd64.tar.gz"
    "/data/whick-ai_music_server/3_product/dist/music-01/docker-ce-resolute-amd64.tar.gz"
  )
  if [[ -f "$LOCK" ]]; then
    local fname
    fname="$(python3 -c "import json;d=json.load(open('$LOCK'));print(d.get('components',{}).get('docker_ce',{}).get('deb_bundle',''))" 2>/dev/null || true)"
    [[ -n "$fname" ]] && candidates+=("/mnt/music/whick-cc/build-staging/music-01/$fname")
  fi
  local c
  for c in "${candidates[@]}"; do
    [[ -f "$c" ]] && { echo "$c"; return 0; }
  done
  return 1
}

check_only() {
  echo "==> Whick OS rootfs --check"
  [[ -f "$RECIPE/allowlist.yaml" ]] || { echo "missing allowlist" >&2; exit 1; }
  [[ -f "$RECIPE/denylist.yaml" ]] || { echo "missing denylist" >&2; exit 1; }
  grep -q 'linux-image-generic' "$RECIPE/allowlist.yaml"
  grep -q 'linux-image-virtual' "$RECIPE/denylist.yaml"
  local bundle
  if bundle="$(resolve_docker_bundle)"; then
    echo "docker_bundle_ok: $bundle ($(du -h "$bundle" | awk '{print $1}'))"
  else
    echo "WARN: docker CE bundle not found — bake will skip unless WHICK_DOCKER_CE_BUNDLE set" >&2
  fi
  [[ -f "$UAB/live/lib/whick-firstboot.sh" ]] || { echo "missing firstboot" >&2; exit 1; }
  echo "OK recipe + paths"
}

MODE="${1:-build}"
case "$MODE" in
  -h|--help) usage; exit 0 ;;
  --check|check) check_only; exit 0 ;;
  build|"") ;;
  *) echo "unknown arg: $MODE" >&2; usage; exit 1 ;;
esac

mkdir -p "$OUT"
rm -rf "$STAGE"

if ! command -v debootstrap >/dev/null 2>&1; then
  if command -v docker >/dev/null 2>&1; then
    echo "==> debootstrap via docker ($DOCKER_IMAGE)"
    BUNDLE_HOST=""
    BUNDLE_HOST="$(resolve_docker_bundle || true)"
    DOCKER_VOL=()
    DOCKER_ENV=(-e WHICK_OS_OUT=/out -e WHICK_OS_STAGE=/tmp/stage -e WHICK_OS_SUITE="$SUITE")
    if [[ -n "$BUNDLE_HOST" ]]; then
      DOCKER_VOL+=(-v "$BUNDLE_HOST:/docker-ce-bundle.tar.gz:ro")
      DOCKER_ENV+=(-e WHICK_DOCKER_CE_BUNDLE=/docker-ce-bundle.tar.gz)
    fi
    docker run --rm --privileged \
      -v "$PRODUCT:/product:ro" \
      -v "$OUT:/out" \
      "${DOCKER_VOL[@]}" \
      "${DOCKER_ENV[@]}" \
      "$DOCKER_IMAGE" \
      bash -ce '
        set -euo pipefail
        apt-get update -qq
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq debootstrap xz-utils
        /product/os/scripts/build-whick-os-rootfs.sh build
      '
    # publish from host (container may lack lock write)
    if [[ -f "$OUT/$ARCHIVE_NAME_OS" ]]; then
      ln -sfn "$ARCHIVE_NAME_OS" "$OUT/$ARCHIVE_NAME_LEGACY"
      cp -f "$OUT/$ARCHIVE_NAME_OS" "$OUT/$ARCHIVE_NAME_LEGACY" 2>/dev/null || true
      publish_os_release "$OUT/$ARCHIVE_NAME_OS"
    fi
    exit 0
  fi
  echo "ERROR: debootstrap or docker required" >&2
  exit 1
fi

echo "==> debootstrap $SUITE ($ARCH) — Whick OS v1"
debootstrap --arch="$ARCH" "$SUITE" "$STAGE" "$MIRROR"

echo "==> packages (generic kernel + firmware)"
mount --bind /dev "$STAGE/dev"
mount --bind /dev/pts "$STAGE/dev/pts"
mount -t proc proc "$STAGE/proc"
mount -t sysfs sysfs "$STAGE/sys"
trap 'umount "$STAGE/dev/pts" "$STAGE/dev" "$STAGE/proc" "$STAGE/sys" 2>/dev/null || true' EXIT

chroot "$STAGE" /bin/bash -e <<'CHROOT'
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
  systemd-sysv iproute2 \
  linux-image-generic linux-firmware initramfs-tools \
  grub-efi-amd64 shim-signed \
  openssh-server curl ca-certificates python3 sudo zstd tar udev \
  wpasupplicant iw wireless-regdb
# remove virtual kernel if pulled as dependency of something
apt-get purge -y 'linux-image-virtual*' 2>/dev/null || true
apt-get autoremove -y 2>/dev/null || true
apt-get clean
rm -rf /var/cache/apt/archives/* /var/lib/apt/lists/*
find /usr/share/doc /usr/share/man -mindepth 1 -delete 2>/dev/null || true
CHROOT

echo "==> Docker CE bake (pinned deb bundle)"
BUNDLE="$(resolve_docker_bundle || true)"
if [[ -n "$BUNDLE" && -f "$BUNDLE" ]]; then
  mkdir -p "$STAGE/tmp/docker-debs"
  tar -xzf "$BUNDLE" -C "$STAGE/tmp/docker-debs"
  chroot "$STAGE" /bin/bash -e <<'CHROOT'
export DEBIAN_FRONTEND=noninteractive
set +e
# timesyncd in docker bundle can conflict with systemd already in rootfs — skip
rm -f /tmp/docker-debs/systemd-timesyncd_*.deb
dpkg -i /tmp/docker-debs/*.deb
apt-get install -y -f --no-install-recommends
set -e
systemctl enable docker.service 2>/dev/null || true
rm -rf /tmp/docker-debs
apt-get clean
rm -rf /var/cache/apt/archives/* /var/lib/apt/lists/*
docker --version || true
CHROOT
else
  echo "WARN: no docker bundle — firstboot install-docker.sh will fetch from CC" >&2
fi

echo "==> mask denylist units"
chroot "$STAGE" /bin/bash -e <<'CHROOT'
for u in snapd.service snapd.socket ModemManager.service cups.service bluetooth.service \
  cloud-init.service cloud-init-local.service cloud-config.service cloud-final.service \
  apt-daily.service apt-daily-upgrade.service apt-daily.timer apt-daily-upgrade.timer; do
  systemctl mask "$u" 2>/dev/null || true
done
CHROOT

echo "==> initramfs boot gate"
chroot "$STAGE" /bin/bash -e <<'CHROOT'
export DEBIAN_FRONTEND=noninteractive
if [[ -f /etc/initramfs-tools/conf.d/resume ]]; then
  echo 'RESUME=none' >/etc/initramfs-tools/conf.d/resume
fi
update-initramfs -c -k all
kver="$(ls /lib/modules | head -1)"
[[ -n "$kver" ]] || { echo "no kernel modules dir" >&2; exit 1; }
INITRD="/boot/initrd.img-${kver}"
[[ -f "$INITRD" ]] || INITRD=/boot/initrd.img
[[ -f "$INITRD" ]] || { echo "initrd missing" >&2; ls -la /boot >&2; exit 1; }
if ! lsinitramfs "$INITRD" 2>/dev/null | grep -Eq '(^|/)libcrypto\.so\.3$'; then
  echo "FATAL: initrd missing libcrypto.so.3" >&2
  exit 1
fi
if ! lsinitramfs "$INITRD" 2>/dev/null | grep -Eq '(^|/)systemd-udevd$'; then
  echo "FATAL: initrd missing systemd-udevd" >&2
  exit 1
fi
echo "initrd OK: $INITRD"
CHROOT

echo "==> ssh + whick user + networkd + udev DAC"
install -d "$STAGE/usr/local/sbin"
install -m 755 "$PRODUCT/install/runtime/scripts/whick-host-reboot.sh" "$STAGE/usr/local/sbin/whick-host-reboot"
install -m 755 "$PRODUCT/install/runtime/scripts/whick-rescue-reboot.sh" "$STAGE/usr/local/sbin/whick-rescue-reboot"
# NOTE: rescue 경로 폐기(2026-07-26). 헬퍼는 stub로만 남겨 구 agent 호출 시 명확히 실패.

install -d "$STAGE/etc/udev/rules.d"
cat >"$STAGE/etc/udev/rules.d/99-whick-usb-dac.rules" <<'EOF'
ACTION=="add", SUBSYSTEM=="usb", ENV{PRODUCT}=="*/*/*", RUN+="/bin/sh -c 'cat /sys$devpath/bInterfaceClass 2>/dev/null | grep -qx 01 && /sbin/modprobe snd-usb-audio || true'"
ACTION=="remove", SUBSYSTEM=="usb", ENV{PRODUCT}=="*/*/*", RUN+="/bin/sh -c 'cat /sys$devpath/bInterfaceClass 2>/dev/null | grep -qx 01 && udevadm trigger --subsystem-match=sound || true'"
EOF

# Camilla Loopback — 부팅마다 호스트에서 선로드 (컨테이너 modprobe/privileged 의존 제거)
# 없으면 ensure-aloop 실패 → fifo 폴백 → MPD hang (목록 OK·재생 불가) 가 재발한다.
install -d -m 755 "$STAGE/etc/modules-load.d"
printf '%s\n' 'snd-aloop' >"$STAGE/etc/modules-load.d/whick-aloop.conf"

chroot "$STAGE" /bin/bash -e <<'CHROOT'
passwd -l root
install -d -m 700 /root/.ssh
if [[ -f /etc/ssh/sshd_config ]]; then
  sed -i 's/^#*PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
  sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
  grep -q '^PermitRootLogin' /etc/ssh/sshd_config || echo 'PermitRootLogin no' >>/etc/ssh/sshd_config
  grep -q '^PasswordAuthentication' /etc/ssh/sshd_config || echo 'PasswordAuthentication no' >>/etc/ssh/sshd_config
fi
if ! id whick >/dev/null 2>&1; then
  useradd -m -s /bin/bash -G sudo,audio whick
fi
install -d -m 750 /etc/sudoers.d
cat >/etc/sudoers.d/whick-remote <<'SUDO'
whick ALL=(ALL) NOPASSWD: ALL
SUDO
chmod 440 /etc/sudoers.d/whick-remote
install -d -m 755 /etc/systemd/network
cat >/etc/systemd/network/10-whick-dhcp.network <<'NET'
[Match]
Name=en* eth* enx*

[Network]
DHCP=yes
NET
systemctl enable systemd-networkd.service
systemctl enable systemd-networkd-wait-online.service
install -d -m 755 /etc/systemd/system/systemd-networkd-wait-online.service.d
cat >/etc/systemd/system/systemd-networkd-wait-online.service.d/whick-any-link.conf <<'WAIT'
[Service]
ExecStart=
ExecStart=/usr/lib/systemd/systemd-networkd-wait-online --any --timeout=45
WAIT
install -d -m 1777 /tmp
ln -sf /dev/null /etc/systemd/system/tmp.mount
install -d -m 755 /etc/systemd/journald.conf.d
cat >/etc/systemd/journald.conf.d/whick-persistent.conf <<'JRN'
[Journal]
Storage=persistent
JRN
install -d -m 2755 /var/log/journal
install -d -m 755 /etc/systemd/system/getty@.service.d
cat >/etc/systemd/system/getty@.service.d/whick-autologin.conf <<'AUTO'
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin whick --noclear %I $TERM
AUTO
# Whick OS identity
install -d /etc/whick
cat >/etc/whick/os-release <<'OS'
NAME=Whick OS
VERSION=1
ID=whick-os
ID_LIKE=ubuntu
UBUNTU_CODENAME=resolute
KERNEL=linux-image-generic
OS
CHROOT

echo "==> first-boot units"
install -d "$STAGE/var/lib/whick"
install -m 755 "$UAB/live/lib/whick-firstboot.sh" "$STAGE/usr/local/sbin/whick-firstboot.sh"
install -m 755 "$UAB/live/lib/whick-orchestrator-phases.sh" "$STAGE/usr/local/sbin/whick-orchestrator-phases.sh"
install -d "$STAGE/etc/systemd/system"
cat >"$STAGE/etc/systemd/system/whick-install-firstboot.service" <<'UNIT'
[Unit]
Description=Whick OS firstboot (runtime on SSD)
After=systemd-networkd.service docker.service
Wants=systemd-networkd.service
ConditionPathExists=!/var/lib/whick/firstboot-done

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/whick-firstboot.sh
RemainAfterExit=yes
Restart=on-failure
RestartSec=60

[Install]
WantedBy=multi-user.target
UNIT
chroot "$STAGE" systemctl enable whick-install-firstboot.service

echo "==> archive"
umount "$STAGE/dev/pts" "$STAGE/dev" "$STAGE/proc" "$STAGE/sys" 2>/dev/null || true
trap - EXIT

ARCHIVE_OS="$OUT/$ARCHIVE_NAME_OS"
ARCHIVE_LEGACY="$OUT/$ARCHIVE_NAME_LEGACY"
tar -cJf "$ARCHIVE_OS" \
  --exclude='./proc' --exclude='./sys' --exclude='./dev' --exclude='./run' --exclude='./tmp' \
  -C "$STAGE" .
cp -f "$ARCHIVE_OS" "$ARCHIVE_LEGACY"
ls -lh "$ARCHIVE_OS"
sha256sum "$ARCHIVE_OS"

publish_os_release "$ARCHIVE_OS"
# also stage for CC install path
STAGING="/mnt/music/whick-cc/build-staging/music-01"
if [[ -d "$STAGING" && -w "$STAGING" ]]; then
  cp -f "$ARCHIVE_OS" "$STAGING/$ARCHIVE_NAME_LEGACY"
  cp -f "$ARCHIVE_OS" "$STAGING/$ARCHIVE_NAME_OS" 2>/dev/null || true
  echo "staged → $STAGING"
fi
echo "OK  Whick OS rootfs: $ARCHIVE_OS"
