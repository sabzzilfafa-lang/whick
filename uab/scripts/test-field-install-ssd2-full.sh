#!/usr/bin/env bash
# 미니PC 필드 설치 사전 검증 — SSD2(/whick-lab) 전체 트랙
# 1) CC orchestrator USB→SSD→verify→complete (full virtual E2E)
# 2) prod runtime + local AI + library robots (SSD2 loop 직접 phase)
set -euo pipefail

SCRIPTS="$(cd "$(dirname "$0")" && pwd)"
SAFE="/data/whick-ai/7_ai_only/scripts/whick-lab-docker-safe.sh"
# shellcheck source=/dev/null
source "$SAFE"
_lab_field_teardown() {
  lab_teardown_or_fail
}
trap _lab_field_teardown EXIT
lab_assert_prod_infra || exit 1
lab_enforce_central_bind

echo "========================================"
echo " Field install SSD2 full validation"
echo " $(date -Is)"
echo "========================================"

echo ">>> [1/2] CC orchestrator path (USB sim → SSD → verify → complete)"
bash "/data/whick-ai/7_ai_only/scripts/test-full-virtual-install-lab-e2e-docker.sh"

echo ""
echo ">>> [2/2] SSD2 prod stack (runtime · player · local AI · robots)"
export WHICK_LAB_REBUILD_BUNDLE="${WHICK_LAB_REBUILD_BUNDLE:-0}"
export WHICK_LAB_SKIP_ROBOTS="${WHICK_LAB_SKIP_ROBOTS:-0}"
bash "$SCRIPTS/test-prod-install-lab-e2e-docker.sh"

echo ""
echo "OK  field install SSD2 full validation complete"
