#!/usr/bin/env bash
# USB 루트 — auto-install.sh 로 위임 (하위 호환)
set -euo pipefail
USB_ROOT="$(cd "$(dirname "$0")" && pwd)"
exec "$USB_ROOT/auto-install.sh" "$@"
