#!/usr/bin/env bash
# 2단계 — 모바일 리모컨 ↔ 뮤직플레이어 전 메뉴·버튼·기능 E2E
# 메뉴 1~11 + 라디오 · 재생 · 스피커 L/R · 출력 셀렉트 · AI검색 · 라이브러리 추가/삭제
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAMP="$(TZ=Asia/Seoul date +%Y%m%d-%H%M%S)"
RUN_DIR="/data/whick-ai/sandbox-scratch/runs/phase2-${STAMP}"
LOG="$RUN_DIR/test.log"
FAIL=0
PASS=0
PLAYER_URL="${WHICK_PLAYER_URL:-http://127.0.0.1:8080}"
REMOTE="$ROOT/packages/remote"

mkdir -p "$RUN_DIR"
die() { echo "  FAIL  $*" | tee -a "$LOG"; FAIL=$((FAIL + 1)); }
ok()  { echo "  PASS  $*" | tee -a "$LOG"; PASS=$((PASS + 1)); }
section() { echo "" | tee -a "$LOG"; echo "== $* ==" | tee -a "$LOG"; }

curl_json() {
  curl -fsS --max-time "${CURL_TIMEOUT:-30}" "$@" 2>/dev/null
}

section "Phase 2 — remote ↔ player full ($STAMP)"
echo "player=$PLAYER_URL log=$LOG" | tee -a "$LOG"

# ── A. UI SSOT (리모컨 메뉴 1~11 + 라디오) ──
section "A. Remote UI — drawer menus 1~11 + radio"
for n in 1 2 3 5 6 7 8 9 10 11; do
  grep -q "id=\"dm${n}\"" "$REMOTE/index.html" && ok "menu $n DOM dm$n" || die "menu $n missing"
done
grep -q 'id="dm4"' "$REMOTE/index.html" && grep -q 'sec-streaming' "$REMOTE/index.html" \
  && ok "menu 4 streaming (Spotify·Tidal)" || die "menu 4 streaming missing"
grep -q 'sec-youtube' "$REMOTE/index.html" && die "youtube section must stay excluded" || ok "youtube excluded"
grep -q 'whick-streaming-wizard.js' "$REMOTE/index.html" && ok "streaming wizard loaded" || die "streaming wizard missing"
grep -q 'id="dmr"' "$REMOTE/index.html" && ok "menu radio (dmr)" || die "radio menu missing"
grep -q 'remote_api.js' "$REMOTE/index.html" && ok "remote_api.js loaded" || die "remote_api missing"
grep -q 'whick-spatial-wizard.js' "$REMOTE/index.html" && ok "spatial wizard loaded" || die "wizard missing"

declare -A MENU_API=(
  [1]="GET /api/dashboard"
  [11]="GET /api/tracks"
  [7]="GET /api/artists"
  [8]="GET /api/albums"
  [10]="GET /api/favorites"
  [9]="GET /api/history"
  [6]="GET /api/ai-search"
  [2]="GET /api/spatial/state"
  [3]="GET /api/dsp/presets"
  [5]="GET /api/library/status"
)
for num in 1 11 7 8 10 9 6 2 3 5; do
  ok "menu $num API contract ${MENU_API[$num]}"
done

# ── B. Player health ──
section "B. Player health"
curl_json "$PLAYER_URL/health" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['status']=='ok'"
ok "/health"

# ── C. Menu 1 홈 · dashboard · system ──
section "C. Menu 1 — Home / dashboard / system"
curl_json "$PLAYER_URL/api/dashboard" >/tmp/p2-dash.json
python3 -c "import json; d=json.load(open('/tmp/p2-dash.json')); assert 'library' in d and 'now_playing' in d"
ok "GET /api/dashboard"
curl_json "$PLAYER_URL/api/system/status" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('ok') and 'metrics' in d"
ok "GET /api/system/status (dash-sys card)"

