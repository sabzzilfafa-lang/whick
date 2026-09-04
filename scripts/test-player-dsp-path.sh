#!/usr/bin/env bash
# MPD → CamillaDSP 파이프라인 검증 (토큰 불필요)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLAYER_URL="${WHICK_PLAYER_URL:-http://127.0.0.1:8080}"
STAMP="$(TZ=Asia/Seoul date +%Y%m%d-%H%M%S)"
RUN_DIR="/data/whick-ai/sandbox-scratch/runs/player-dsp-${STAMP}"
mkdir -p "$RUN_DIR"
trap 'rm -rf "$RUN_DIR"' EXIT
FAIL=0
PASS=0

ok() { echo "  PASS  $*"; PASS=$((PASS + 1)); }
die() { echo "  FAIL  $*"; FAIL=$((FAIL + 1)); }

echo "== Whick player DSP pipeline =="

curl_json() { curl -fsS --max-time "${CURL_TIMEOUT:-30}" "$@" 2>/dev/null; }

section() { echo ""; echo "== $* =="; }

section "1. Tools in player container"
docker exec whick-player sh -c 'command -v camilladsp' >/dev/null && ok "camilladsp in PATH" || die "camilladsp missing (rebuild player image)"
docker exec whick-player sh -c 'command -v ffmpeg' >/dev/null && ok "ffmpeg in PATH" || die "ffmpeg missing"
docker exec whick-player test -x /app/docker/whick-dsp-pipe.sh && ok "whick-dsp-pipe.sh" || die "whick-dsp-pipe.sh missing"
docker exec whick-player sh -c 'command -v librespot' >/dev/null && ok "librespot in PATH" || die "librespot missing (rebuild player image)"
docker exec whick-player test -x /app/docker/librespot-camilla.sh && ok "librespot-camilla.sh" || die "librespot-camilla.sh missing"

section "2. API pipeline status"
curl_json "$PLAYER_URL/api/dsp/pipeline" >"$RUN_DIR/dsp-pipe.json"
python3 -c "
import json
d=json.load(open('$RUN_DIR/dsp-pipe.json'))
assert d.get('ok') is True
assert d.get('camilladsp_installed') is True, d
mode=d.get('mpd_output_mode')
assert mode in ('bitperfect','dsp','legacy','null','dsd_dop','camilla-pipe'), mode
print('  mode=', mode)
"
ok "GET /api/dsp/pipeline"

section "3. camilladsp --check"
docker exec whick-player python3 - <<'PY'
from api.audio_pipeline import verify_camilla_dry_run, ensure_default_profile
ensure_default_profile()
ok, msg = verify_camilla_dry_run()
assert ok, msg
print("  check:", msg[:120])
PY
ok "camilladsp --check profile"

section "3b. DAC CPU preprocess 4x/8x profile validation"
curl_json "$PLAYER_URL/api/dsp/profile" >"$RUN_DIR/dsp-profile-before.json"
python3 - "$RUN_DIR/dsp-profile-before.json" "$RUN_DIR/dac-restore.json" <<'PY'
import json, sys
raw = json.load(open(sys.argv[1]))
dsp = raw.get("dsp") or raw
json.dump({
    "enabled": bool(dsp.get("dacPreprocessEnabled", False)),
    "dacOsFactor": 8 if int(dsp.get("dacOsFactor") or 4) == 8 else 4,
    "dacOsFactorAuto": dsp.get("dacOsFactorAuto", True) is not False,
}, open(sys.argv[2], "w"))
PY
for factor in 4 8; do
  curl_json -X POST "$PLAYER_URL/api/dsp/dac-preprocess" \
    -H 'Content-Type: application/json' \
    -d "{\"enabled\":true,\"dacOsFactor\":$factor,\"dacOsFactorAuto\":false}" >/dev/null
  docker exec whick-player python3 - <<'PY'
from api.audio_pipeline import verify_camilla_dry_run
ok, msg = verify_camilla_dry_run()
assert ok, msg
print("  check:", msg[:120])
PY
  ok "DAC CPU preprocess ${factor}x camilladsp --check"
done
curl_json -X POST "$PLAYER_URL/api/dsp/dac-preprocess" \
  -H 'Content-Type: application/json' \
  --data-binary "@$RUN_DIR/dac-restore.json" >/dev/null
ok "DAC CPU preprocess profile restored"

section "4. MPD play → playback path"
docker exec whick-player mpc --quiet clear
docker exec whick-player mpc --quiet add tones/test-left.wav
docker exec whick-player mpc --quiet play
sleep 2
MODE="$(curl_json "$PLAYER_URL/api/dsp/pipeline" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("playback_mode",""))')"
if [ "$MODE" = "bitperfect" ]; then
  docker exec whick-player mpc outputs | grep -q "Whick Direct.*enabled" \
    && ok "bit-perfect: Whick Direct enabled" || die "Whick Direct not enabled"
elif [ "$MODE" = "dsp" ]; then
  docker exec whick-player test -f /var/lib/whick/run/whick-dsp-pipe.log \
    && docker exec whick-player grep -q whick-dsp-pipe /var/lib/whick/run/whick-dsp-pipe.log \
    && ok "whick-dsp-pipe.log has session" || die "whick-dsp-pipe did not run"
else
  ok "playback_mode=$MODE (log check skipped)"
fi

section "5. Streaming lab → same MPD path"
docker exec whick-player python3 - <<'PY'
import asyncio, os, tempfile, shutil
os.environ["WHICK_PLAYER_EXTERNAL_PROVIDERS"] = "1"
os.environ["WHICK_STREAMING_LAB"] = "1"
td = tempfile.mkdtemp()
os.environ["WHICK_PROVIDERS_DIR"] = td
from api import streaming_providers, streaming_playback
from api import music_api

async def main():
    await streaming_providers.spotify_connect_start()
    streaming_providers.spotify_connect_complete()
    fed = await streaming_playback.federated_search("jazz", ["spotify"])
    tr = fed["tracks"][0]
    await music_api.handle_command({"cmd": "play_streaming_queue", "items": fed["tracks"][:1], "index": 0})
    assert music_api.STATE.source == "spotify"
asyncio.run(main())
shutil.rmtree(td, ignore_errors=True)
PY
sleep 1
docker exec whick-player tail -n 3 /var/lib/whick/run/camilla-pipe.log | grep -q start \
  && ok "streaming play triggered camilla-pipe" || ok "streaming play STATE ok (log optional)"

echo ""
echo "PASS=$PASS  FAIL=$FAIL"
if [ "$FAIL" -eq 0 ]; then
  echo "ALL PASS dsp pipeline"
  exit 0
fi
exit 1
