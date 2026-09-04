# shellcheck shell=bash
# Bootstrap tarball must list versioned initrd + vmlinuz (USB Live: python tarfile or tar -tJ fallback)

bootstrap_tar_boot_ready() {
  local path="${1:?path}"
  [[ -f "$path" ]] || return 1
  if python3 - <<'PY' "$path"
import re, sys, tarfile
path = sys.argv[1]
mode = "r:xz" if path.endswith(".xz") else "r:gz"
with tarfile.open(path, mode) as tf:
    names = tf.getnames()
pat_initrd = re.compile(r"(^|/)boot/initrd\.img-[^/]+$")
pat_vmlinuz = re.compile(r"(^|/)boot/vmlinuz-[^/]+$")
if not any(pat_initrd.search(n) for n in names):
    raise SystemExit("bootstrap tar missing boot/initrd.img-*")
if not any(pat_vmlinuz.search(n) for n in names):
    raise SystemExit("bootstrap tar missing boot/vmlinuz-*")
PY
  then
    return 0
  fi
  if [[ "$path" == *.xz ]] && command -v tar >/dev/null 2>&1; then
    tar -tJf "$path" 2>/dev/null | grep -qE '(^|/)boot/initrd\.img-[^/]+$' \
      && tar -tJf "$path" 2>/dev/null | grep -qE '(^|/)boot/vmlinuz-[^/]+$'
    return $?
  fi
  return 1
}

# Deep check: initrd archive inside a boot-ready tarball must carry libcrypto.so.3
# and systemd-udevd (the exact field failure mode). Uses lsinitramfs when available,
# else unpacks with unmkinitramfs/cpio.
initrd_image_boot_ready() {
  local img="${1:?initrd path}"
  [[ -f "$img" ]] || return 1
  local listing base
  if command -v lsinitramfs >/dev/null 2>&1; then
    listing="$(lsinitramfs "$img" 2>/dev/null)" || return 1
    printf '%s\n' "$listing" | grep -Eq '(^|/)libcrypto\.so\.3$' || return 1
    printf '%s\n' "$listing" | grep -Eq '(^|/)systemd-udevd$' || return 1
    return 0
  fi
  if ! command -v unmkinitramfs >/dev/null 2>&1; then
    echo "initrd_image_boot_ready: no lsinitramfs/unmkinitramfs to inspect $img" >&2
    return 2
  fi
  local tmp="${TMPDIR:-/tmp}/whick-initrd-check-$$"
  rm -rf "$tmp"; mkdir -p "$tmp"
  unmkinitramfs "$img" "$tmp" 2>/dev/null || return 1
  base="$tmp"; [[ -d "$tmp/main" ]] && base="$tmp/main"
  find "$base" -path '*/libcrypto.so.3' 2>/dev/null | grep -q . || { rm -rf "$tmp"; return 1; }
  find "$base" -name 'systemd-udevd' 2>/dev/null | grep -q . || { rm -rf "$tmp"; return 1; }
  rm -rf "$tmp"
  return 0
}
