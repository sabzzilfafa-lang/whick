#!/usr/bin/env bash
# 뮤직 플레이어 전 기능 — 고객 설정(샘플 없음) + dev 샘플 재생·AI
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAMP="$(TZ=Asia/Seoul date +%Y%m%d-%H%M%S)"
RUN_DIR="/data/whick-ai/sandbox-scratch/runs/player-full-${STAMP}"
LOG="$RUN_DIR/test.log"
FAIL=0
PLAYER_URL="${WHICK_PLAYER_URL:-http://127.0.0.1:8080}"
DEV_SAMPLES="${WHICK_PLAYER_DEV_SAMPLES:-1}"

mkdir -p "$RUN_DIR"
die() { echo "  FAIL  $*" | tee -a "$LOG"; FAIL=$((FAIL + 1)); }
ok()  { echo "  PASS  $*" | tee -a "$LOG"; }
section() { echo "" | tee -a "$LOG"; echo "== $* ==" | tee -a "$LOG"; }

compose_files() {
  local -n out=$1
  out=(-f "$ROOT/compose.yaml")
  if [[ "$DEV_SAMPLES" == "1" ]]; then
    out+=(-f "$ROOT/compose.override.dev.yaml")
  fi
}

section "Whick player full feature test"
echo "log=$LOG dev_samples=$DEV_SAMPLES" | tee -a "$LOG"

section "0. Customer install SSOT (no sample FLAC)"
grep -q 'WHICK_PLAYER_PORT_BIND=127.0.0.1:8080' "$ROOT/.env.example" && ok "localhost port bind in .env.example" || die ".env.example port bind"
! grep -q 'WHICK_SAMPLE_AUDIO' "$ROOT/.env.example" && ok "no sample path in .env.example" || die ".env.example has sample path"
grep -q 'library/music' "$ROOT/.env.example" && ok "customer music scan path" || die ".env.example scan path"
! grep -q 'samples/flac' "$ROOT/compose.yaml" && ok "compose.yaml no sample mount" || die "compose.yaml sample mount"

section "1. Build & start player"
cd "$ROOT"
CF=()
compose_files CF
docker compose "${CF[@]}" up -d --build player-db player >>"$LOG" 2>&1 || die "compose up"

section "2. Health"
ready=0
for i in $(seq 1 90); do
  curl -fsS --max-time 5 "$PLAYER_URL/health" >/tmp/whick-pf-health.json 2>/dev/null && ready=1 && break
  sleep 2
done
[[ "$ready" -eq 1 ]] && ok "/health" || die "health timeout"
python3 -c "import json; d=json.load(open('/tmp/whick-pf-health.json')); assert d.get('status')=='ok'"

section "3. Library"
if [[ "$DEV_SAMPLES" == "0" ]]; then
  curl -fsS -X POST "$PLAYER_URL/api/library/scan" >/tmp/whick-pf-scan.json 2>/dev/null || true
  sleep 2
elif [[ "$DEV_SAMPLES" == "1" ]]; then
  curl -fsS -X POST "$PLAYER_URL/api/library/scan" >/tmp/whick-pf-scan.json 2>/dev/null || true
  sleep 3
fi
curl -fsS "$PLAYER_URL/api/library/status" >/tmp/whick-pf-lib.json
curl -fsS "$PLAYER_URL/api/tracks?per_page=500" >/tmp/whick-pf-tracks.json 2>/dev/null || echo '{"tracks":[]}' >/tmp/whick-pf-tracks.json
python3 >>"$LOG" 2>&1 <<PY
import json
d = json.load(open("/tmp/whick-pf-lib.json"))
assert d.get("radio_enabled") is True
assert d.get("room_correction_enabled") is True
assert d.get("external_providers_enabled") is False
paths = d.get("scan_paths") or []
total = int(d.get("total_tracks") or 0)
dev = "${DEV_SAMPLES}" == "1"
tracks = json.load(open("/tmp/whick-pf-tracks.json")).get("tracks") or []
if dev:
    assert any("samples" in p for p in paths), paths
    assert total >= 200, f"dev samples expected >=200, got {total}"
else:
    assert not any("samples" in p for p in paths), paths
    for t in tracks:
        fp = t.get("file_path") or ""
        assert "/samples/" not in fp and "sample-audio" not in fp, fp
    assert total < 200, f"customer install must not ship bundled samples, got {total}"
