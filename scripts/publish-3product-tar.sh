#!/usr/bin/env bash
# 3_product → whick.org HTTPS tar (노트북 dev_pull용)
# SSOT: 5_site/content/customer — site-web이 /mnt/customer-content 로 마운트
# (site-web/public/whick-content/customer 에 복사하지 말 것 — nginx가 5_site를 직접 서빙)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="${WHICK_CONTENT_DIR:-/data/whick-ai_music_server/5_site/content/customer}"
STAMP="$(date +%Y%m%d)"
ARCHIVE="whick-3product-${STAMP}.tar.gz"
LATEST="whick-3product-latest.tar.gz"
# agent/dev-ops.mjs 기본 URL 파일명 — 깨지면 미니PC가 HTML을 tar로 받아 복구 불능
PINNED="whick-3product-20260612-pullfix.tar.gz"
TMP="$(mktemp -d)"

cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

mkdir -p "$OUT_DIR"
echo "== pack 3_product → $OUT_DIR/$LATEST =="

COPY="$TMP/whick-3product"
mkdir -p "$COPY"
rsync -a \
  --exclude '.env' \
  --exclude '.git/' \
  --exclude 'library/incoming/*' \
  --exclude 'dist/' \
  --exclude 'node_modules/' \
  "$ROOT/" "$COPY/"

tar czf "$OUT_DIR/$ARCHIVE" -C "$TMP" whick-3product
cp -f "$OUT_DIR/$ARCHIVE" "$OUT_DIR/$LATEST"
cp -f "$OUT_DIR/$ARCHIVE" "$OUT_DIR/$PINNED"
ls -lh "$OUT_DIR/$LATEST" "$OUT_DIR/$PINNED"
# 서빙 경로 스모크 (로컬 site-web)
if curl -fsS --max-time 5 -o /dev/null -w '%{http_code} %{size_download}\n' \
  "http://127.0.0.1:8088/whick-content/customer/${PINNED}" 2>/dev/null | grep -qE '^200 [1-9]'; then
  echo "OK serve http://127.0.0.1:8088/whick-content/customer/${PINNED}"
else
  echo "WARN: site-web 미응답 또는 HTML/빈 응답 — docker compose up -d site-web 확인" >&2
fi
echo "Done — 노트북/에이전트 dev_pull 또는 laptop-dev-update.sh HTTPS fallback"