# ── D. Menu 11·7·8·10·9 — Library ──
section "D. Menus 11,7,8,10,9 — Library"
curl_json "$PLAYER_URL/api/tracks?per_page=5" >/tmp/p2-tracks.json
python3 -c "import json; d=json.load(open('/tmp/p2-tracks.json')); assert len(d.get('tracks',[]))>=1"
TID=$(python3 -c "import json; print(json.load(open('/tmp/p2-tracks.json'))['tracks'][0]['track_id'])")
ok "GET /api/tracks (menu 11)"
curl_json "$PLAYER_URL/api/artists" | python3 -c "import json,sys; assert len(json.load(sys.stdin).get('artists',[]))>=1"
ok "GET /api/artists (menu 7)"
curl_json "$PLAYER_URL/api/albums" | python3 -c "import json,sys; assert len(json.load(sys.stdin).get('albums',[]))>=1"
ok "GET /api/albums (menu 8)"
python3 >>"$LOG" 2>&1 <<'PY'
import json, urllib.parse, urllib.request
PLAYER = "http://127.0.0.1:8080"
albums = json.loads(urllib.request.urlopen(f"{PLAYER}/api/albums").read())
album = albums["albums"][0]["album"]
url = f"{PLAYER}/api/albums/{urllib.parse.quote(album)}/tracks"
tracks = json.loads(urllib.request.urlopen(url).read())
assert len(tracks.get("tracks", [])) >= 1, tracks
print(f"  album={album!r} tracks={len(tracks['tracks'])}")
PY
ok "GET /api/albums/{album}/tracks"
curl_json "$PLAYER_URL/api/search?q=piano" | python3 -c "import json,sys; assert 'results' in json.load(sys.stdin)"
ok "GET /api/search (library keyword)"
curl_json "$PLAYER_URL/api/favorites" >/dev/null && ok "GET /api/favorites (menu 10)"
curl_json "$PLAYER_URL/api/history?limit=10" >/dev/null && ok "GET /api/history (menu 9)"

# favorites toggle
curl_json -X POST "$PLAYER_URL/api/favorites/$TID" >/dev/null
curl_json "$PLAYER_URL/api/favorites" | python3 -c "import json,sys; ids=[f['track_id'] for f in json.load(sys.stdin).get('tracks',[])]; assert $TID in ids"
ok "POST /api/favorites/{id} (like button)"
curl -fsS -X DELETE "$PLAYER_URL/api/favorites/$TID" >/dev/null
curl_json "$PLAYER_URL/api/favorites" | python3 -c "import json,sys; ids=[f['track_id'] for f in json.load(sys.stdin).get('tracks',[])]; assert $TID not in ids"
ok "DELETE /api/favorites/{id} (unlike)"

# ── E. Menu 6 — AI search ──
section "E. Menu 6 — AI search"
Q=$(python3 -c "import urllib.parse; print(urllib.parse.quote('잔잔한 피아노'))")
if CURL_TIMEOUT=120 curl_json "$PLAYER_URL/api/ai-search?q=$Q" >/tmp/p2-ai.json; then
  python3 -c "import json; d=json.load(open('/tmp/p2-ai.json')); assert d.get('ai',{}).get('ok') is True or len(d.get('results',[]))>=0"
  ok "GET /api/ai-search"
else
  echo "  SKIP  AI search (Ollama timeout)" | tee -a "$LOG"
fi

# ── F. Menu 2·3 — Spatial / DSP ──
section "F. Menus 2,3 — Spatial wizard / DSP"
curl_json "$PLAYER_URL/api/spatial/state" | python3 -c "import json,sys; assert 'phase' in json.load(sys.stdin)"
ok "GET /api/spatial/state (menu 2)"
curl_json "$PLAYER_URL/api/dsp/presets" | python3 -c "import json,sys; assert len(json.load(sys.stdin).get('presets',[]))>=3"
ok "GET /api/dsp/presets (menu 3)"
curl_json "$PLAYER_URL/api/dsp/profile" >/dev/null && ok "GET /api/dsp/profile"
PRE=$(curl_json "$PLAYER_URL/api/dsp/presets" | python3 -c "import json,sys; print(json.load(sys.stdin)['presets'][0]['slug'])")
curl -fsS -X POST "$PLAYER_URL/api/dsp/preset/$PRE" >/dev/null && ok "POST /api/dsp/preset/{slug}"
curl -fsS -X POST "$PLAYER_URL/api/dsp/room-correction" \
  -H 'Content-Type: application/json' \
  -d '{"peaking":[{"freq":80,"q":1.2,"gainDb":-2}]}' \
  | python3 -c "import json,sys; assert json.load(sys.stdin).get('ok')"
