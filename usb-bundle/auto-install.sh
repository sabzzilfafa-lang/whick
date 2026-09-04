#!/usr/bin/env bash
# USB → ~/whick-3_product 복사 · Docker · CC(admin 직접) · runtime 기동 (원클릭)
# 터미널 명령 없이 desktop · 로그인 autostart 에서 호출
_self="${BASH_SOURCE[0]:-$0}"
if [[ ! -t 1 && -z "${WHICK_TERM_LAUNCHED:-}" ]]; then
  export WHICK_TERM_LAUNCHED=1
  _dir="$(cd "$(dirname "$_self")" && pwd)"
  _cmd="export WHICK_TERM_LAUNCHED=1; cd $(printf '%q' "$_dir") && bash $(printf '%q' "$_self")"
  for term in gnome-terminal x-terminal-emulator konsole xfce4-terminal xterm; do
    if command -v "$term" >/dev/null; then
      case "$term" in
        gnome-terminal)
          exec gnome-terminal --title="Whick USB 설치" -- bash -lc "$_cmd; ec=\$?; echo; read -r -p 'Enter로 종료…' _; exit \$ec"
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
SRC="${USB_ROOT}/whick-3_product"
TARGET="${WHICK_TARGET:-$HOME/whick-3_product}"
LOG="${WHICK_USB_LOG:-$HOME/whick-usb-install.log}"
MARKER="${WHICK_USB_MARKER:-$HOME/.whick-usb-install-done}"
LOCK="${WHICK_USB_LOCK:-$HOME/.whick-usb-install.lock}"

mkdir -p "$(dirname "$LOG")"

exec > >(tee -a "$LOG") 2>&1

echo ""
echo "══════════════════════════════════════════════════════"
echo " Whick USB 자동 설치  $(date '+%Y-%m-%d %H:%M:%S')"
echo " USB:    $USB_ROOT"
echo " 대상:   $TARGET"
echo " 로그:   $LOG"
echo "══════════════════════════════════════════════════════"
echo ""

if [[ "$(id -u)" -eq 0 ]]; then
  echo "root 로 실행하지 마세요. 일반 사용자로 실행하세요." >&2
  exit 1
fi

if [[ ! -d "$SRC" ]]; then
  echo "ERROR: whick-3_product 없음: $SRC" >&2
  exit 1
fi

if [[ -f "$MARKER" && "${WHICK_USB_FORCE:-}" != "1" ]]; then
  echo "이미 설치 완료 ($MARKER)."
  echo "재설치: WHICK_USB_FORCE=1 ./auto-install.sh"
  exit 0
fi

if [[ -f "$LOCK" ]]; then
  pid="$(cat "$LOCK" 2>/dev/null || true)"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    echo "설치가 이미 진행 중입니다 (pid $pid). 로그: $LOG"
    exit 0
  fi
  rm -f "$LOCK"
fi
echo $$ >"$LOCK"
trap 'rm -f "$LOCK"' EXIT

echo "==> [1/3] USB → 홈 복사"
mkdir -p "$TARGET"
rsync -a --delete \
  --exclude '.env' \
  --exclude 'library/incoming/*' \
  --exclude 'dist/' \
  "$SRC/" "$TARGET/"

chmod +x "$TARGET"/install-whick.sh "$TARGET"/scripts/*.sh 2>/dev/null || true
cp -f "$USB_ROOT"/ssh-tunnel-cc.sh "$USB_ROOT"/run-test.sh "$TARGET/scripts/" 2>/dev/null || true
chmod +x "$TARGET/scripts/ssh-tunnel-cc.sh" "$TARGET/scripts/run-test.sh" 2>/dev/null || true

echo ""
echo "==> [2/3] 원클릭 설치 (전원·Docker·관제·runtime)"
echo "    CC: SSH 터널 없이 admin.whick.org 직접 연결 (검증됨)"
echo ""

export WHICK_INSTALL_ROOT="$TARGET"
export WHICK_SCRIPTS_DIR="$TARGET/scripts"
export WHICK_SKIP_END_PAUSE="${WHICK_SKIP_END_PAUSE:-1}"
export WHICK_CUSTOMER_MODE="${WHICK_CUSTOMER_MODE:-1}"

if ! bash "$TARGET/scripts/whick-one-click-install.sh"; then
  echo ""
  echo "설치 실패 — Wi-Fi · sudo 비밀번호 확인 후 다시 실행하세요."
  echo "  $USB_ROOT/auto-install.sh"
  exit 1
fi

if [[ -x "$TARGET/scripts/laptop-power-always-on.sh" ]]; then
  echo ""
  echo "==> 전원 유지 (절전·뚜껑·전원키)"
  WHICK_SCRIPTS_DIR="$TARGET/scripts" bash "$TARGET/scripts/laptop-power-always-on.sh" apply || {
    echo "WARN: 전원 설정 일부 실패 — 설치 후 수동: $TARGET/scripts/laptop-power-always-on.sh apply"
  }
fi

echo ""
echo "==> [3/3] 완료 표시"
date -Iseconds >"$MARKER"
echo "OK  $MARKER"

echo ""
echo "══════════════════════════════════════════════════════"
echo "  설치·기동 완료"
echo "══════════════════════════════════════════════════════"
echo "  curl -s http://127.0.0.1:8787/health"
echo "  관제: https://admin.whick.org/ → 뮤직서버관제"
echo ""

if [[ "${WHICK_USB_OPEN_ADMIN:-1}" == "1" ]] && command -v xdg-open >/dev/null; then
  xdg-open "https://admin.whick.org/" 2>/dev/null || true
fi

if [[ "${WHICK_SKIP_END_PAUSE:-}" != "1" ]]; then
  read -r -p "Enter 키로 종료…" _ || true
fi
