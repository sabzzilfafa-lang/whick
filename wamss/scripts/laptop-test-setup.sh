#!/usr/bin/env bash
# 고객용 runtime 테스트 — Linux 노트북 (미니PC 대용)
# CC API는 본사 서버 127.0.0.1:8090 → SSH 터널 필요 (별 터미널)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> Whick 3_product — 고객 테스트 노트북"
echo "    경로: $ROOT"
echo ""

if ! command -v docker >/dev/null; then
  echo "Docker 필요: https://docs.docker.com/engine/install/"
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "docker compose v2 필요"
  exit 1
fi

ENV_FILE="$ROOT/.env"
if [[ ! -f "$ENV_FILE" ]]; then
  cp "$ROOT/.env.example" "$ENV_FILE"
  echo "Created $ENV_FILE"
fi

# shellcheck source=whick-cc-url.sh
source "$ROOT/scripts/whick-cc-url.sh"

CC_URL="$(grep -E '^WHICK_CC_API_URL=' "$ENV_FILE" 2>/dev/null | cut -d= -f2- || true)"
if [[ -z "$CC_URL" ]] || ! whick_cc_health_ok "$CC_URL" 3; then
  if CC_URL="$(whick_set_env_cc_url "$ENV_FILE" "$ROOT/.env.example")"; then
    echo "OK  CC API: $CC_URL"
    export WHICK_CC_API_URL="$CC_URL"
  fi
fi

CC_URL="${WHICK_CC_API_URL:-$(grep -E '^WHICK_CC_API_URL=' "$ENV_FILE" | cut -d= -f2-)}"
if [[ -z "$CC_URL" ]] || ! curl -sf --max-time 4 "${CC_URL%/}/system/health" >/dev/null; then
  echo ""
  echo "⚠ CC API (${CC_URL}) 에 연결되지 않습니다."
  echo "  본사 서버에서 CC가 떠 있는 상태에서, **다른 터미널**에 SSH 터널:"
  echo ""
  echo "    ssh -N -L 8090:127.0.0.1:8090 whick@ssh.whick.org"
  echo ""
  echo "  터널 후 이 스크립트를 다시 실행하세요."
  echo "  (또는 Wi-Fi에서 admin.whick.org 직접 연결 — ./install-whick.sh 원클릭)"
  exit 1
fi

mkdir -p "$ROOT/library/incoming"

echo "==> docker compose up"
docker compose --env-file "$ENV_FILE" up -d --build

sleep 4
echo ""
echo "==> 상태"
docker compose ps
echo ""
docker compose logs --tail=8 agent monitor audio
echo ""
echo "확인:"
echo "  curl -s http://127.0.0.1:8787/health"
echo "  docker exec whick-agent cat /var/lib/whick/runtime-state.json"
echo "  관제 UI: https://admin.whick.org/ (control.whick.org 아님)"
