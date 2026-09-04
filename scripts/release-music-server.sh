#!/usr/bin/env bash
# music-01 — 버전 bump · runtime 번들 빌드 · CC 등록
set -euo pipefail

CC="/data/whick-ai/2_control_center/scripts"
PRODUCT="$(cd "$(dirname "$0")/.." && pwd)"
PRODUCT_MAP="$PRODUCT/scripts/apply-product-map.py"
python3 "$PRODUCT_MAP" apply --scope sources
# shellcheck source=/dev/null
source "$CC/solution-version.sh"

CODE="music-01"
NO_BUMP=0
SKIP_BUNDLE=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-bump) NO_BUMP=1; shift ;;
    --skip-bundle) SKIP_BUNDLE=1; shift ;;
    *) echo "usage: $0 [--no-bump] [--skip-bundle]" >&2; exit 1 ;;
  esac
done

if [[ "$NO_BUMP" -eq 0 ]]; then
  VER="$(solution_version_bump "$CODE" "${WHICK_RELEASE_NOTES:-}")"
else
  VER="$(solution_version_field "$CODE" version)"
fi
solution_version_json "$CODE" set-build "$(kst_build_stamp)" >/dev/null

if [[ "$SKIP_BUNDLE" -eq 0 ]]; then
  chmod +x "$PRODUCT/scripts/build-docker-ce-deb-bundle.sh"
  "$PRODUCT/scripts/build-docker-ce-deb-bundle.sh"
  chmod +x "$PRODUCT/scripts/build-music-runtime-bundle.sh"
  "$PRODUCT/scripts/build-music-runtime-bundle.sh"
  BUNDLE="$(python3 -c "import json; print(json.load(open('/data/whick-ai/2_control_center/config/solutions/music-01.json'))['components']['runtime_bundle']['file'])")"
  DIST_DIR="${WHICK_MUSIC01_DIST:-$PRODUCT/dist/music-01}"
  python3 "$PRODUCT_MAP" verify --scope all
  "$CC/register-solution-cc.sh" "$CODE" "$DIST_DIR/$BUNDLE"
else
  python3 "$PRODUCT_MAP" apply --scope release
  python3 "$PRODUCT_MAP" verify --scope all
  "$CC/register-solution-cc.sh" "$CODE"
fi

python3 "$PRODUCT_MAP" apply --scope versions --version-id sales-remote-update-fallback
python3 "$PRODUCT_MAP" verify --scope versions --version-id sales-remote-update-fallback

echo "OK  music-01 ${VER} (pinned runtime bundle · offline install)"
