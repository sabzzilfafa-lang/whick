#!/usr/bin/env bash
# 집 PC에서 실행 — 본사 서버 3_product → 로컬 → (선택) 노트북 LAN
# Cursor는 서버 SSH 개발, 노트북에는 runtime 테스트용 복사본만 둠.
#
#   ./scripts/sync-from-server.sh
#   ./scripts/sync-from-server.sh whick@192.168.0.50:~/whick-3_product/
set -euo pipefail

SERVER="${WHICK_SERVER:-whick@ssh.whick.org}"
REMOTE="${WHICK_REMOTE_3PRODUCT:-/data/whick-ai_music_server/3_product/}"
LOCAL="${WHICK_LOCAL_3PRODUCT:-$HOME/whick-3_product}"
LAPTOP="${1:-}"

echo "==> rsync $SERVER:$REMOTE → $LOCAL"
mkdir -p "$LOCAL"
rsync -avz --delete \
  --exclude '.env' \
  --exclude 'library/incoming/*' \
  --exclude '.git/' \
  "$SERVER:$REMOTE" "$LOCAL/"

echo "OK  $LOCAL"

if [[ -n "$LAPTOP" ]]; then
  echo "==> rsync → $LAPTOP"
  rsync -avz --delete \
    --exclude '.env' \
    --exclude 'library/incoming/*' \
    "$LOCAL/" "$LAPTOP"
  echo "OK  노트북 동기화 — 노트북에서 ./scripts/laptop-first-boot.sh"
fi
