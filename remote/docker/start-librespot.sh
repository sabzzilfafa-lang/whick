#!/bin/sh
# Spotify Connect → 상주 Camilla (aloop ALSA 또는 FIFO feed)
set -eu

if [ "${WHICK_PLAYER_EXTERNAL_PROVIDERS:-0}" != "1" ]; then
  exit 0
fi
if [ "${WHICK_LIBRESPOT_AUTOSTART:-1}" != "1" ]; then
  exit 0
fi
if ! command -v librespot >/dev/null 2>&1; then
  echo "[librespot] binary missing — skip"
  exit 0
fi
if pgrep -f '[l]ibrespot' >/dev/null 2>&1; then
  echo "[librespot] already running"
  exit 0
fi

NAME="${WHICK_SPOTIFY_DEVICE_NAME:-Whick Player}"
CACHE="${WHICK_PROVIDERS_DIR:-/var/lib/whick/providers}/spotify"
LOG="${WHICK_LIBRESPOT_LOG:-/var/lib/whick/run/librespot.log}"
mkdir -p "$CACHE" "$(dirname "$LOG")"

TRANSPORT="$(python3 - <<'PY'
from api.camilla_loopback import transport_mode
print(transport_mode())
PY
)"

# FIFO 경로는 MPD pipe·bridge와 동일하게 S32LE
if [ "$TRANSPORT" = "fifo" ]; then
  FORMAT="${WHICK_LIBRESPOT_FORMAT:-S32}"
else
  FORMAT="${WHICK_LIBRESPOT_FORMAT:-S16}"
fi

if [ -n "${WHICK_LIBRESPOT_BACKEND:-}" ]; then
  BACKEND="$WHICK_LIBRESPOT_BACKEND"
  DEVICE="${WHICK_LIBRESPOT_DEVICE:-}"
elif [ "$TRANSPORT" = "fifo" ]; then
  BACKEND="subprocess"
  DEVICE="/app/docker/whick-camilla-feed.sh"
else
  BACKEND="alsa"
  DEVICE="$(python3 - <<'PY'
from api.camilla_loopback import loopback_feed_device
print(loopback_feed_device())
PY
)"
fi

if [ -z "${DEVICE:-}" ] && [ "$BACKEND" = "subprocess" ]; then
  DEVICE="/app/docker/whick-camilla-feed.sh"
fi

echo "[librespot] starting name=$NAME backend=$BACKEND device=$DEVICE transport=$TRANSPORT" | tee -a "$LOG"
nohup librespot \
  --name "$NAME" \
  --cache "$CACHE" \
  --zeroconf-port 0 \
  --backend "$BACKEND" \
  --device "$DEVICE" \
  --format "$FORMAT" \
  >>"$LOG" 2>&1 &
echo "[librespot] pid=$!"
