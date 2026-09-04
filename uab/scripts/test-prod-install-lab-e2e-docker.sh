#!/usr/bin/env bash
# privileged docker 래퍼 — whick 사용자 sudo 없이 SSD2 loop E2E
# CC·그누보드·터널 컨테이너 보호 (whick-lab-docker-safe.sh)
set -euo pipefail
SCRIPT="/data/whick-ai_music_server/3_product/uab/scripts/test-prod-install-lab-e2e.sh"
SAFE="/data/whick-ai/7_ai_only/scripts/whick-lab-docker-safe.sh"
LOG="/whick-lab/runs/lab-prod-e2e-latest.log"
mkdir -p /whick-lab/runs
# shellcheck source=/dev/null
source "$SAFE"
_lab_docker_teardown() {
  lab_teardown_or_fail
}
trap _lab_docker_teardown EXIT
lab_assert_prod_infra || {
  echo "ERROR: CC/그누보드 확인 후 SSD2 E2E 실행" >&2
  exit 1
}
lab_enforce_central_bind
docker run --rm --privileged \
  --pid=host \
  --network host \
  -v /dev:/dev \
  -v /whick-lab:/whick-lab \
  -v /mnt/music:/mnt/music:ro \
  -v /data/whick-ai_music_server:/data/whick-ai_music_server \
  -v /data/whick-ai:/data/whick-ai \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -e WHICK_VID_SECRET="${WHICK_VID_SECRET:-whick-cc-site-sync-dev}" \
  -e WHICK_VID_MB_ID="${WHICK_VID_MB_ID:-bkhkorea@gmail.com}" \
  -e WHICK_CC_API_URL="${WHICK_CC_API_URL:-http://127.0.0.1:8095/api/v1}" \
  -e WHICK_LAB_LOOP_GB="${WHICK_LAB_LOOP_GB:-256}" \
  -e WHICK_MUSIC_MIN_GB="${WHICK_MUSIC_MIN_GB:-10}" \
  -e WHICK_INSTALL_RESERVE_GB="${WHICK_INSTALL_RESERVE_GB:-64}" \
  -e WHICK_LOCAL_AI="${WHICK_LOCAL_AI:-0}" \
  -e WHICK_LAB_REBUILD_BUNDLE="${WHICK_LAB_REBUILD_BUNDLE:-0}" \
  -e WHICK_MUSIC01_DIST="${WHICK_MUSIC01_DIST:-/whick-lab/artifacts}" \
  -e WHICK_BOOTSTRAP_ROOTFS="${WHICK_BOOTSTRAP_ROOTFS:-}" \
  -e WHICK_PLAYER_PORT_BIND="${WHICK_PLAYER_PORT_BIND:-127.0.0.1:8080}" \
  ubuntu:resolute \
  bash -ce '
    set -euo pipefail
    export DEBIAN_FRONTEND=noninteractive
    echo "DEBUG: WHICK_CC_API_URL=$WHICK_CC_API_URL WHICK_VID_SECRET=${WHICK_VID_SECRET:0:10}..."
    apt-get update -qq
    apt-get install -y -qq python3 curl zstd parted e2fsprogs dosfstools grub-efi-amd64 xz-utils udev util-linux rsync
    apt-get install -y -qq docker.io docker-compose-v2 2>/dev/null || apt-get install -y -qq docker.io
    service docker start || true
    bash /data/whick-ai_music_server/3_product/uab/scripts/test-prod-install-lab-e2e.sh
  ' 2>&1 | tee "$LOG"
