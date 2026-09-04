#!/usr/bin/env bash
# Whick 뮤직서버 — Docker 컨테이너 재실행 (고객용)
# VIP Room 첨부 또는 ~/whick-3product/scripts/whick-docker-restart.sh
set -euo pipefail

find_install_root() {
  if [[ -n "${WHICK_INSTALL_ROOT:-}" ]] && [[ -f "${WHICK_INSTALL_ROOT}/compose.yaml" ]]; then
    echo "$WHICK_INSTALL_ROOT"
    return 0
  fi
  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  local candidates=("$HOME/whick-3product" "/opt/whick/runtime" "$script_dir/..")
  for d in "${candidates[@]}"; do
    if [[ -f "$d/compose.yaml" ]]; then
      echo "$(cd "$d" && pwd)"
      return 0
    fi
  done
  return 1
}

if ! ROOT="$(find_install_root)"; then
  echo "Whick 설치 폴더(compose.yaml)를 찾을 수 없습니다."
  echo "  ~/whick-3product 가 있는지 확인하거나 VIP Room 설치 안내를 따라 주세요."
  exit 1
fi

cd "$ROOT"
ENV_FILE="$ROOT/.env"

echo "==> Whick Docker 재실행"
echo "    경로: $ROOT"
echo ""

if ! command -v docker >/dev/null; then
  echo "Docker가 설치되어 있지 않습니다."
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "docker compose v2 가 필요합니다."
  exit 1
fi

if [[ -f "$ENV_FILE" ]]; then
  docker compose --env-file "$ENV_FILE" restart
else
  docker compose restart
fi

sleep 3
echo ""
docker compose ps
echo ""
if curl -sf --max-time 8 http://127.0.0.1:8787/health >/dev/null; then
  echo "OK  뮤직서버(audio) 정상"
else
  echo "⚠ audio 확인 실패 — 1~2분 후 다시 실행하거나 고객센터·관제에 문의"
fi
