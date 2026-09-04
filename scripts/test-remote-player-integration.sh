#!/usr/bin/env bash
# 모바일 리모컨 ↔ 뮤직플레이어 연동 — 채널 설정·테스트톤·공간음향·DSP
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAMP="$(TZ=Asia/Seoul date +%Y%m%d-%H%M%S)"
RUN_DIR="/data/whick-ai/sandbox-scratch/runs/remote-player-${STAMP}"
LOG="$RUN_DIR/test.log"
FAIL=0
PLAYER_URL="${WHICK_PLAYER_URL:-http://127.0.0.1:8080}"

mkdir -p "$RUN_DIR"
die() { echo "  FAIL  $*" | tee -a "$LOG"; FAIL=$((FAIL + 1)); }
ok()  { echo "  PASS  $*" | tee -a "$LOG"; }
section() { echo "" | tee -a "$LOG"; echo "== $* ==" | tee -a "$LOG"; }

section "Remote ↔ player integration"
echo "log=$LOG url=$PLAYER_URL" | tee -a "$LOG"

section "1. Mobile SSOT — speaker setup before room correction"
grep -q "phase = 'speakers'" "$ROOT/packages/remote/js/whick-spatial-wizard.js" && ok "wizard starts at speakers phase" || die "speakers phase missing"
grep -q 'renderSpeakers' "$ROOT/packages/remote/js/whick-spatial-wizard.js" && ok "renderSpeakers UI" || die "renderSpeakers missing"
grep -q 'saveChannelSetup' "$ROOT/packages/remote/js/remote_api.js" && ok "remote_api saveChannelSetup" || die "saveChannelSetup missing"
grep -q 'setOutputMode' "$ROOT/packages/remote/js/remote_api.js" && ok "remote_api setOutputMode" || die "setOutputMode missing"
grep -q 'sec-speaker' "$ROOT/packages/remote/index.html" && ok "settings speaker select UI" || die "speaker UI missing"
grep -q 'playTestTone' "$ROOT/packages/remote/js/remote_api.js" && ok "remote_api playTestTone" || die "playTestTone missing"

section "2. Player health"
curl -fsS "$PLAYER_URL/health" >/tmp/whick-rp-health.json || die "health unreachable"
python3 -c "import json; d=json.load(open('/tmp/whick-rp-health.json')); assert d.get('status')=='ok'"
ok "/health"

section "3. Channel setup API (L/R swap)"
curl -fsS -X POST "$PLAYER_URL/api/dsp/channel-setup" \
  -H 'Content-Type: application/json' \
  -d '{"swapChannels":true}' >/tmp/whick-rp-ch.json
python3 >>"$LOG" 2>&1 <<'PY'
import json
d = json.load(open("/tmp/whick-rp-ch.json"))
assert d.get("ok") is True
dsp = (d.get("dsp") or {})
assert dsp.get("swapChannels") is True
yaml = d.get("camillaYaml") or ""
assert "whick_swap_lr" in yaml, yaml
PY
ok "POST /api/dsp/channel-setup swap=true"

curl -fsS -X POST "$PLAYER_URL/api/dsp/channel-setup" \
  -H 'Content-Type: application/json' \
  -d '{"swapChannels":false}' >/tmp/whick-rp-ch0.json
python3 -c "import json; d=json.load(open('/tmp/whick-rp-ch0.json')); assert d['dsp']['swapChannels'] is False; assert 'whick_swap_lr' not in (d.get('camillaYaml') or '')"
ok "POST /api/dsp/channel-setup swap=false"

section "4. Test tone API"
curl -fsS -X POST "$PLAYER_URL/api/dsp/channel-setup" \
  -H 'Content-Type: application/json' \
  -d '{"swapChannels":false}' >/dev/null
curl -fsS -X POST "$PLAYER_URL/api/spatial/test-tone" \
  -H 'Content-Type: application/json' \
  -d '{"channel":"left"}' | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('channel')=='left'"
ok "POST /api/spatial/test-tone left"
docker exec whick-player bash -c 'sleep 0.3; mpc playlist' | grep -q 'tones/test-left.wav' && ok "MPD queued test-left.wav" || die "MPD test-left missing"
curl -fsS -X POST "$PLAYER_URL/api/spatial/test-tone" \
  -H 'Content-Type: application/json' \
  -d '{"channel":"left","swapChannels":true}' >/dev/null
docker exec whick-player bash -c 'sleep 0.3; mpc playlist' | grep -q 'tones/test-right.wav' && ok "test-tone preview swapChannels" || die "swap preview failed"
curl -fsS -X POST "$PLAYER_URL/api/spatial/test-tone" \
  -H 'Content-Type: application/json' \
  -d '{"channel":"right"}' | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('channel')=='right'"
ok "POST /api/spatial/test-tone right"

section "4b. Audio DSP reload reads Camilla swap"
cd "$ROOT"
docker compose -f compose.yaml up -d audio >>"$LOG" 2>&1 || true
sleep 2
curl -fsS -X POST "$PLAYER_URL/api/dsp/channel-setup" \
  -H 'Content-Type: application/json' \
  -d '{"swapChannels":true}' >/dev/null
curl -fsS -X POST 'http://127.0.0.1:8787/dsp/reload' | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('swapChannels') is True"
ok "audio /dsp/reload sees swapChannels"

section "5. Room correction preserves swapChannels"
curl -fsS -X POST "$PLAYER_URL/api/dsp/channel-setup" \
  -H 'Content-Type: application/json' \
  -d '{"swapChannels":true}' >/dev/null
