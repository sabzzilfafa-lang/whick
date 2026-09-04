#!/usr/bin/env bash
# VIP Room setup.sh / setup.desktop — 고객용 (컴퓨터·리눅스 몰라도 됨)
# 같은 폴더(다운로드)에 whick-3product-*.tar.gz 가 있어야 합니다.
_self="${BASH_SOURCE[0]:-$0}"
if [[ ! -t 1 && -z "${WHICK_TERM_LAUNCHED:-}" && -z "${WHICK_FROM_DEB:-}" ]]; then
  export WHICK_TERM_LAUNCHED=1
  _dir="$(cd "$(dirname "$_self")" && pwd)"
  _cmd="export WHICK_TERM_LAUNCHED=1 WHICK_DOWNLOAD_DIR=$(printf '%q' "$_dir"); bash $(printf '%q' "$_self")"
  for term in gnome-terminal x-terminal-emulator konsole xfce4-terminal xterm; do
    if command -v "$term" >/dev/null 2>&1; then
      case "$term" in
        gnome-terminal)
          exec gnome-terminal --title="Whick 설치" -- bash -lc "$_cmd; echo; read -r -p 'Enter로 종료…' _"
          ;;
        *)
          exec "$term" -e bash -lc "$_cmd; echo; read -r -p 'Enter로 종료…' _"
          ;;
      esac
    fi
  done
fi
set -euo pipefail

WHICK_INSTALL_ROOT="${WHICK_INSTALL_ROOT:-$HOME/whick-3product}"
WHICK_CUSTOMER_MODE=1
export WHICK_CUSTOMER_MODE

pause_end() {
  echo ""
  read -r -p "완료. Enter 키로 창을 닫습니다…" _ 2>/dev/null || sleep 5
}

on_error() {
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  설치 중 문제가 발생했습니다."
  echo "  Wi-Fi 연결 · sudo 비밀번호 확인 후 아래 중 하나:"
  echo "    curl -fsSL https://whick.org/whick-content/customer/setup.sh | bash"
  echo "    bash ~/whick-3product/scripts/whick-customer-install.sh"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  pause_end
}

trap on_error ERR

if [[ "$(id -u)" -eq 0 ]]; then
  echo "관리자(root) 계정이 아닌, 평소 쓰는 사용자로 실행해 주세요."
  exit 1
fi

# ── 다운로드 폴더 찾기 (스크립트와 같은 위치 우선) ──
find_download_dir() {
  local d cand script_dir=""
  script_dir="$(cd "$(dirname "$_self")" && pwd 2>/dev/null || true)"
  for cand in \
    "${GIO_LAUNCHED_DESKTOP_FILE:+$(dirname "$GIO_LAUNCHED_DESKTOP_FILE")}" \
    "$script_dir" \
    "${WHICK_DOWNLOAD_DIR:-}" \
    "$(xdg-user-dir DOWNLOAD 2>/dev/null || true)" \
    "$HOME/다운로드" \
    "$HOME/Downloads"; do
    [[ -n "$cand" && -d "$cand" ]] || continue
    d="$(cd "$cand" && pwd)"
    if ls "$d"/whick-3product-*.tar.gz >/dev/null 2>&1; then
      echo "$d"
      return 0
    fi
  done
  return 1
}

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║           Whick 뮤직서버 — 자동 설치                    ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

DOWNLOAD_DIR=""
if ! DOWNLOAD_DIR="$(find_download_dir)"; then
  echo "다운로드 폴더에서 whick-3product-*.tar.gz 를 찾을 수 없습니다."
  echo ""
  echo "VIP Room 공지에서 아래 두 파일을 **같은 폴더**(다운로드)에 받아 주세요."
  echo "  ① whick-3product-….tar.gz"
  echo "  ② setup.deb  (더블클릭 → 설치)"
  echo ""
  echo "setup.deb 를 더블클릭 → 「설치」 버튼을 누르세요."
  pause_end
  exit 1
fi