print(f"  tracks={total} paths={paths}")
PY
ok "GET /api/library/status"

if [[ "$DEV_SAMPLES" == "1" ]]; then
  curl -fsS "$PLAYER_URL/api/tracks?per_page=3" | python3 -c "import json,sys; d=json.load(sys.stdin); assert len(d.get('tracks',[]))>=1"
  ok "GET /api/tracks"
  curl -fsS "$PLAYER_URL/api/albums" | python3 -c "import json,sys; d=json.load(sys.stdin); assert len(d.get('albums',[]))>=5"
  ok "GET /api/albums"
  curl -fsS "$PLAYER_URL/api/artists" | python3 -c "import json,sys; d=json.load(sys.stdin); assert len(d.get('artists',[]))>=5"
  ok "GET /api/artists"
  curl -fsS "$PLAYER_URL/api/search?q=debussy" | python3 -c "import json,sys; d=json.load(sys.stdin); assert 'results' in d"
  ok "GET /api/search"
fi

section "4. Radio"
curl -fsS "$PLAYER_URL/api/radio" | python3 -c "import json,sys; d=json.load(sys.stdin); assert len(d.get('stations',[]))>=10"
ok "GET /api/radio"
curl -fsS "$PLAYER_URL/api/radio/kbs-1fm/play" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('ok') is True and d.get('playback')=='server'"
ok "GET /api/radio/kbs-1fm/play"

section "5. DSP / room correction"
curl -fsS "$PLAYER_URL/api/dsp/presets" | python3 -c "import json,sys; d=json.load(sys.stdin); assert len(d.get('presets',[]))>=5"
ok "GET /api/dsp/presets"
curl -fsS "$PLAYER_URL/api/dsp/profile" | python3 -c "import json,sys; json.load(sys.stdin)"
ok "GET /api/dsp/profile"
curl -fsS -X POST "$PLAYER_URL/api/dsp/room-correction" \
  -H 'Content-Type: application/json' \
  -d '{"peaking":[{"freq":80,"q":1.2,"gainDb":-2.5}]}' | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('ok') is True"
ok "POST /api/dsp/room-correction"
curl -fsS -X POST "$PLAYER_URL/api/dsp/channel-setup" \
  -H 'Content-Type: application/json' \
  -d '{"swapChannels":true}' | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('ok') and d.get('dsp',{}).get('swapChannels') is True"
ok "POST /api/dsp/channel-setup"
curl -fsS -X POST "$PLAYER_URL/api/spatial/test-tone" \
  -H 'Content-Type: application/json' \
  -d '{"channel":"left"}' | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('ok')"
ok "POST /api/spatial/test-tone"

section "6. Dashboard · system · spatial · playlists"
curl -fsS "$PLAYER_URL/api/dashboard" >/tmp/whick-pf-dash.json
python3 -c "import json; d=json.load(open('/tmp/whick-pf-dash.json')); assert 'library' in d and 'now_playing' in d"
ok "GET /api/dashboard"
curl -fsS "$PLAYER_URL/api/system/status" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('ok') is True and 'metrics' in d"
ok "GET /api/system/status"
curl -fsS "$PLAYER_URL/api/spatial/state" | python3 -c "import json,sys; json.load(sys.stdin)"
ok "GET /api/spatial/state"
curl -fsS -X POST "$PLAYER_URL/api/playlists" \
  -H 'Content-Type: application/json' \
  -d '{"name":"e2e-test","description":"auto"}' >/tmp/whick-pf-pl.json
python3 >>"$LOG" 2>&1 <<'PY'
import json
d = json.load(open("/tmp/whick-pf-pl.json"))
pl = d.get("playlist") or d
pid = pl.get("playlist_id")
assert pid, d
open("/tmp/whick-pf-pl-id.txt","w").write(str(pid))
PY
ok "POST /api/playlists"
PLID=$(cat /tmp/whick-pf-pl-id.txt)
curl -fsS "$PLAYER_URL/api/playlists" | python3 -c "import json,sys; assert any(p.get('playlist_id') for p in json.load(sys.stdin).get('playlists',[]))"
ok "GET /api/playlists"