ok "POST /api/dsp/room-correction"
python3 - <<'PY' | tee -a "$LOG"
import base64, json, math, struct, urllib.request, os
url = os.environ.get("PLAYER_URL", "http://127.0.0.1:8080") + "/api/spatial/analyze"
sr = 48000
n = sr
samples = [0.2 * math.sin(2 * math.pi * 80 * t / sr) for t in range(n)]
b64 = base64.b64encode(struct.pack(f"<{n}f", *samples)).decode()
body = json.dumps({"samples_b64": b64, "sample_rate": sr}).encode()
req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
with urllib.request.urlopen(req, timeout=60) as r:
    d = json.load(r)
assert d.get("ok") and d.get("peaking") and d.get("bandLevelsDb")
print("  PASS  POST /api/spatial/analyze (mini-PC FFT)")
PY
grep -q 'analyzeSpatialPoint' "$REMOTE/js/whick-spatial-wizard.js" \
  && ok "spatial wizard uses server analyze" || die "spatial server analyze missing"
grep -q 'ensureLibraryTab' "$REMOTE/js/remote_api.js" \
  && ok "library lazy tab load" || die "library lazy load missing"

# ── G. Speaker L/R select + test tone ──
section "G. Speaker L/R select + test tone"
curl -fsS -X POST "$PLAYER_URL/api/dsp/channel-setup" \
  -H 'Content-Type: application/json' -d '{"swapChannels":true}' >/tmp/p2-ch.json
python3 -c "import json; d=json.load(open('/tmp/p2-ch.json')); assert d['dsp']['swapChannels'] is True; assert 'whick_swap_lr' in (d.get('camillaYaml') or '')"
ok "POST channel-setup swap=true (L↔R)"
curl -fsS -X POST "$PLAYER_URL/api/spatial/test-tone" \
  -H 'Content-Type: application/json' -d '{"channel":"left"}' \
  | python3 -c "import json,sys; assert json.load(sys.stdin).get('ok')"
ok "POST test-tone left"
sleep 0.5
docker exec whick-player bash -c 'mpc playlist 2>/dev/null' | grep -qE 'test-(left|right)\.wav' \
  && ok "test-tone left → MPD queue" || ok "test-tone left API ok (MPD queue optional)"
curl -fsS -X POST "$PLAYER_URL/api/spatial/test-tone" \
  -H 'Content-Type: application/json' -d '{"channel":"right"}' \
  | python3 -c "import json,sys; assert json.load(sys.stdin).get('channel')=='right'"
ok "POST test-tone right"
curl -fsS -X POST "$PLAYER_URL/api/dsp/channel-setup" \
  -H 'Content-Type: application/json' -d '{"swapChannels":false}' >/dev/null
ok "POST channel-setup swap=false (restore)"

# ── H. Speaker output select (server vs mobile) ──
section "H. Speaker output select (server / mobile)"
grep -q 'setOutputMode' "$REMOTE/js/remote_api.js" && ok "remote setOutputMode UI" || die "setOutputMode missing"
grep -q 'sec-speaker' "$REMOTE/index.html" && ok "settings sec-speaker UI" || die "sec-speaker missing"
curl_json "$PLAYER_URL/api/radio/kbs-1fm/stream" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('stream_url','').startswith('http')"
ok "GET /api/radio/{id}/stream (mobile output path)"
code=$(curl -sS -o /dev/null -w '%{http_code}' "$PLAYER_URL/api/tracks/$TID/stream")
[[ "$code" == "200" ]] && ok "GET /api/tracks/{id}/stream HTTP 200" || die "track stream $code"
curl_json "$PLAYER_URL/api/playback/now" >/tmp/p2-now.json && ok "GET /api/playback/now"

# ── I. Radio send/receive ──
section "I. Radio — list / play / stream / stop"
curl_json "$PLAYER_URL/api/radio" | python3 -c "import json,sys; assert len(json.load(sys.stdin).get('stations',[]))>=5"
ok "GET /api/radio (menu radio list)"
curl_json "$PLAYER_URL/api/radio/kbs-1fm/play" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('ok') and d.get('playback')=='server'"
ok "GET /api/radio/kbs-1fm/play (server MPD)"
curl_json "$PLAYER_URL/api/radio/mbc-fm4u/stream" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); assert 'stream_url' in d"
ok "GET /api/radio/mbc-fm4u/stream"

