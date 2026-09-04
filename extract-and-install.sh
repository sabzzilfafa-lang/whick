#!/usr/bin/env bash
# Downloads 등에 tar.gz 와 함께 두고 실행 — 압축 해제 + 원클릭 설치
# Usage: bash extract-and-install.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

ARCHIVE="$(ls -1 whick-3product-*.tar.gz 2>/dev/null | sort -r | head -1 || true)"
if [[ -z "$ARCHIVE" ]]; then
  echo "ERROR: whick-3product-*.tar.gz 가 이 폴더에 없습니다." >&2
  echo "VIP Room 공지에서 패키지를 받은 뒤, 이 스크립트와 같은 폴더에 두세요." >&2
  exit 1
fi

echo "==> 압축 해제: $ARCHIVE"
tar xzf "$ARCHIVE"
TARGET="$HERE/whick-3product"
if [[ ! -d "$TARGET" ]]; then
  echo "ERROR: whick-3product 폴더가 생성되지 않았습니다." >&2
  exit 1
fi

chmod +x "$TARGET/install-whick.sh" "$TARGET/scripts/"*.sh 2>/dev/null || true
exec "$TARGET/install-whick.sh"
