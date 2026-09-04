#!/bin/sh
# 외장 USB DAC — plughw(호환) / hw( bit-perfect 직결)
# WHICK_ALSA_DEVICE_MODE=hw|plug (기본 hw)
# WHICK_CAMILLA_ALSA_DEVICE=auto → USB 자동

_emit_device() {
  _card="$1"
  _dev="$2"
  _mode="${WHICK_ALSA_DEVICE_MODE:-hw}"
  case "$_mode" in
    plug|plughw) printf 'plughw:CARD=%s,DEV=%s\n' "$_card" "$_dev" ;;
    *)           printf 'hw:CARD=%s,DEV=%s\n' "$_card" "$_dev" ;;
  esac
}

_resolve_via_ffmpeg() {
  command -v ffmpeg >/dev/null 2>&1 || return 1
  ffmpeg -hide_banner -sources alsa 2>/dev/null | awk '
    /plughw:CARD=/ {
      if ($0 ~ /HDMI|HD-Audio|hdmi|CARD=Generic|CARD=PCH|NVidia|CARD=NVidia|CARD=HDA|CARD=Intel|CARD=AMD|CARD=acp/) next
      if (match($0, /plughw:CARD=[^,]+/)) {
        s = substr($0, RSTART, RLENGTH)
        sub(/^plughw:CARD=/, "", s)
        print s; exit
      }
    }
  '
}

_resolve_via_aplay() {
  command -v aplay >/dev/null 2>&1 || return 1
  aplay -l 2>/dev/null | awk '
    /USB Audio|USB-Audio/ {
      card=""; dev="0"
      if (match($0, /card [0-9]+: [^ ]+/)) {
        s = substr($0, RSTART, RLENGTH)
        n = split(s, a, " "); card = a[3]
      }
      if (match($0, /device [0-9]+:/)) {
        s = substr($0, RSTART, RLENGTH)
        gsub(/[^0-9]/, "", s); if (s != "") dev = s
      }
      if (card != "") { printf "%s %s\n", card, dev; exit }
    }
  '
}

_resolve_via_proc() {
  _asound="${WHICK_ASOUND_ROOT:-/proc/asound}"
  [ -r "$_asound/cards" ] || return 1
  awk '
    /USB-Audio|USB Audio/ {
      if (match($0, /\[[^]]+\]/)) {
        s = substr($0, RSTART + 1, RLENGTH - 2)
        gsub(/[ \t]+$/, "", s); gsub(/^[ \t]+/, "", s)
        print s; exit
      }
    }
  ' "$_asound/cards" 2>/dev/null
}

resolve_alsa_device() {
  _want="${WHICK_CAMILLA_ALSA_DEVICE:-auto}"

  case "$_want" in
    auto | "" | AUTO) : ;;
    *) echo "$_want"; return 0 ;;
  esac

  _pair="$(_resolve_via_aplay || true)"
  if [ -n "$_pair" ]; then
    _card=$(echo "$_pair" | awk '{print $1}')
    _dev=$(echo "$_pair" | awk '{print $2}')
    _emit_device "$_card" "$_dev"
    return 0
  fi

  _card="$(_resolve_via_proc || true)"
  if [ -n "$_card" ]; then
    _emit_device "$_card" "0"
    return 0
  fi

  _card="$(_resolve_via_ffmpeg || true)"
  if [ -n "$_card" ]; then
    _emit_device "$_card" "0"
    return 0
  fi

  echo ""
  return 1
}

if [ "${1:-}" = "--print" ]; then
  resolve_alsa_device
fi
