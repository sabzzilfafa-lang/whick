#!/usr/bin/env bash
# 모바일 리모컨 (remote-mobile) — bump · deploy · CC
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CC="/data/whick-ai/2_control_center/scripts"
# shellcheck source=/dev/null
source "$CC/solution-version.sh"

CODE="remote-mobile"
NO_BUMP=0
SKIP_DEPLOY=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-bump) NO_BUMP=1; shift ;;
    --skip-deploy) SKIP_DEPLOY=1; shift ;;
    *) echo "usage: $0 [--no-bump] [--skip-deploy]" >&2; exit 1 ;;
  esac
done

PRODUCT_MAP="/data/whick-ai_music_server/3_product/scripts/apply-product-map.py"

if [[ "$NO_BUMP" -eq 0 ]]; then
  VER="$(solution_version_bump "$CODE" "${WHICK_RELEASE_NOTES:-}")"
else
  VER="$(solution_version_field "$CODE" version)"
fi
solution_version_json "$CODE" set-build "$(date +%Y%m%d%H)" >/dev/null
python3 "$PRODUCT_MAP" apply --scope versions --version-id remote-portal-ui
python3 "$PRODUCT_MAP" apply --scope versions --version-id sales-remote-ui-footer
python3 "$PRODUCT_MAP" verify --scope versions --version-id remote-portal-ui
python3 "$PRODUCT_MAP" verify --scope versions --version-id sales-remote-ui-footer

if [[ "$SKIP_DEPLOY" -eq 0 ]]; then
  "$ROOT/scripts/deploy-remote-portal.sh"
fi

"$CC/register-solution-cc.sh" "$CODE"
echo "OK  remote-mobile ${VER}"
