#!/usr/bin/env bash
# 로그인 시 USB(whick-laptop-usb) 가 있으면 auto-install.sh 실행
set -euo pipefail

MARKER="${WHICK_USB_MARKER:-$HOME/.whick-usb-install-done}"
LOG="${WHICK_USB_LOG:-$HOME/whick-usb-install.log}"

# USB 마운트 대기
sleep "${WHICK_USB_MOUNT_WAIT:-10}"

find_usb_root() {
  local d
  for d in \
    /media/"$USER"/*/whick-laptop-usb \
    /media/"$USER"/whick-laptop-usb \
    /run/media/"$USER"/*/whick-laptop-usb \
    /run/media/"$USER"/whick-laptop-usb; do
    [[ -d "$d" && -x "$d/auto-install.sh" ]] || continue
    echo "$d"
    return 0
  done
  return 1
}

USB_ROOT=""
if ! USB_ROOT="$(find_usb_root)"; then
  exit 0
fi

if [[ -f "$MARKER" && "${WHICK_USB_FORCE:-}" != "1" ]]; then
  exit 0
fi

{
  echo ""
  echo "==> Whick USB 자동 실행 $(date '+%Y-%m-%d %H:%M:%S')"
  echo "    $USB_ROOT"
} >>"$LOG"

export WHICK_SKIP_END_PAUSE=1
export WHICK_USB_OPEN_ADMIN=1
export DISPLAY="${DISPLAY:-:0}"

# 진행 상황을 볼 수 있게 터미널에서 실행 (백그라운드만 하면 sudo 입력 불가)
if [[ -n "${DISPLAY:-}" ]] && command -v gnome-terminal >/dev/null; then
  exec gnome-terminal --title="Whick USB 설치" --wait -- bash -lc \
    "$(printf '%q' "$USB_ROOT/auto-install.sh"); ec=\$?; echo; read -r -p 'Enter로 종료…' _; exit \$ec"
fi

for term in x-terminal-emulator konsole xfce4-terminal xterm; do
  if command -v "$term" >/dev/null; then
    exec "$term" -e bash -lc \
      "$(printf '%q' "$USB_ROOT/auto-install.sh"); ec=\$?; echo; read -r -p 'Enter로 종료…' _; exit \$ec"
  fi
done

exec bash "$USB_ROOT/auto-install.sh"
