#!/usr/bin/env bash
# remote.whick.org — static portal 재빌드·기동
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PRODUCT_ROOT="$(cd "$ROOT/../.." && pwd)"
BOUNDARY_GUARD="/data/whick-ai/2_control_center/scripts/guard-remote-ui-boundaries.py"

if [[ -x "$BOUNDARY_GUARD" ]]; then
  "$BOUNDARY_GUARD"
fi
"$PRODUCT_ROOT/scripts/guard-product-remote-separation.sh"

cd "$ROOT"

echo "[remote-portal] build + up"
docker compose build --pull=false remote-portal
docker compose up -d remote-portal

sleep 1
echo "[remote-portal] health"
curl -sf -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:8097/ || {
  echo "FAIL: portal not responding on :8097"
  exit 1
}

echo "[remote-portal] OK http://127.0.0.1:8097"
echo "Tunnel: remote.whick.org → 127.0.0.1:8097 (see 0_gateway/cloudflare/config.yml)"
