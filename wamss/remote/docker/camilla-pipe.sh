#!/bin/sh
# MPD pipe output → ffmpeg (s16le 44.1k) → camilladsp (stdin f32 48k) → ALSA device
# Resilience: ALSA device retry, fallback to aplay, proper logging
set -e

PROFILE="${WHICK_CAMILLA_PROFILE:-/var/lib/whick/camilla/profile.yml}"
LOG="${WHICK_CAMILLA_LOG:-/var/lib/whick/run/camilla-pipe.log}"
RATE="${WHICK_MPD_PIPE_RATE:-44100}"
DAC_RATE="${WHICK_DAC_ALSA_RATE:-48000}"
ASOUND="${WHICK_ASOUND_ROOT:-/proc/asound}"

ts() { date -Iseconds; }

log() {
  echo "[camilla-pipe] $(ts) $*" >>"$LOG"
  echo "[camilla-pipe] $(ts) $*" >&2
}

cleanup() {
  log "pipe closing (exit=$?)"
}
trap cleanup EXIT

# Profile check
if [ ! -f "$PROFILE" ]; then
  log "WARN missing profile: $PROFILE — attempting direct ALSA bypass"
  # Try to play PCM data directly to ALSA via aplay (16-bit, 44.1kHz, stereo)
  if command -v aplay >/dev/null 2>&1; then
    ALSA_DEV=""
    if [ -r "$ASOUND/cards" ]; then
      ALSA_DEV=$(awk '/USB-Audio|USB Audio/ {if(match($0,/card [0-9]+/)){s=substr($0,RSTART,RLENGTH); split(s,a," "); print "hw:"a[2]",0"}}' "$ASOUND/cards" 2>/dev/null | head -1)
    fi
    if [ -n "$ALSA_DEV" ]; then
      log "direct aplay → ${ALSA_DEV} (no camilla profile)"
      exec aplay -q -D "$ALSA_DEV" -f S16_LE -r "$RATE" -c 2 2>>"$LOG"
    fi
  fi
  cat >/dev/null
  exit 0
fi

if ! command -v camilladsp >/dev/null 2>&1; then
  log "WARN camilladsp not installed — trying direct aplay"
  if command -v aplay >/dev/null 2>&1; then
    . /app/docker/resolve-alsa-device.sh 2>/dev/null || true
    ALSA_DEV="$(resolve_alsa_device 2>/dev/null || true)"
    if [ -n "$ALSA_DEV" ]; then
      log "direct aplay → ${ALSA_DEV}"
      exec aplay -q -D "$ALSA_DEV" -f S16_LE -r "$RATE" -c 2 2>>"$LOG"
    fi
  fi
  cat >/dev/null
  exit 0
fi

# Source helper scripts
if [ -f /app/docker/whick-camilla-rate.sh ]; then
  . /app/docker/whick-camilla-rate.sh
  OS_RATE="$(whick_camilla_playback_rate "$PROFILE" 2>/dev/null || echo 48000)"
else
  OS_RATE=48000
fi

log "start profile=$PROFILE os_rate=$OS_RATE dac_rate=$DAC_RATE"

if [ -f /app/docker/resolve-alsa-device.sh ]; then
  . /app/docker/resolve-alsa-device.sh
  ALSA_DEV="$(resolve_alsa_device 2>/dev/null || true)"
else
  ALSA_DEV=""
fi
log "alsa_device=${ALSA_DEV:-none}"

# Pipeline with ALSA retry
if [ -n "$ALSA_DEV" ] && ls /dev/snd/controlC* >/dev/null 2>&1; then
  RETRY=0
  MAX_RETRY=5
  while [ $RETRY -lt $MAX_RETRY ]; do
    if [ $RETRY -gt 0 ]; then
      log "ALSA retry ${RETRY}/${MAX_RETRY}"
      sleep 1
    fi
    # Run the pipeline — if it succeeds, exec replaces us
    ffmpeg -hide_banner -loglevel error -f s16le -ar "$RATE" -ac 2 -i - \
      -f f32le -ar 48000 -ac 2 pipe:1 2>>"$LOG" | \
      camilladsp "$PROFILE" 2>>"$LOG" | \
      ffmpeg -hide_banner -loglevel error -f f32le -ar "$OS_RATE" -ac 2 -i - \
        -af "aresample=${DAC_RATE}" -f alsa "${ALSA_DEV}" 2>>"$LOG" &
    PIPE_PID=$!
    # Wait for pipeline to start or fail
    sleep 1
    if kill -0 $PIPE_PID 2>/dev/null; then
      log "pipeline started (pid=$PIPE_PID) alsa=${ALSA_DEV}"
      wait $PIPE_PID 2>/dev/null
      EXIT_CODE=$?
      if [ $EXIT_CODE -eq 0 ]; then
        exit 0
      fi
      log "pipeline exited code=$EXIT_CODE"
      RETRY=$((RETRY + 1))
      continue
    fi
    RETRY=$((RETRY + 1))
  done
  # All retries failed — try aplay fallback
  if command -v aplay >/dev/null 2>&1; then
    log "pipeline failed after ${MAX_RETRY} retries — fallback to aplay"
    exec aplay -q -D "$ALSA_DEV" -f S16_LE -r "$RATE" -c 2 2>>"$LOG"
  fi
fi

# No ALSA device — drain through camilladsp (spectrum visualization only, no audio)
log "drain mode (no ALSA device)"
exec ffmpeg -hide_banner -loglevel error -f s16le -ar "$RATE" -ac 2 -i - \
  -f f32le -ar 48000 -ac 2 pipe:1 2>>"$LOG" | \
  camilladsp "$PROFILE" 2>>"$LOG" | \
  cat >/dev/null