curl -fsS -X POST "$PLAYER_URL/api/dsp/room-correction" \
  -H 'Content-Type: application/json' \
  -d '{"peaking":[{"freq":100,"q":1.1,"gainDb":-1.5}]}' >/tmp/whick-rp-rc.json
python3 -c "import json; d=json.load(open('/tmp/whick-rp-rc.json')); assert d['dsp']['swapChannels'] is True; assert 'whick_swap_lr' in (d.get('camillaYaml') or '')"
ok "room-correction keeps swapChannels"

section "6. Spatial state + WebSocket cmd"
curl -fsS "$PLAYER_URL/api/spatial/state" | python3 -c "import json,sys; d=json.load(sys.stdin); assert 'phase' in d"
ok "GET /api/spatial/state"

docker exec whick-player python3 >>"$LOG" 2>&1 <<'PY'
import asyncio, json, websockets

async def main():
    async with websockets.connect("ws://127.0.0.1:8080/ws", open_timeout=8) as ws:
        await ws.recv()
        await ws.recv()
        await ws.send(json.dumps({"cmd": "spatial_test_tone", "channel": "left"}))
        await asyncio.sleep(0.5)
        await ws.send(json.dumps({"cmd": "spatial_reset"}))
        await asyncio.sleep(0.3)

asyncio.run(main())
PY
ok "WebSocket spatial_test_tone + reset"

section "7. Camilla yaml unit"
PYTHONPATH="$ROOT/remote/api:$ROOT/remote" python3 >>"$LOG" 2>&1 <<'PY'
from api.camilla_yaml import full_camilla_config

on = full_camilla_config({"enabled": True, "swapChannels": True, "peaking": []})
assert "whick_swap_lr" in on
off = full_camilla_config({"enabled": True, "swapChannels": False, "peaking": [{"freq": 80, "q": 1, "gainDb": -2}]})
assert "whick_swap_lr" not in off
assert "whick_eq_0" in off
PY
ok "camilla_yaml swap mixer"

section "8. Spectrum WebSocket (MPD fifo → FFT)"
docker exec whick-player python3 >>"$LOG" 2>&1 <<'PY'
import asyncio, json, urllib.request, websockets

async def main():
    req = urllib.request.Request(
        "http://127.0.0.1:8080/api/spatial/test-tone",
        data=b'{"channel":"left"}',
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(req, timeout=10)
    async with websockets.connect("ws://127.0.0.1:8080/ws", open_timeout=10) as ws:
        await ws.recv()
        await ws.recv()
        for _ in range(50):
            raw = await asyncio.wait_for(ws.recv(), timeout=3)
            msg = json.loads(raw)
            if msg.get("event") != "spectrum":
                continue
            bands = msg.get("bands") or []
            assert len(bands) >= 16, bands
            if max(bands) > 0.03:
                return
    raise AssertionError("spectrum energy not received")

asyncio.run(main())
PY
ok "WebSocket spectrum from mini PC"

PYTHONPATH="$ROOT/remote/api:$ROOT/remote" python3 >>"$LOG" 2>&1 <<'PY'
from api.spectrum_engine import analyze_pcm, BAND_COUNT

pcm = b""
for i in range(2048):
    import math, struct
    v = int(12000 * math.sin(2 * math.pi * 440 * i / 44100))
    pcm += struct.pack("<hh", v, v)
bands = analyze_pcm(pcm, prev=[0.0] * BAND_COUNT)
assert max(bands) > 0.2, bands
PY
ok "spectrum_engine unit"

section "9. Speaker output (mobile stream endpoints)"
curl -fsS "$PLAYER_URL/api/radio/kbs-1fm/stream" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('stream_url','').startswith('http')"
ok "GET /api/radio stream (mobile output)"
tid=$(curl -fsS "$PLAYER_URL/api/tracks?per_page=1" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['tracks'][0]['track_id'])")
code=$(curl -sS -o /dev/null -w '%{http_code}' "$PLAYER_URL/api/tracks/$tid/stream")
[[ "$code" == "200" ]] && ok "GET /api/tracks/{id}/stream" || die "track stream HTTP $code"
docker exec whick-player python3 >>"$LOG" 2>&1 <<PY
import asyncio, json, urllib.request, websockets

async def main():
    tracks = json.loads(urllib.request.urlopen("http://127.0.0.1:8080/api/tracks?per_page=1").read())
    tid = tracks["tracks"][0]["track_id"]
    async with websockets.connect("ws://127.0.0.1:8080/ws", open_timeout=10) as ws:
        await ws.recv()
        await ws.recv()
        await ws.send(json.dumps({"cmd": "play", "track_id": tid, "output": "mobile"}))
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert msg.get("event") == "state"
        assert msg.get("playing") is True
        assert msg.get("track_id") == tid

asyncio.run(main())
PY
ok "WS play output=mobile (state only)"
curl -fsS "$PLAYER_URL/api/playback/now" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('source') in ('library','radio','idle'), d
if d.get('source')=='library':
    assert d.get('stream_url','').startswith('/api/tracks/')
"
ok "GET /api/playback/now"

if [[ "$FAIL" -eq 0 ]]; then
  echo "ALL PASS remote-player ($LOG)" | tee -a "$LOG"
  exit 0
fi
echo "FAILED ($FAIL) — $LOG" | tee -a "$LOG"
exit 1