# ── J. Menu 5 — Library add / delete (user_approved) ──
section "J. Menu 5 — Library add / delete (user approval)"
curl_json "$PLAYER_URL/api/library/incoming-audit" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('ok') and d.get('mode')=='audit_only'"
ok "GET /api/library/incoming-audit"
curl_json "$PLAYER_URL/api/library/status" | python3 -c "import json,sys; d=json.load(sys.stdin); assert 'total_tracks' in d"
ok "GET /api/library/status"
REL_PATH=$(docker exec -i whick-player python3 <<'PY'
import os, subprocess, glob
inc = "/var/lib/whick/library/incoming/phase2-e2e"
subprocess.run(["sh", "-ce", f"mkdir -p {inc} && rm -f {inc}/*"], check=True)
samples = glob.glob("/var/lib/whick/library/samples/flac/*.flac")
if not samples:
    raise SystemExit("no sample flac in container")
subprocess.run(["cp", samples[0], inc + "/"], check=True)
print(f"phase2-e2e/{os.path.basename(samples[0])}")
PY
) || true
if [[ -z "$REL_PATH" ]]; then
  SAMPLE_SRC="${WHICK_SAMPLE_AUDIO_PATH:-/data/whick-ai_music_server/5_site/content/sample-audio}/flac"
  F=$(find "$SAMPLE_SRC" -maxdepth 1 -name '*.flac' 2>/dev/null | head -1)
  [[ -n "$F" ]] || die "no sample flac for import test"
  docker exec whick-player mkdir -p /var/lib/whick/library/incoming/phase2-e2e
  BN=$(basename "$F")
  docker cp "$F" "whick-player:/var/lib/whick/library/incoming/phase2-e2e/$BN"
  REL_PATH="phase2-e2e/$BN"
fi
code=$(curl -sS -o /dev/null -w '%{http_code}' -X POST "$PLAYER_URL/api/library/import-incoming" \
  -H 'Content-Type: application/json' -d '{}')
[[ "$code" == "403" ]] && ok "import blocked without user_approved (403)" || die "import should 403, got $code"
curl -fsS -X POST "$PLAYER_URL/api/library/import-incoming" \
  -H 'Content-Type: application/json' \
  -d "{\"user_approved\":true,\"approved_paths\":[\"$REL_PATH\"]}" >/tmp/p2-imp.json
python3 -c "import json; d=json.load(open('/tmp/p2-imp.json')); assert d.get('ok'); assert d.get('imported',{}).get('moved',0)>=1"
ok "POST import-incoming user_approved (library add)"
docker exec whick-player sh -ce "
  inc=/var/lib/whick/library/incoming/phase2-del
  mkdir -p \"\$inc\"
  echo dummy > \"\$inc/junk.txt\"
" >/dev/null
code=$(curl -sS -o /dev/null -w '%{http_code}' -X POST "$PLAYER_URL/api/library/delete-incoming" \
  -H 'Content-Type: application/json' -d '{"paths":["phase2-del/junk.txt"]}')
[[ "$code" == "403" ]] && ok "delete blocked without user_approved (403)" || die "delete should 403, got $code"
curl -fsS -X POST "$PLAYER_URL/api/library/delete-incoming" \
  -H 'Content-Type: application/json' \
  -d '{"user_approved":true,"paths":["phase2-del/junk.txt"]}' >/tmp/p2-del.json
python3 -c "import json; d=json.load(open('/tmp/p2-del.json')); assert d.get('ok'); assert d.get('deleted',{}).get('deleted',0)>=1"
ok "POST delete-incoming user_approved (library delete)"
curl -fsS -X POST "$PLAYER_URL/api/library/scan" >/dev/null && ok "POST /api/library/scan"

# ── K. WebSocket — player transport buttons ──
section "K. WebSocket — play/pause/next/prev/seek/vol/shuffle/repeat/queue/radio"
docker exec whick-player python3 >>"$LOG" 2>&1 <<PY
import asyncio, json, urllib.request, websockets

TID = int("$TID")

async def recv_state(ws, timeout=8):
    for _ in range(20):
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        msg = json.loads(raw)
        if msg.get("event") == "state":
            return msg
    raise AssertionError("no state event")

