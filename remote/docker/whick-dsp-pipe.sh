#!/bin/sh
# MPD DSP pipe — 고해상도 PCM 유지 → CamillaDSP → ALSA (최소 손실)
set -eu

PROFILE="${WHICK_CAMILLA_PROFILE:-/var/lib/whick/camilla/profile.yml}"
LOG="${WHICK_CAMILLA_LOG:-/var/lib/whick/run/whick-dsp-pipe.log}"
PIPE_RATE="${WHICK_DSP_PIPE_RATE:-192000}"
PIPE_BITS="${WHICK_DSP_PIPE_BITS:-32}"
DAC_RATE="${WHICK_DAC_ALSA_RATE:-48000}"
PLAYBACK_JSON="/var/lib/whick/run/current-playback.json"

if [ ! -f "$PROFILE" ]; then
  echo "[whick-dsp-pipe] missing profile: $PROFILE" >>"$LOG"
  cat >/dev/null
  exit 0
fi

if ! command -v camilladsp >/dev/null 2>&1; then
  echo "[whick-dsp-pipe] camilladsp not installed — drain" >>"$LOG"
  cat >/dev/null
  exit 0
fi

case "$PIPE_BITS" in
  16) IN_FMT=s16le ;;
  24) IN_FMT=s24le ;;
  *) IN_FMT=s32le ;;
esac

WORK_RATE=48000
if [ -f "$PLAYBACK_JSON" ]; then
  WORK_RATE="$(python3 - <<'PY' 2>/dev/null || echo 48000
import json, os
from pathlib import Path
pipe_rate = int(os.getenv("WHICK_DSP_PIPE_RATE", "192000"))
p = Path("/var/lib/whick/run/current-playback.json")
d = json.loads(p.read_text())
sr = int(d.get("sample_rate") or 44100)
work = max(48000, min(sr, pipe_rate))
print(work)
PY
)"
fi

# Camilla stdin rate = capture_samplerate (전처리 ON 시 devices.samplerate 와 다름)
CAPTURE_RATE="$WORK_RATE"
_capture="$(grep -E '^[[:space:]]*capture_samplerate:' "$PROFILE" 2>/dev/null | head -n1 | awk '{print $2}')"
if [ -n "$_capture" ] && [ "$_capture" -gt 0 ] 2>/dev/null; then
  CAPTURE_RATE="$_capture"
fi

. /app/docker/whick-camilla-rate.sh
OS_RATE="$(whick_camilla_playback_rate "$PROFILE")"

echo "[whick-dsp-pipe] start $(date -Iseconds) pipe=${PIPE_RATE}/${PIPE_BITS} capture=$CAPTURE_RATE os_rate=$OS_RATE dac=$DAC_RATE" >>"$LOG"

. /app/docker/resolve-alsa-device.sh
export WHICK_ALSA_DEVICE_MODE="${WHICK_DSP_ALSA_DEVICE_MODE:-plug}"
ALSA_DEV="$(resolve_alsa_device || true)"
echo "[whick-dsp-pipe] alsa_device=${ALSA_DEV:-none}" >>"$LOG"

if [ -n "$ALSA_DEV" ] && ls /dev/snd/controlC* >/dev/null 2>&1; then
  exec ffmpeg -hide_banner -loglevel error -f "$IN_FMT" -ar "$PIPE_RATE" -ac 2 -i - \
    -f f32le -ar "$CAPTURE_RATE" -ac 2 pipe:1 2>>"$LOG" | \
    camilladsp "$PROFILE" 2>>"$LOG" | \
    ffmpeg -hide_banner -loglevel error -f f32le -ar "$OS_RATE" -ac 2 -i - \
      -af "aresample=${DAC_RATE}:resampler=soxr" -f alsa "${ALSA_DEV}" 2>>"$LOG"
fi

exec ffmpeg -hide_banner -loglevel error -f "$IN_FMT" -ar "$PIPE_RATE" -ac 2 -i - \
  -f f32le -ar "$CAPTURE_RATE" -ac 2 pipe:1 2>>"$LOG" | \
  camilladsp "$PROFILE" 2>>"$LOG" | \
  cat >/dev/null
