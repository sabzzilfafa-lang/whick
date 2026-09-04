#!/usr/bin/env bash
# VIP 맞춤 USB — ISO provision inject 를 docker(whick/xorriso:local)로 실행
# cc-site-api 에는 xorriso/sgdisk 가 없음 → 호스트 dockerd + 이미지로 remaster
set -euo pipefail

ISO=""
BOOT_DIR=""
OUT=""
SETUP_PY=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --iso) ISO="${2:-}"; shift 2 ;;
    --boot-dir) BOOT_DIR="${2:-}"; shift 2 ;;
    --out) OUT="${2:-}"; shift 2 ;;
    --setup-py) SETUP_PY="${2:-}"; shift 2 ;;
    *) echo "unknown: $1" >&2; exit 1 ;;
  esac
done

[[ -n "$ISO" && -f "$ISO" ]] || { echo "ERROR: --iso" >&2; exit 1; }
[[ -n "$BOOT_DIR" && -d "$BOOT_DIR" ]] || { echo "ERROR: --boot-dir" >&2; exit 1; }
OUT="${OUT:-$ISO}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INJECT="$SCRIPT_DIR/inject-provision-into-live-iso.sh"
[[ -f "$INJECT" ]] || { echo "ERROR: missing $INJECT" >&2; exit 1; }

ISO="$(readlink -f "$ISO")"
BOOT_DIR="$(readlink -f "$BOOT_DIR")"
OUT="$(readlink -f "$OUT")"
[[ -n "$SETUP_PY" && -f "$SETUP_PY" ]] && SETUP_PY="$(readlink -f "$SETUP_PY")" || SETUP_PY=""

DOCKER_BIN="${DOCKER_BIN:-docker}"
export DOCKER_HOST="${DOCKER_HOST:-unix:///var/run/docker.sock}"

if ! command -v "$DOCKER_BIN" >/dev/null 2>&1; then
  echo "ERROR: docker CLI missing — mount docker binary + /var/run/docker.sock into API container" >&2
  exit 1
fi

HOST_UID="$(id -u)"
HOST_GID="$(id -g)"

Q_ISO=$(printf '%q' "$ISO")
Q_BOOT=$(printf '%q' "$BOOT_DIR")
Q_OUT=$(printf '%q' "$OUT")
INJECT_CMD="bash /tmp/inject-provision-into-live-iso.sh --iso $Q_ISO --boot-dir $Q_BOOT --out $Q_OUT"
[[ -n "$SETUP_PY" ]] && INJECT_CMD+=" --setup-py $(printf '%q' "$SETUP_PY")"

echo "==> docker inject via whick/xorriso:local"
"$DOCKER_BIN" run --rm \
  -e HOME=/tmp \
  -v /mnt/ssd2:/mnt/ssd2 \
  -v /data:/data \
  -v /mnt/music:/mnt/music \
  -v /tmp:/tmp \
  -v "$INJECT:/tmp/inject-provision-into-live-iso.sh:ro" \
  -w "$(dirname "$ISO")" \
  --entrypoint bash \
  whick/xorriso:local \
  -c "set -euo pipefail
export PATH=/usr/bin:/bin:/usr/local/bin
command -v sgdisk >/dev/null || apk add --no-cache gptfdisk >/dev/null
command -v python3 >/dev/null || apk add --no-cache python3 >/dev/null
$INJECT_CMD
chown ${HOST_UID}:${HOST_GID} $Q_OUT
"
