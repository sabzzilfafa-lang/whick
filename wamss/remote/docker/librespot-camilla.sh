#!/bin/sh
# librespot subprocess backend → CamillaDSP (Spotify Connect 재생)
set -eu

PROFILE="${WHICK_CAMILLA_PROFILE:-/var/lib/whick/camilla/profile.yml}"
LOG="${WHICK_LIBRESPOT_CAMILLA_LOG:-/var/lib/whick/run/librespot-camilla.log}"
RATE="${WHICK_LIBRESPOT_PIPE_RATE:-48000}"
DAC_RATE="${WHICK_DAC_ALSA_RATE:-48000}"

if [ ! -f "$PROFILE" ]; then
  echo "[librespot-camilla] missing profile: $PROFILE" >>"$LOG"
  cat >/dev/null
  exit 0
fi

if ! command -v camilladsp >/dev/null 2>&1; then
  echo "[librespot-camilla] camilladsp missing — drain" >>"$LOG"
  cat >/dev/null
  exit 0
fi

. /app/docker/whick-camilla-rate.sh
OS_RATE="$(whick_camilla_playback_rate "$PROFILE")"

echo "[librespot-camilla] start $(date -Iseconds) profile=$PROFILE in_rate=$RATE os_rate=$OS_RATE" >>"$LOG"

. /app/docker/resolve-alsa-device.sh
ALSA_DEV="$(resolve_alsa_device || true)"
echo "[librespot-camilla] alsa_device=${ALSA_DEV:-none}" >>"$LOG"

if [ -n "$ALSA_DEV" ] && ls /dev/snd/controlC* >/dev/null 2>&1; then
  exec ffmpeg -hide_banner -loglevel error -f s24le -ar "$RATE" -ac 2 -i - \
    -f f32le -ar "$OS_RATE" -ac 2 pipe:1 2>>"$LOG" | \
    camilladsp "$PROFILE" 2>>"$LOG" | \
    ffmpeg -hide_banner -loglevel error -f f32le -ar "$OS_RATE" -ac 2 -i - \
      -af "aresample=${DAC_RATE}:resampler=soxr" -f alsa "${ALSA_DEV}" 2>>"$LOG"
fi

exec ffmpeg -hide_banner -loglevel error -f s24le -ar "$RATE" -ac 2 -i - \
  -f f32le -ar "$OS_RATE" -ac 2 pipe:1 2>>"$LOG" | \
  camilladsp "$PROFILE" 2>>"$LOG" | \
  cat >/dev/null
