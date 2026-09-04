#!/usr/bin/env bash
# 노트북 1회 실행 — 이후 USB 꽂고 부팅·로그인 시 자동 설치
_self="${BASH_SOURCE[0]:-$0}"
if [[ ! -t 1 && -z "${WHICK_TERM_LAUNCHED:-}" ]]; then
  export WHICK_TERM_LAUNCHED=1
  _dir="$(cd "$(dirname "$_self")" && pwd)"
  _cmd="export WHICK_TERM_LAUNCHED=1; cd $(printf '%q' "$_dir") && bash $(printf '%q' "$_self")"
  for term in gnome-terminal x-terminal-emulator konsole xfce4-terminal xterm; do
    if command -v "$term" >/dev/null; then
      case "$term" in
        gnome-terminal)
          exec gnome-terminal --title="Whick USB 부팅 자동" -- bash -lc "$_cmd; ec=\$?; echo; read -r -p 'Enter로 종료…' _; exit \$ec"
          ;;
        *)
          exec "$term" -e bash -lc "$_cmd; ec=\$?; echo; read -r -p 'Enter로 종료…' _; exit \$ec"
          ;;
      esac
    fi
  done
fi
set -euo pipefail

USB_ROOT="$(cd "$(dirname "$0")" && pwd)"
BIN_DIR="$HOME/.local/bin"
AUTOSTART="$HOME/.config/autostart"
WATCH="$BIN_DIR/whick-usb-watch.sh"
DESKTOP="$AUTOSTART/whick-usb-install.desktop"

mkdir -p "$BIN_DIR" "$AUTOSTART"

cp -f "$USB_ROOT/watch-usb-at-login.sh" "$WATCH"
chmod +x "$WATCH"

cat >"$DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Name=Whick USB 자동 설치
Comment=USB whick-laptop-usb 감지 시 설치 실행
Exec=bash -lc $(printf '%q' "$WATCH")
Hidden=false
NoDisplay=true
X-GNOME-Autostart-enabled=true
X-GNOME-Autostart-Delay=5
EOF

chmod +x "$DESKTOP" 2>/dev/null || true

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║  부팅·로그인 자동 설치 등록 완료                        ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
echo "  등록: $DESKTOP"
echo "  감시: $WATCH"
echo ""
echo "다음부터:"
echo "  1) USB(whick-laptop-usb) 꽂기"
echo "  2) 노트북 전원 ON → Ubuntu 로그인"
echo "  3) 터미널이 자동으로 열리며 설치 (sudo 비밀번호만 입력)"
echo ""
echo "지금 바로 설치: ./auto-install.sh"
echo ""

if [[ "${WHICK_SKIP_END_PAUSE:-}" != "1" ]]; then
  read -r -p "Enter 키로 종료…" _ || true
fi