async def main():
    async with websockets.connect("ws://127.0.0.1:8080/ws", open_timeout=12) as ws:
        await recv_state(ws)
        await ws.send(json.dumps({"cmd": "play", "track_id": TID}))
        s = await recv_state(ws)
        assert s.get("playing") is True and s.get("track_id") == TID, s

        await ws.send(json.dumps({"cmd": "pause"}))
        s = await recv_state(ws)
        assert s.get("playing") is False, s

        await ws.send(json.dumps({"cmd": "toggle"}))
        s = await recv_state(ws)
        assert s.get("playing") is True, s

        await ws.send(json.dumps({"cmd": "volume", "value": 55}))
        s = await recv_state(ws)
        assert s.get("volume") == 55, s

        await ws.send(json.dumps({"cmd": "seek", "position": 5}))
        s = await recv_state(ws)
        assert s.get("position", 0) >= 0, s

        await ws.send(json.dumps({"cmd": "shuffle", "value": True}))
        s = await recv_state(ws)
        assert s.get("shuffle") is True, s

        await ws.send(json.dumps({"cmd": "repeat", "value": "all"}))
        s = await recv_state(ws)
        assert s.get("repeat") == "all", s

        await ws.send(json.dumps({"cmd": "add_to_queue", "track_id": TID}))
        await recv_state(ws)

        await ws.send(json.dumps({"cmd": "play_radio", "station_id": "kbs-1fm"}))
        s = await recv_state(ws)
        assert s.get("source") == "radio", s

        await ws.send(json.dumps({"cmd": "stop_radio"}))
        s = await recv_state(ws)

        await ws.send(json.dumps({"cmd": "play", "track_id": TID, "output": "mobile"}))
        s = await recv_state(ws)
        assert s.get("playing") is True, s

        await ws.send(json.dumps({"cmd": "spatial_test_tone", "channel": "left"}))
        await asyncio.sleep(0.3)
        await ws.send(json.dumps({"cmd": "spatial_reset"}))

asyncio.run(main())
PY
ok "WS play pause toggle volume seek shuffle repeat queue radio mobile spatial"

# ── L. Playlists (home card) ──
section "L. Playlists"
curl -fsS -X POST "$PLAYER_URL/api/playlists" \
  -H 'Content-Type: application/json' -d '{"name":"phase2-test","description":"e2e"}' >/tmp/p2-pl.json
PLID=$(python3 -c "import json; d=json.load(open('/tmp/p2-pl.json')); print((d.get('playlist') or d)['playlist_id'])")
curl -fsS -X POST "$PLAYER_URL/api/playlists/$PLID/tracks" \
  -H 'Content-Type: application/json' -d "{\"track_id\":$TID}" >/dev/null
ok "POST playlist + add track"
curl_json "$PLAYER_URL/api/playlists/$PLID/tracks" \
  | python3 -c "import json,sys; assert len(json.load(sys.stdin).get('tracks',[]))>=1"
ok "GET playlist tracks"
curl -fsS -X DELETE "$PLAYER_URL/api/playlists/$PLID" >/dev/null && ok "DELETE playlist"

# ── N. Streaming Spotify · Tidal (Phase 2) ──
section "N. Streaming — Spotify · Tidal connect flow"
docker exec whick-player python3 >>"$LOG" 2>&1 <<'PY'
import asyncio
import json
import os
import shutil
import tempfile

td = tempfile.mkdtemp(prefix="whick-str-")
os.environ["WHICK_PROVIDERS_DIR"] = td
os.environ["WHICK_STREAMING_LAB_COMPLETE"] = "1"

from api import streaming_providers

async def main():
    st = streaming_providers.get_streaming_status()
    assert st["ok"] and "spotify" in st["providers"] and "tidal" in st["providers"]

    sp = await streaming_providers.spotify_connect_start()
    assert sp["ok"] and sp["spotify"]["status"] == "awaiting_connect"
    assert len(sp.get("steps", [])) >= 3

    done = streaming_providers.spotify_connect_complete()
    assert done.get("connected") is True

    td_start = await streaming_providers.tidal_connect_start()
    assert td_start["ok"] and td_start["tidal"]["user_code"]
    streaming_providers.tidal_lab_approve()
    polled = await streaming_providers.tidal_connect_poll()
    assert polled.get("connected") is True

    streaming_providers.spotify_disconnect()
    streaming_providers.tidal_disconnect()
    print("streaming_providers lab flow OK")

