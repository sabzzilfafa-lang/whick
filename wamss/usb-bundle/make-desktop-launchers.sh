#!/usr/bin/env bash
# USB 루트 .desktop 생성 (build-laptop-usb.sh 에서 호출)
set -euo pipefail

USB_ROOT="$(cd "$(dirname "$0")" && pwd)"

write_desktop() {
  local name="$1" title="$2" comment="$3" script="$4"
  local file="$USB_ROOT/${name}.desktop"
  cat >"$file" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=${title}
Name[ko]=${title}
Comment=${comment}
Exec=bash -lc 'cd $(printf '%q' "$USB_ROOT") && ./${script}'
Icon=utilities-terminal
Terminal=false
Categories=Utility;
StartupNotify=true
EOF
  chmod +x "$file"
}

write_desktop "Whick-USB-설치" "Whick USB 설치" "복사·Docker·관제·runtime (지금 바로)" "auto-install.sh"
write_desktop "Whick-USB-부팅자동" "Whick USB 부팅 자동" "로그인 시 USB 자동 설치 (1회 등록)" "register-login-autostart.sh"

if command -v gio >/dev/null; then
  gio set "$USB_ROOT/Whick-USB-설치.desktop" metadata::trusted true 2>/dev/null || true
  gio set "$USB_ROOT/Whick-USB-부팅자동.desktop" metadata::trusted true 2>/dev/null || true
fi

echo "OK  desktop launchers in $USB_ROOT"
