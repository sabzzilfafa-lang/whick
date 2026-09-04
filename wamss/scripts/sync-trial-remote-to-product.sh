#!/usr/bin/env bash
set -euo pipefail

cat >&2 <<'EOF'
ERROR: trial-to-product synchronization is permanently disabled.

3_product/packages/remote is the independent production SSOT.
Do not copy, sync, import, symlink, or hardlink trial site-web sources into it.
Make production changes directly in packages/remote and validate them with:

  3_product/scripts/guard-product-remote-separation.sh
EOF

exit 1
