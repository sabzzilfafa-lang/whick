#!/usr/bin/env bash
# Whick 원클릭 설치 — 전원 유지 → Docker → CC 연결 → runtime 기동
# VIP Room 압축 해제 후: ./install-whick.sh 또는 「Whick 설치」 더블클릭
set -euo pipefail

ROOT="${WHICK_INSTALL_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$ROOT"

# deb(/usr/lib/whick) · tar(~/whick-3product/scripts) — setup.sh 단독 실행 시 tar 우선
if [[ -f "${WHICK_SCRIPTS_DIR:-}/whick-cc-url.sh" ]]; then
  :
elif [[ -f "$ROOT/scripts/whick-cc-url.sh" ]]; then
  WHICK_SCRIPTS_DIR="$ROOT/scripts"
elif [[ -f /usr/lib/whick/whick-cc-url.sh ]]; then
  WHICK_SCRIPTS_DIR=/usr/lib/whick
else
  WHICK_SCRIPTS_DIR="$ROOT/scripts"
fi
export WHICK_SCRIPTS_DIR

# shellcheck source=whick-cc-url.sh
source "$WHICK_SCRIPTS_DIR/whick-cc-url.sh"

pause_on_error() {
  echo ""
  echo "설치가 중단되었습니다. 위 메시지를 확인하세요."
  read -r -p "Enter 키로 종료…" _ || true
}

trap 'ec=$?; [[ $ec -eq 0 ]] || pause_on_error' EXIT

if [[ "$(id -u)" -eq 0 ]]; then
  echo "root 로 실행하지 마세요. 일반 사용자 계정으로 실행하세요."
  exit 1
fi

chmod +x "$ROOT"/install-whick.sh "$ROOT"/scripts/*.sh 2>/dev/null || true

echo "╔══════════════════════════════════════════════════════╗"
echo "║  Whick 3_product — 원클릭 설치                        ║"
echo "║  전원 유지 → Docker → 관제 연결 → agent 기동          ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
echo "경로: $ROOT"
echo ""

# ── 1–2. 전원 유지 + Docker (laptop-first-boot 에 포함) ──
echo "▶ [1/3] Docker · runtime 준비"
export WHICK_INSTALL_ROOT="$ROOT"
export WHICK_SCRIPTS_DIR
"$WHICK_SCRIPTS_DIR/laptop-first-boot.sh"
echo ""

# ── 3. CC URL · .env ──
echo "▶ [2/3] 본사 관제(CC) 연결 확인"
ENV_FILE="$ROOT/.env"
[[ -f "$ENV_FILE" ]] || cp "$ROOT/.env.example" "$ENV_FILE"

CC_URL=""
if CC_URL="$(whick_set_env_cc_url "$ENV_FILE" "$ROOT/.env.example")"; then
  echo "OK  CC API: $CC_URL"
else
  echo ""
  echo "⚠ CC API에 연결할 수 없습니다."
  echo "  · Wi-Fi 연결 확인"
  echo "  · 또는 다른 터미널에서 SSH 터널:"
  echo "      ssh -N -L 8090:127.0.0.1:8090 whick@ssh.whick.org"
  echo "  · 터널 후 이 스크립트를 다시 실행하세요."
  exit 1
fi
if ! grep -q '^WHICK_RUNTIME_HOST_DIR=' "$ENV_FILE" 2>/dev/null; then
  echo "WHICK_RUNTIME_HOST_DIR=$ROOT" >> "$ENV_FILE"
fi
echo ""

# ── 4. runtime ──
echo "▶ [3/3] Docker runtime 기동 (agent · monitor · audio)"
mkdir -p "$ROOT/library/incoming"

run_compose() {
  cd "$ROOT"
  docker compose --env-file "$ENV_FILE" up -d --build
  sleep 4
  docker compose ps
  echo ""
  docker compose logs --tail=10 agent monitor audio 2>/dev/null || true
}

if whick_docker_ready; then
  run_compose
elif groups 2>/dev/null | grep -q '\bdocker\b'; then
  sg docker -c "cd $(printf '%q' "$ROOT") && docker compose --env-file $(printf '%q' "$ENV_FILE") up -d --build"
  sleep 4
  sg docker -c "cd $(printf '%q' "$ROOT") && docker compose ps"
  sg docker -c "cd $(printf '%q' "$ROOT") && docker compose logs --tail=10 agent monitor audio" 2>/dev/null || true
else
  echo "Docker 그룹 적용이 필요합니다."
  echo "  → 터미널을 닫고 다시 로그인한 뒤 ./install-whick.sh 를 한 번 더 실행하세요."
  echo "  → 또는: newgrp docker  후  ./scripts/laptop-test-setup.sh"
  exit 1
fi

echo ""
echo "══════════════════════════════════════════════════════"
echo "  설치·기동 완료"
echo "══════════════════════════════════════════════════════"
echo ""
echo "  로컬 확인:  curl -s http://127.0.0.1:8787/health"
echo "  agent 상태: docker compose logs -f agent"
echo "  관제 UI:    https://admin.whick.org/  → 뮤직서버관제"
echo ""
if [[ "${WHICK_CUSTOMER_MODE:-}" == "1" ]]; then
  command -v xdg-open >/dev/null && xdg-open "https://admin.whick.org/" 2>/dev/null || true
elif command -v xdg-open >/dev/null; then
  read -r -p "관제 페이지를 브라우저에서 열까요? [y/N] " open_admin || true
  if [[ "${open_admin,,}" == "y" ]]; then
    xdg-open "https://admin.whick.org/" 2>/dev/null || true
  fi
fi

# 더블클릭용 .desktop (절대 경로 갱신)
DESKTOP="$ROOT/Whick-설치.desktop"
cat >"$DESKTOP" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Whick 설치
Name[ko]=Whick 설치 (원클릭)
Comment=전원 유지 · Docker · 관제 연결 · agent 기동
Exec=bash -lc 'cd $(printf '%q' "$ROOT") && ./install-whick.sh'
Icon=utilities-terminal
Terminal=true
Categories=Utility;
StartupNotify=true
EOF
chmod +x "$DESKTOP" "$ROOT/install-whick.sh" 2>/dev/null || true
if command -v gio >/dev/null; then
  gio set "$DESKTOP" metadata::trusted true 2>/dev/null || true
fi

if [[ "${WHICK_SKIP_END_PAUSE:-}" != "1" ]]; then
  echo ""
  read -r -p "Enter 키로 종료…" _ || true
fi