section "7. Favorites · history · state"
curl -fsS "$PLAYER_URL/api/favorites" | python3 -c "import json,sys; json.load(sys.stdin)"
ok "GET /api/favorites"
curl -fsS "$PLAYER_URL/api/history" | python3 -c "import json,sys; json.load(sys.stdin)"
ok "GET /api/history"
curl -fsS "$PLAYER_URL/api/state" | python3 -c "import json,sys; json.load(sys.stdin)"
ok "GET /api/state"

section "8. WebSocket playback"
if [[ "$DEV_SAMPLES" == "1" ]]; then
  docker exec whick-player python3 >>"$LOG" 2>&1 <<'PY'
import asyncio, json, urllib.request, urllib.parse, websockets

async def main():
    albums = json.loads(urllib.request.urlopen("http://127.0.0.1:8080/api/albums").read())
    album = albums["albums"][0]
    tracks = json.loads(urllib.request.urlopen(
        "http://127.0.0.1:8080/api/albums/" + urllib.parse.quote(album["album"]) + "/tracks"
    ).read())
    ids = [t["track_id"] for t in tracks["tracks"]]
    async with websockets.connect("ws://127.0.0.1:8080/ws", open_timeout=12) as ws:
        await asyncio.wait_for(ws.recv(), timeout=12)
        await ws.send(json.dumps({"cmd": "play_queue", "track_ids": ids, "index": 0}))
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=12))
        assert msg.get("source") == "library", msg
        if len(ids) > 1:
            await ws.send(json.dumps({"cmd": "next"}))
            msg2 = json.loads(await asyncio.wait_for(ws.recv(), timeout=12))
            assert msg2.get("track_id") == ids[1], msg2
        reduced = ids[-1:]
        await ws.send(json.dumps({"cmd": "set_queue", "track_ids": reduced}))
        msg3 = json.loads(await asyncio.wait_for(ws.recv(), timeout=12))
        assert msg3.get("queue") == reduced, msg3
asyncio.run(main())
PY
  ok "WebSocket play_queue + next + set_queue"
else
  ok "WebSocket skipped (no library tracks)"
fi

section "9. Local AI (Ollama)"
ai_ok=$(curl -fsS --max-time 15 "$PLAYER_URL/api/dashboard" 2>/dev/null \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print('1' if d.get('ai',{}).get('ok') else '0')" 2>/dev/null || echo 0)
if [[ "$ai_ok" == "1" ]]; then
  Q=$(python3 -c "import urllib.parse; print(urllib.parse.quote('잔잔한 피아노'))")
  curl -fsS --max-time 120 "$PLAYER_URL/api/ai-search?q=$Q" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('ai',{}).get('ok') is True"
  ok "GET /api/ai-search"
else
  echo "  SKIP  AI (Ollama unreachable — start local-ai profile)" | tee -a "$LOG"
fi

section "10. Port bind check"
bind=$(docker port whick-player 8080 2>/dev/null | head -1 || true)
echo "  player bind: ${bind:-unknown}" | tee -a "$LOG"
if [[ "${WHICK_PLAYER_REQUIRE_LAN_BIND:-0}" == "1" ]]; then
  [[ "$bind" == *"0.0.0.0:8080"* || "$bind" == *":::8080"* ]] && ok "player LAN bind (miniPC)" || die "player not LAN bind ($bind)"
else
  [[ "$bind" == *"127.0.0.1:8080"* ]] && ok "player localhost bind (central SSOT)" || die "player not localhost bind ($bind)"
fi

section "11. Inbound policy"
INBOUND="/data/whick-ai/0_gateway/scripts/check-inbound-ports.sh"
if [[ -x "$INBOUND" ]]; then
  "$INBOUND" >>"$LOG" 2>&1 && ok "no public TCP listeners" || die "inbound policy violated"
else
  echo "  SKIP  check-inbound-ports.sh missing" | tee -a "$LOG"
fi

section "12. Teardown"
cd "$ROOT"
CF=()
compose_files CF
docker compose "${CF[@]}" stop player player-db >>"$LOG" 2>&1 || true
ok "player stopped"

section "Summary"
if [[ "$FAIL" -eq 0 ]]; then
  echo "ALL PASS player full ($LOG)" | tee -a "$LOG"
  exit 0
fi
echo "FAILED: $FAIL ($LOG)" | tee -a "$LOG"
exit 1
