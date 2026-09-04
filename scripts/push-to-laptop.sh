#!/usr/bin/env bash
# 본사 서버(Cursor) → 테스트 노트북 원격 배포 (VIP tar 다운로드 불필요)
#
#   export WHICK_LAPTOP=test@192.168.0.50    # 노트북 IP·계정 (한 번만)
#   ./scripts/push-to-laptop.sh
#   ./scripts/push-to-laptop.sh --install     # rsync + whick-one-click-install
#
# 노트북: openssh-server · whick@ 또는 test@ 로그인 가능해야 함
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LAPTOP="${WHICK_LAPTOP:-}"
REMOTE_DIR="${WHICK_LAPTOP_DIR:-~/whick-3product}"
DO_INSTALL=0

for arg in "$@"; do
  case "$arg" in
    --install) DO_INSTALL=1 ;;
    -h|--help)
      cat <<EOF
Usage: WHICK_LAPTOP=user@IP ./scripts/push-to-laptop.sh [--install]

  rsync 3_product 소스 → 노트북
  --install  whick-one-click-install.sh 까지 원격 실행 (sudo·Docker 필요)

노트북 SSH 예:
  sudo apt install -y openssh-server
  ip -4 addr   # IP 확인 → WHICK_LAPTOP=test@192.168.x.x
EOF
      exit 0
      ;;
  esac
done

[[ -n "$LAPTOP" ]] || {
  echo "WHICK_LAPTOP=user@IP 를 설정하세요." >&2
  echo "  예: export WHICK_LAPTOP=test@192.168.0.50" >&2
  exit 1
}

echo "==> probe SSH $LAPTOP"
ssh -o BatchMode=yes -o ConnectTimeout=8 "$LAPTOP" 'echo OK host=$(hostname)'

echo "==> rsync $ROOT → $LAPTOP:$REMOTE_DIR"
ssh "$LAPTOP" "mkdir -p $REMOTE_DIR"
rsync -avz --delete \
  --exclude '.env' \
  --exclude 'library/incoming/*' \
  --exclude 'dist/' \
  --exclude '.git/' \
  "$ROOT/" "$LAPTOP:$REMOTE_DIR/"

echo "==> remote: docker compose build agent (and up)"
ssh "$LAPTOP" bash -lc "
  set -e
  cd $REMOTE_DIR
  chmod +x scripts/*.sh install-whick.sh 2>/dev/null || true
  if ! command -v docker >/dev/null; then
    echo 'Docker 없음 — laptop-first-boot.sh 먼저 실행 필요'
    exit 1
  fi
  grep -q '^WHICK_CC_API_URL=' .env 2>/dev/null || cp .env.example .env
  if ! grep -q 'admin.whick.org' .env 2>/dev/null; then
    sed -i 's|^WHICK_CC_API_URL=.*|WHICK_CC_API_URL=https://admin.whick.org/api/v1|' .env || \
      echo 'WHICK_CC_API_URL=https://admin.whick.org/api/v1' >> .env
  fi
  docker compose build agent
  docker compose up -d agent
  sleep 3
  docker logs --tail=15 whick-agent
"

if [[ "$DO_INSTALL" == "1" ]]; then
  echo "==> remote: full one-click install"
  ssh "$LAPTOP" bash -lc "
    export WHICK_INSTALL_ROOT=$REMOTE_DIR
    export WHICK_SCRIPTS_DIR=$REMOTE_DIR/scripts
    export WHICK_SKIP_END_PAUSE=1
    bash $REMOTE_DIR/scripts/whick-one-click-install.sh
  "
fi

echo ""
echo "OK  pushed to $LAPTOP:$REMOTE_DIR"
echo "    logs: ssh $LAPTOP 'docker logs -f whick-agent'"
