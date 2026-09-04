#!/usr/bin/env bash
# DAC capability 자동 감지 · playback 모드 스모크 (DAC 없어도 PASS)
set -euo pipefail

PLAYER_URL="${WHICK_PLAYER_URL:-http://127.0.0.1:8080}"
PASS=0
FAIL=0
ok() { echo "  PASS  $*"; PASS=$((PASS + 1)); }
die() { echo "  FAIL  $*"; FAIL=$((FAIL + 1)); }

echo "== Whick DAC detect + playback =="

section() { echo ""; echo "== $* =="; }

section "1. detect_dac_capability (in container)"
docker exec whick-player python3 - <<'PY'
from api.dac_detect import detect_dac_capability
cap = detect_dac_capability(save=True)
assert cap.get("pcm_max_sample_rate"), cap
print("  source=", cap.get("source"), "rate=", cap.get("pcm_max_sample_rate"))
PY
ok "detect_dac_capability"

section "2. MPD conf dop flag"
docker exec whick-player grep -q 'dop' /etc/mpd.conf && ok "mpd.conf has dop" || die "mpd.conf missing dop"

section "3. API detect endpoint"
curl -fsS -X POST "$PLAYER_URL/api/dac/capability/detect" >/tmp/dac-detect.json
python3 -c "
import json
d=json.load(open('/tmp/dac-detect.json'))
assert d.get('ok') is True
assert 'capability' in d
print('  dop=', d['capability'].get('dop'))
"
ok "POST /api/dac/capability/detect"

section "4. playback modules"
docker exec whick-player python3 -c "
from api.dsd_playback import dsd_playback_plan, dop_wrapper_rate, dsd_format_from_rate, DSD64_RATE, DSD128_RATE
from api.playback_fade import read_last_playback
assert dsd_format_from_rate(DSD64_RATE) == 'DSD64'
assert dsd_format_from_rate(DSD128_RATE) == 'DSD128'
p = dsd_playback_plan('/tmp/x.dsf', raw_sample_rate=DSD128_RATE)
assert p['dsd_format'] == 'DSD128'
assert dop_wrapper_rate('DSD64') == 176400
assert dop_wrapper_rate('DSD128') == 352800
"
ok "dsd_playback + playback_fade imports"

echo ""
echo "PASS=$PASS  FAIL=$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
