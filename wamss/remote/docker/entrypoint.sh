#!/bin/sh
set -e

mkdir -p /var/lib/whick/library/music /var/lib/whick/library/playlists /var/lib/whick/library/incoming /var/lib/whick/library/sweep /var/lib/whick/library/music/tones /var/lib/whick/camilla/fir /var/lib/whick/run /run/mpd
SPECTRUM_FIFO="/var/lib/whick/run/mpd-spectrum.pcm"
SPECTRUM_RING="/var/lib/whick/run/spectrum-ring.pcm"
rm -f "$SPECTRUM_FIFO" "$SPECTRUM_RING"
mkfifo "$SPECTRUM_FIFO"
chmod 666 "$SPECTRUM_FIFO"
# 상시 drain — spectrum UI는 ring 파일만 읽음 (FIFO 경쟁으로 DAC 끊김 방지)
export WHICK_SPECTRUM_FIFO="$SPECTRUM_FIFO"
export WHICK_SPECTRUM_RING="$SPECTRUM_RING"
python3 /app/docker/spectrum_drain.py &
export WHICK_SPECTRUM_DRAIN_PID=$!
if [ ! -f /var/lib/whick/library/sweep/log-sweep.wav ] && [ -f /app/docker/log-sweep.wav ]; then
  cp /app/docker/log-sweep.wav /var/lib/whick/library/sweep/log-sweep.wav
fi
for tone in log-sweep test-left test-right; do
  src=""
  if [ -f "/var/lib/whick/library/sweep/${tone}.wav" ]; then
    src="/var/lib/whick/library/sweep/${tone}.wav"
  elif [ -f "/app/docker/${tone}.wav" ]; then
    src="/app/docker/${tone}.wav"
  fi
  if [ -n "$src" ]; then
    cp "$src" "/var/lib/whick/library/music/tones/${tone}.wav"
  fi
done

echo "[player] waiting for PostgreSQL…"
python3 - <<'PY'
import os, sys, time
import asyncio
import asyncpg

url = os.environ.get("DATABASE_URL", "")
if not url:
    sys.exit("DATABASE_URL required")

async def wait():
    for i in range(60):
        try:
            conn = await asyncpg.connect(url, timeout=3)
            await conn.close()
            print("[player] database ready")
            return
        except Exception as exc:
            print(f"[player] db retry {i + 1}/60: {exc}")
            await asyncio.sleep(2)
    sys.exit("database timeout")

asyncio.run(wait())
PY

echo "[player] CamillaDSP profile"
python3 - <<'PY'
from api.audio_pipeline import ensure_default_profile, verify_camilla_dry_run, camilla_enabled
p = ensure_default_profile()
print("[player] camilla profile", p)
if camilla_enabled():
    ok, msg = verify_camilla_dry_run()
    print("[player] camilladsp --check", "OK" if ok else "FAIL", msg[:200])
PY

echo "[player] ALSA Loopback + Camilla resident daemon"
if [ "${WHICK_CAMILLA_ENABLED:-1}" = "1" ]; then
  if ! sh /app/docker/ensure-aloop.sh; then
    # fifo 자동 폴백은 MPD 제어 소켓 hang 을 유발한다(목록만 되고 재생 실패).
    # Loopback 없으면 DSP를 끄고 Bit-Perfect(direct ALSA)로 기동 — 재생 가능 상태 유지.
    echo "[player] CRITICAL ensure-aloop failed — disabling Camilla DSP (direct ALSA, no fifo fallback)" >&2
    export WHICK_CAMILLA_ENABLED=0
    export WHICK_CAMILLA_TRANSPORT=
  else
    sh /app/docker/start-camilla-daemon.sh || echo "[player] WARN camilla daemon start failed"
  fi
fi

echo "[player] DAC capability detect"
python3 - <<'PY'
from api.dac_capability import ensure_dac_capability_detected
cap = ensure_dac_capability_detected()
print("[player] dac", cap.get("source"), cap.get("product_label") or cap.get("notes", "")[:60])
PY

echo "[player] MPD config"
python3 /app/docker/gen_mpd_conf.py

echo "[player] starting MPD…"
mpd --no-daemon &
MPD_PID=$!
sleep 1
if ! kill -0 "$MPD_PID" 2>/dev/null; then
  echo "[player] MPD failed to start" >&2
  exit 1
fi
mpc update >/dev/null 2>&1 || true

echo "[player] playback route (Camilla Loopback feed)"
python3 - <<'PY'
from api.playback_router import sync_playback_route
from api.dsp_store import default_dsp_profile
r = sync_playback_route(default_dsp_profile())
print("[player] mpd outputs", r)
PY

/app/docker/start-librespot.sh || true

if [ "${WHICK_SEED_DEMO:-0}" = "1" ]; then
  python3 /app/docker/seed_demo_library.py || echo "[player] seed skipped or failed"
fi

echo "[player] remote device token"
python3 - <<'PY'
from api.device_auth import ensure_token_file
print("[player] device_token", ensure_token_file()[:16] + "…")
PY

echo "[player] starting music API on :8080 (library scan on startup via API lifespan)"
exec uvicorn api.music_api:app --host 0.0.0.0 --port 8080
