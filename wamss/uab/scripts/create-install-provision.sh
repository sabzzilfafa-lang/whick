#!/usr/bin/env bash
# VIP 비밀글 내용 → CC install provision 등록
# 무선 SSOT (2026-07-26): provision.json wifi_ssid/password 만 — Whick-Setup AP 폐기
# Usage:
#   ./create-install-provision.sh --mb-id user@example.com --wired
#   ./create-install-provision.sh --mb-id user@example.com --wireless --ssid 'MyWiFi_2.4G' --password 'secret'
set -euo pipefail

CC_URL="${WHICK_CC_API_URL:-https://admin.whick.org/api/v1}"
CC_SECRET="${WHICK_CC_SITE_SECRET:-${CC_SITE_SECRET:-}}"

MB_ID=""
ACCESS="wired"
SSID=""
PASSWORD=""
VIP_REF=""
NOTES=""

usage() {
  cat <<EOF
Usage: $(basename "$0") --mb-id ID (--wired | --wireless [--ssid SSID --password PASS])

  VIP 비밀글 신청 내용을 CC provision으로 등록합니다.
  무선은 --ssid/--password 필수 (가상 AP로 받는 경로 없음).
  이후: PROVISION_ID=<id> scripts/build-custom-install-usb.sh

Env: WHICK_CC_SITE_SECRET (필수)
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mb-id) MB_ID="${2:-}"; shift 2 ;;
    --wired) ACCESS="wired"; shift ;;
    --wireless) ACCESS="wireless"; shift ;;
    --ssid) SSID="${2:-}"; shift 2 ;;
    --password) PASSWORD="${2:-}"; shift 2 ;;
    --vip-ref) VIP_REF="${2:-}"; shift 2 ;;
    --notes) NOTES="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown: $1" >&2; exit 1 ;;
  esac
done

[[ -n "$MB_ID" ]] || { echo "ERROR: --mb-id required" >&2; exit 1; }
[[ -n "$CC_SECRET" ]] || { echo "ERROR: WHICK_CC_SITE_SECRET required" >&2; exit 1; }
if [[ "$ACCESS" == "wireless" ]]; then
  [[ -n "$SSID" && -n "$PASSWORD" ]] || {
    echo "ERROR: --wireless requires --ssid and --password (Whick-Setup AP retired)" >&2
    exit 1
  }
fi

BODY="$(python3 -c "
import json, os
print(json.dumps({
  'mb_id': os.environ['MB_ID'],
  'access_mode': os.environ['ACCESS'],
  'wifi_ssid': os.environ.get('SSID') or '',
  'wifi_password': os.environ.get('PASSWORD') or '',
  'vip_post_ref': os.environ.get('VIP_REF') or '',
  'staff_notes': os.environ.get('NOTES') or '',
}))
" MB_ID="$MB_ID" ACCESS="$ACCESS" SSID="$SSID" PASSWORD="$PASSWORD" VIP_REF="$VIP_REF" NOTES="$NOTES")"

RES="$(curl -fsSL -X POST \
  -H "Content-Type: application/json" \
  -H "x-cc-site-secret: $CC_SECRET" \
  -d "$BODY" \
  "${CC_URL%/}/install/provisions")"

echo "$RES" | python3 -c "
import json, sys
raw = json.load(sys.stdin)
d = raw.get('data') or raw
print('OK  provision_id=', d.get('provision_id'))
print('    session_id=', d.get('session_id'))
print('    device_code=', d.get('device_code'))
print('')
print('Next: PROVISION_ID=%s $(dirname "$0")/build-custom-install-usb.sh' % d.get('provision_id'))
"
