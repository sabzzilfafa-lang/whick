#!/usr/bin/env bash
# 터널 켠 뒤 runtime 기동
set -euo pipefail
ROOT="${WHICK_TARGET:-$HOME/whick-3_product}"
exec "$ROOT/scripts/laptop-test-setup.sh"
