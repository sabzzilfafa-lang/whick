#!/usr/bin/env bash
# 고객 재설치 시뮬 — Docker·볼륨 전부 삭제 후 HTTPS로 다시 설치
#   curl -fsSL https://whick.org/whick-content/customer/laptop-sim-reinstall.sh | bash
#
# 동작:
#   · whick-runtime 컨테이너·볼륨·이미지 제거 → 관제 ● 잠깐 끊김 (1~5분)
#   · laptop-dev-update.sh 로 재설치 → agent 재등록 (hostname 같으면 device_id 유지)
#   · 본사 서버·Cloudflare(0_gateway) 는 건드리지 않음 — 아웃바운드 HTTPS만 사용
set -euo pipefail

ROOT="${WHICK_INSTALL_ROOT:-$HOME/whick-3product}"
UPDATE_URL="${WHICK_UPDATE_URL:-https://whick.org/whick-content/customer/laptop-dev-update.sh}"

echo "== Whick 재설치 시뮬 (USB+전원 고객 흐름 테스트) =="
echo "   관제 연결은 재설치 중 ● 끊김 → 완료 후 자동 복구"
echo ""

if [[ "${WHICK_SIM_CONFIRM:-}" != "yes" ]]; then
  echo "  Docker whick-runtime 전부 삭제 후 재설치합니다."
  echo "  계속: WHICK_SIM_CONFIRM=yes 로 다시 실행"
  echo ""
  echo "  WHICK_SIM_CONFIRM=yes curl -fsSL https://whick.org/whick-content/customer/laptop-sim-reinstall.sh | bash"
  exit 0
fi

command -v docker >/dev/null || { echo "NG Docker 없음"; exit 1; }

if [[ -f "$ROOT/compose.yaml" ]]; then
  echo "== [1] compose down -v =="
  docker compose -f "$ROOT/compose.yaml" down -v 2>/dev/null || true
fi

echo "== [2] whick 이미지·고아 볼륨 정리 =="
docker rm -f whick-agent whick-audio whick-monitor 2>/dev/null || true
docker rmi whick/agent:dev whick/audio:dev 2>/dev/null || true
docker volume rm whick-runtime_whick-data 2>/dev/null || true

echo "== [3] 재설치 (HTTPS) =="
curl -fsSL4 "$UPDATE_URL" | bash

echo ""
echo "== 완료 =="
echo "   관제 admin.whick.org → test-750XDA ● 확인 (1~2분)"
echo "   본사: remote-laptop-ops.sh pull 11 (online 후)"