ARCHIVE="$(ls -1 "$DOWNLOAD_DIR"/whick-3product-*.tar.gz 2>/dev/null | sort -r | head -1)"
echo "다운로드 폴더: $DOWNLOAD_DIR"
echo "설치 패키지:   $(basename "$ARCHIVE")"
echo ""

# ── 기존 Whick · Docker 전부 제거 후 재설치 ──
echo "▶ [1/4] 기존 Whick 설치 제거 (재설치·오류 복구)"
if [[ -d "$WHICK_INSTALL_ROOT" ]] && [[ -f "$WHICK_INSTALL_ROOT/compose.yaml" ]]; then
  if command -v docker >/dev/null && docker compose version >/dev/null 2>&1; then
    (cd "$WHICK_INSTALL_ROOT" && docker compose down -v --remove-orphans 2>/dev/null) || true
  fi
fi
for c in whick-agent whick-monitor whick-audio; do
  docker rm -f "$c" 2>/dev/null || true
done
for img in whick/agent:dev whick/monitor:dev whick/audio:dev; do
  docker rmi -f "$img" 2>/dev/null || true
done
docker volume rm whick-runtime_whick-data 2>/dev/null || true
rm -rf "$WHICK_INSTALL_ROOT"
echo "   OK  이전 설치 삭제 완료"
echo ""

# ── 압축 해제 ──
echo "▶ [2/4] 설치 파일 풀기 → $WHICK_INSTALL_ROOT"
tar xzf "$ARCHIVE" -C "$HOME"
chmod +x "$WHICK_INSTALL_ROOT"/scripts/*.sh 2>/dev/null || true
echo ""

# ── Docker · CC · runtime ──
echo "▶ [3/4] Docker · 본사 관제 연결"
echo "   (sudo 비밀번호 = Ubuntu 로그인 비밀번호 · 전원 설정은 설치 중 건너뜀)"
export WHICK_INSTALL_ROOT
export WHICK_SKIP_END_PAUSE=1
if [[ -x /usr/lib/whick/whick-one-click-install.sh && -f /usr/lib/whick/whick-cc-url.sh ]]; then
  export WHICK_SCRIPTS_DIR="/usr/lib/whick"
  bash /usr/lib/whick/whick-one-click-install.sh
else
  export WHICK_SCRIPTS_DIR="$WHICK_INSTALL_ROOT/scripts"
  bash "$WHICK_INSTALL_ROOT/scripts/whick-one-click-install.sh"
fi
echo ""

# ── 전원 설정 파일만 (재부팅 후 적용) ──
PWR=""
if [[ -x /usr/lib/whick/laptop-power-always-on.sh ]]; then
  PWR=/usr/lib/whick/laptop-power-always-on.sh
elif [[ -x "$WHICK_INSTALL_ROOT/scripts/laptop-power-always-on.sh" ]]; then
  PWR="$WHICK_INSTALL_ROOT/scripts/laptop-power-always-on.sh"
fi
if [[ -n "$PWR" ]]; then
  echo "▶ [4/5] 전원 설정 파일 기록 (재부팅 후 적용)"
  WHICK_SCRIPTS_DIR="${WHICK_SCRIPTS_DIR:-$WHICK_INSTALL_ROOT/scripts}" bash "$PWR" write-config-only || true
  echo "   ※ 설치 후 **한 번 재부팅**하면 절전·뚜껑 닫기 설정 완료"
  echo ""
fi

echo "▶ [5/5] 최종 확인"
if curl -sf --max-time 3 http://127.0.0.1:8787/health >/dev/null; then
  echo "   OK  뮤직서버 runtime 정상"
else
  echo "   ⚠ audio health 확인 실패 — Wi-Fi·잠시 후 재실행"
fi

echo ""
echo "══════════════════════════════════════════════════════"
echo "  Whick 설치가 완료되었습니다."
echo "  관제: https://admin.whick.org/  → 뮤직서버관제"
echo "══════════════════════════════════════════════════════"
if command -v xdg-open >/dev/null; then
  xdg-open "https://admin.whick.org/" 2>/dev/null || true
fi
pause_end
