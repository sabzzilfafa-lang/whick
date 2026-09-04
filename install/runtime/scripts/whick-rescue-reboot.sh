#!/usr/bin/env bash
# DEPRECATED · REMOVED (2026-07-26)
# rescue 파티션 / 원격 system_reinstall 설계 폐기.
# 전체 재설치(OS) = VIP USB Live 만. 관제 = runtime_reinstall(Docker) 까지.
set -euo pipefail
echo "[whick-rescue-reboot] REMOVED: rescue partition path discarded." >&2
echo "Full OS reinstall: use VIP USB install package (USB Live)." >&2
echo "Docker-only: use CC runtime_reinstall." >&2
exit 2
