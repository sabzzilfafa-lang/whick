#!/usr/bin/env bash
# 고객 뮤직서버 Docker player — test-player-full.sh 래퍼 (dev 샘플)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export WHICK_PLAYER_DEV_SAMPLES="${WHICK_PLAYER_DEV_SAMPLES:-1}"
exec "$ROOT/scripts/test-player-full.sh" "$@"
