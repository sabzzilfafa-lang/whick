#!/bin/sh
# HW ID SSOT — Bugbot fixes 회귀 테스트
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
API="/data/whick-ai/2_control_center/api"
PASS=0
FAIL=0

ok() { PASS=$((PASS + 1)); printf '  PASS  %s\n' "$1"; }
ng() { FAIL=$((FAIL + 1)); printf '  FAIL  %s\n' "$1"; }

section() { printf '\n== %s ==\n' "$1"; }

section "Node installMotherboardHwId"
if node --input-type=module <<'NODE'
import {
  resolveHwIdFromFingerprint,
  computeMotherboardHwIdHash,
  HW_ID_SCHEME,
} from '/data/whick-ai/2_control_center/api/src/lib/installMotherboardHwId.js';

const oemOnly = {
  motherboard: {
    manufacturer: 'To Be Filled By O.E.M.',
    product: 'Default string',
    serial: 'To Be Filled By O.E.M.',
    uuid: '00000000-0000-0000-0000-000000000000',
  },
  identity_source: 'motherboard',
};
const oemRes = resolveHwIdFromFingerprint(oemOnly);
if (oemRes.hwIdHash) throw new Error('OEM-only raw must not produce hash');

const good = {
  motherboard: {
    manufacturer: 'ASUSTeK COMPUTER INC.',
    product: 'H610M-E',
    uuid: '12345678-1234-1234-1234-123456789abc',
  },
  identity_source: 'motherboard',
};
const goodRes = resolveHwIdFromFingerprint(good);
const expect = computeMotherboardHwIdHash(
  {
    manufacturer: 'ASUSTeK COMPUTER INC.',
    product: 'H610M-E',
    uuid: '12345678-1234-1234-1234-123456789abc',
  },
  HW_ID_SCHEME,
);
if (goodRes.hwIdHash !== expect) throw new Error(`hash mismatch ${goodRes.hwIdHash} != ${expect}`);

const trust = resolveHwIdFromFingerprint({}, 'a'.repeat(64));
if (trust.hwIdHash) throw new Error('client_hash_only fallback must be removed');

console.log('node ok');
NODE
then
  ok "Node OEM reject + no client hash trust"
else
  ng "Node installMotherboardHwId tests"
fi

section "Python hw_identity server raw"
if python3 <<PY
import sys
sys.path.insert(0, "$ROOT/boot-connect")
from hw_identity import (
    _raw_usable_for_server,
    _clean_raw_for_server,
    compute_hw_id_hash,
    HW_ID_SCHEME,
    collect_dmi_raw_for_server,
)

oem = {
    "manufacturer": "To Be Filled By O.E.M.",
    "product": "Default string",
    "serial": "To Be Filled By O.E.M.",
    "uuid": "00000000-0000-0000-0000-000000000000",
}
assert not _raw_usable_for_server("motherboard", oem), "OEM-only must be unusable"

mixed = {
    "manufacturer": "ASUSTeK COMPUTER INC.",
    "product": "H610M-E",
    "serial": "To Be Filled By O.E.M.",
}
assert _raw_usable_for_server("motherboard", mixed), "valid fields with OEM serial must pass"

clean = _clean_raw_for_server("motherboard", {
    "manufacturer": "ASUSTeK COMPUTER INC.",
    "product": "H610M-E",
    "uuid": "12345678-1234-1234-1234-123456789abc",
})
h = compute_hw_id_hash(clean, HW_ID_SCHEME)
assert len(h) == 64

# degraded: OEM serial allowed in raw but strict path rejects
assert _raw_usable_for_server("degraded", {"serial": "To Be Filled By O.E.M.", "product": "X"})

print("python ok")
PY
then
  ok "Python raw usable + OEM filter"
else
  ng "Python hw_identity tests"
fi

section "Python ↔ Node hash parity"
if python3 <<'PY' && node --input-type=module <<'NODE'
import json, sys
sys.path.insert(0, "/data/whick-ai_music_server/3_product/uab/boot-connect")
from hw_identity import _clean_raw_for_server, compute_hw_id_hash, HW_ID_SCHEME
ident = _clean_raw_for_server("motherboard", {
    "manufacturer": "ASUSTeK COMPUTER INC.",
    "product": "H610M-E",
    "uuid": "12345678-1234-1234-1234-123456789abc",
})
print(json.dumps({"hash": compute_hw_id_hash(ident, HW_ID_SCHEME)}))
PY
import { computeMotherboardHwIdHash, HW_ID_SCHEME } from '/data/whick-ai/2_control_center/api/src/lib/installMotherboardHwId.js';
const ident = {
  manufacturer: 'ASUSTeK COMPUTER INC.',
  product: 'H610M-E',
  uuid: '12345678-1234-1234-1234-123456789abc',
};
console.log(JSON.stringify({ hash: computeMotherboardHwIdHash(ident, HW_ID_SCHEME) }));
NODE
then
  PY_HASH=$(python3 -c "
import sys
sys.path.insert(0, '$ROOT/boot-connect')
from hw_identity import _clean_raw_for_server, compute_hw_id_hash, HW_ID_SCHEME
ident = _clean_raw_for_server('motherboard', {
    'manufacturer': 'ASUSTeK COMPUTER INC.',
    'product': 'H610M-E',
    'uuid': '12345678-1234-1234-1234-123456789abc',
})
print(compute_hw_id_hash(ident, HW_ID_SCHEME))
")
  NODE_HASH=$(node --input-type=module -e "
import { computeMotherboardHwIdHash, HW_ID_SCHEME } from '$API/src/lib/installMotherboardHwId.js';
console.log(computeMotherboardHwIdHash({
  manufacturer: 'ASUSTeK COMPUTER INC.',
  product: 'H610M-E',
  uuid: '12345678-1234-1234-1234-123456789abc',
}, HW_ID_SCHEME));
")
  if [ "$PY_HASH" = "$NODE_HASH" ]; then
    ok "Python/Node hash parity ($PY_HASH)"
  else
    ng "hash mismatch py=$PY_HASH node=$NODE_HASH"
  fi
else
  ng "parity run failed"
fi

section "dmidecode timeout constant"
grep -q 'DMI_CMD_TIMEOUT_SEC' "$ROOT/boot-connect/hw_identity.py" \
  && grep -q '_run_dmidecode' "$ROOT/boot-connect/hw_identity.py" \
  && ok "dmidecode timeout wrapper" || ng "missing dmidecode timeout"

grep -q 'hw_report_required' "$API/src/lib/installLink.js" \
  && ok "link hw_report_required flag" || ng "missing hw_report_required"

grep -q 'server_hw_skip' "$ROOT/boot-connect/whick-boot-connect.sh" \
  && ok "boot-connect server skip sync" || ng "missing server skip sync"

! grep -q 'client_hash_only' "$API/src/lib/installMotherboardHwId.js" \
  && ok "no client_hash_only in server" || ng "client_hash_only still present"

printf '\n== SUMMARY ==\n\nPASS=%s  FAIL=%s\n\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
echo "OK  hw-id verify"
