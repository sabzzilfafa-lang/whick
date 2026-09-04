#!/usr/bin/env bash
# 미니PC HW 지문 수집 → /tmp/hw_raw.json · /tmp/hw_id_hash (메인보드 기준)
set -euo pipefail

OUT_RAW="${WHICK_HW_RAW:-/tmp/hw_raw.json}"
OUT_HASH="${WHICK_HW_HASH:-/tmp/hw_id_hash}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LIVE_LIB="$(cd "$SCRIPT_DIR/../lib" && pwd)"

python3 - "$LIVE_LIB" "$OUT_RAW" "$OUT_HASH" <<'PY'
import json, os, sys

sys.path.insert(0, sys.argv[1])
from hw_identity import resolve_hw_identity

out_raw, out_hash = sys.argv[2], sys.argv[3]
mb, hw_hash, scheme = resolve_hw_identity()
data = {
    "hostname": os.uname().nodename,
    "hw_id_scheme": scheme,
    "motherboard": mb,
    "hw_id_hash": hw_hash,
}
with open(out_raw, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
with open(out_hash, "w", encoding="utf-8") as f:
    f.write(hw_hash + "\n")
print(f"hw_id_hash={hw_hash}")
print(f"raw={out_raw}")
PY
