#!/usr/bin/env bash
# 3_product → VIP Room 배포용 압축 (tar.gz)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAMP="$(date +%Y%m%d)"
OUT_DIR="${WHICK_3PRODUCT_DIST:-$ROOT/dist}"
OUT="$OUT_DIR/whick-3product-${STAMP}.tar.gz"
WORK="$(mktemp -d)"

cleanup() { rm -rf "$WORK"; }
trap cleanup EXIT

mkdir -p "$OUT_DIR" "$WORK/whick-3product"
rsync -a --delete \
  --exclude '.env' \
  --exclude 'library/incoming/*' \
  --exclude 'dist/' \
  --exclude '.git/' \
  "$ROOT/" "$WORK/whick-3product/"

chmod +x "$WORK/whick-3product/install-whick.sh" \
  "$WORK/whick-3product/extract-and-install.sh" \
  "$WORK/whick-3product/scripts/"*.sh 2>/dev/null || true

tar czf "$OUT" -C "$WORK" whick-3product
chmod 644 "$OUT"

"$ROOT/scripts/build-customer-deb.sh" >/dev/null

echo "OK  $OUT ($(du -h "$OUT" | cut -f1))"
echo "OK  $OUT_DIR/setup.deb (VIP 첨부 · 더블클릭 설치)"
echo "$OUT"