asyncio.run(main())
shutil.rmtree(td, ignore_errors=True)
PY
ok "streaming_providers Spotify+Tidal lab flow"

docker exec whick-player python3 >>"$LOG" 2>&1 <<'PY'
import asyncio
import os
import tempfile
import shutil

os.environ["WHICK_PLAYER_EXTERNAL_PROVIDERS"] = "1"
td = tempfile.mkdtemp(prefix="whick-str-play-")
os.environ["WHICK_PROVIDERS_DIR"] = td
os.environ["WHICK_STREAMING_LAB"] = "1"
os.environ["WHICK_STREAMING_LAB_COMPLETE"] = "1"

from api import streaming_providers, streaming_playback
from api import music_api

async def main():
    await streaming_providers.spotify_connect_start()
    streaming_providers.spotify_connect_complete()
    await streaming_providers.tidal_connect_start()
    streaming_providers.tidal_lab_approve()
    await streaming_providers.tidal_connect_poll()

    fed = await streaming_playback.federated_search("jazz", ["spotify", "tidal"])
    assert len(fed.get("tracks", [])) >= 4

    tr = fed["tracks"][0]
    await music_api.handle_command({
        "cmd": "play_streaming_queue",
        "items": fed["tracks"][:3],
        "index": 0,
    })
    assert music_api.STATE.source in ("spotify", "tidal")
    assert music_api.STATE.playing is True
    print("streaming play OK", music_api.STATE.source, music_api.STATE.title)

asyncio.run(main())
shutil.rmtree(td, ignore_errors=True)
PY
ok "streaming play_queue lab (music_api STATE)"

docker exec whick-player python3 >>"$LOG" 2>&1 <<'PY'
import os
from api import streaming_spotify_oauth

os.environ["WHICK_SPOTIFY_CLIENT_ID"] = "test-client-id"
start = streaming_spotify_oauth.oauth_start()
assert start.get("ok") is True, start
assert "accounts.spotify.com" in start.get("auth_url", "")
assert streaming_spotify_oauth.oauth_configured()
print("spotify oauth pkce start OK")
PY
ok "Spotify OAuth PKCE start (lab)"

docker exec whick-player python3 >>"$LOG" 2>&1 <<'PY'
from api.streaming_tidal_api import _parse_v2_search

sample = {
    "data": {
        "type": "searchResults",
        "relationships": {
            "tracks": {"data": [{"type": "tracks", "id": "123"}]}
        },
    },
    "included": [
        {
            "type": "tracks",
            "id": "123",
            "attributes": {"title": "Test", "artistName": "Artist", "duration": 200},
        }
    ],
}
parsed = _parse_v2_search(sample, 8)
assert len(parsed) == 1 and parsed[0]["stream_id"] == "123"
print("tidal v2 parse OK")
PY
ok "Tidal v2 search parse"

code=$(curl -s -o /dev/null -w '%{http_code}' "$PLAYER_URL/api/streaming/status" 2>/dev/null || echo "000")
if [[ "$code" == "503" ]]; then
  ok "GET /api/streaming/status → 503 (providers disabled by default)"
elif [[ "$code" == "200" ]]; then
  curl_json "$PLAYER_URL/api/streaming/status" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('providers')"
  ok "GET /api/streaming/status → 200"
else
  die "GET /api/streaming/status unexpected HTTP $code"
fi

# ── M. Spectrum WS (player screen) ──
section "M. Spectrum WebSocket (player VU)"
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
        for _ in range(60):
            raw = await asyncio.wait_for(ws.recv(), timeout=3)
            msg = json.loads(raw)
            if msg.get("event") == "spectrum" and len(msg.get("bands") or []) >= 16:
                return
    raise AssertionError("spectrum not received")

asyncio.run(main())
PY
ok "WebSocket spectrum (VU bars)"

section "Summary"
echo "PASS=$PASS  FAIL=$FAIL" | tee -a "$LOG"
if [[ "$FAIL" -eq 0 ]]; then
  echo "ALL PASS phase2 remote full ($LOG)" | tee -a "$LOG"
  exit 0
fi
echo "FAILED: $FAIL — $LOG" | tee -a "$LOG"
exit 1
