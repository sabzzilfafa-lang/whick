#!/usr/bin/env bash
# 본사 CC API (8090) → 노트북 localhost:8090
# 이 터미널을 닫지 마세요.
set -euo pipefail

HOST="${WHICK_SSH_HOST:-whick@ssh.whick.org}"
LOCAL_PORT="${WHICK_CC_LOCAL_PORT:-8090}"
REMOTE_PORT="${WHICK_CC_REMOTE_PORT:-8090}"

echo "==> SSH 터널 (유지)"
echo "    localhost:${LOCAL_PORT} → ${HOST} 127.0.0.1:${REMOTE_PORT}"
echo "    종료: Ctrl+C"
echo ""

exec ssh -N -L "${LOCAL_PORT}:127.0.0.1:${REMOTE_PORT}" "$HOST"
