#!/usr/bin/env bash
# Whick 원클릭 설치 — 더블클릭 또는 터미널에서 실행
# 압축 해제 후 whick-3product 폴더에서 실행하세요.
ROOT="$(cd "$(dirname "$0")" && pwd)"
exec bash "$ROOT/scripts/whick-one-click-install.sh" "$@"
