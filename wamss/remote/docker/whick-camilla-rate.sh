#!/bin/sh
# profile.yml devices.samplerate — CamillaDSP stdout rate (전처리 ON 시 384000)
whick_camilla_playback_rate() {
  _prof="${1:-/var/lib/whick/camilla/profile.yml}"
  if [ ! -f "$_prof" ]; then
    echo 48000
    return
  fi
  _r=$(grep -E '^  samplerate:' "$_prof" 2>/dev/null | head -n1 | awk '{print $2}')
  if [ -n "$_r" ] && [ "$_r" -gt 0 ] 2>/dev/null; then
    echo "$_r"
  else
    echo 48000
  fi
}
