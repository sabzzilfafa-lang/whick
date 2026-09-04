#!/usr/bin/env bash
# USB 설치 패키지 릴리스 — 유선(connect-wired) · 무선(connect-wireless)
#
# 2026-07-26: Alpine zip 폐기 → Ubuntu Whick OS Live ISO
#   wired    → connect-wired    (whick-os-live-wired.iso)
#   wireless → connect-wireless (whick-os-live-wireless.iso, 회원별 provision STA)
# CC 솔루션 whick-os 항목 삭제 — Live는 connect-* 만. rootfs는 music-01 핀.
# See docs/WHICK-OS.md
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPTS="$ROOT/scripts"
CC_SCRIPTS="/data/whick-ai/2_control_center/scripts"
OS_SCRIPTS="/data/whick-ai_music_server/3_product/os/scripts"
# shellcheck source=/dev/null
source "$CC_SCRIPTS/solution-version.sh"

SKIP_PUBLISH=0
NO_BUMP=0
WHICK_USB_PROFILE="${WHICK_USB_PROFILE:-wired}"

case "$WHICK_USB_PROFILE" in
  wired)
    SOLUTION_CODE="connect-wired"
    # 고객 배포 = ISO + USB Maker 한 zip (bare ISO 단독 배포 금지)
    WHICK_CONNECT_ZIP_NAME="${WHICK_CONNECT_ZIP_NAME:-USB설치용-유선.zip}"
    ;;
  wireless)
    SOLUTION_CODE="connect-wireless"
    WHICK_CONNECT_ZIP_NAME="${WHICK_CONNECT_ZIP_NAME:-USB설치용-무선.zip}"
    ;;
  *)
    echo "WHICK_USB_PROFILE must be wired or wireless" >&2
    exit 1
    ;;
esac
export WHICK_USB_PROFILE WHICK_CONNECT_ZIP_NAME SOLUTION_CODE WHICK_SOLUTION_CODE="$SOLUTION_CODE"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-publish) SKIP_PUBLISH=1; shift ;;
    --no-bump) NO_BUMP=1; shift ;;
    *) echo "unknown: $1" >&2; exit 1 ;;
  esac
done

LABEL="$(solution_catalog_field "$SOLUTION_CODE" name_short)"

# 채널 = 판매용/테스트용 구분점. USB 안의 CC 주소는 여기서만 갈린다.
# 맞춤 USB(provision inject)도 live-debug + whick-env 를 공개 URL 로 다시 핀한다.
# 그래도 베이스 ISO 에 localhost 가 박혀 있으면 inject 누락·옛 스크립트 시 사고가 반복된다.
CHANNEL="$(solution_version_field "$SOLUTION_CODE" channel)"
case "$CHANNEL" in
  stable)
    DEFAULT_CC_API_URL="https://admin.whick.org/api/v1"
    CHANNEL_DIST=""  # catalog package.dist_dir 그대로 (/pages/downloads 게시판 대상)
    # 같은 셸에서 test 릴리스를 먼저 돌렸다면 두 변수가 테스트 디렉터리로 남아 있다.
    # WHICK_OS_LIVE_OUT 를 물려받으면 판매 ISO 가 테스트 쪽에 만들어지고,
    # WHICK_CONNECT_CUSTOMER_DIST 를 물려받으면 고객 zip 이 테스트 쪽에 떨어진다.
    # 판매 경로는 항상 스크립트·catalog 기본값으로 고정한다.
    unset WHICK_OS_LIVE_OUT WHICK_CONNECT_CUSTOMER_DIST
    ;;
  test)
    DEFAULT_CC_API_URL="https://test-admin.whick.org/api/v1"
    # 판매 산출물과 섞이면 안 된다 — 테스트 산출물은 SSD2.
    # ISO 파일명(whick-os-live-<profile>.iso)이 채널 구분 없이 같으므로 출력 디렉터리를
    # 함께 옮기지 않으면 테스트 ISO 가 공유 dist/os 의 판매 ISO 를 덮어쓰고,
    # pack-connect-customer-zip.sh 가 그 디렉터리를 1순위로 찾아 판매 zip 에 섞인다.
    CHANNEL_DIST="${WHICK_CONNECT_TEST_DIST:-/mnt/ssd2/whick-cc/whick-dist-test/os}"
    # 상속값을 존중하면(:-) 셸에 판매 디렉터리가 남아 있을 때 테스트 ISO 가 판매 트리에
    # 떨어진다. 출력 위치는 채널이 정하고, 바꾸려면 WHICK_CONNECT_TEST_DIST 를 쓴다.
    export WHICK_OS_LIVE_OUT="$CHANNEL_DIST"
    ;;
  *)
    echo "ERROR: $SOLUTION_CODE channel='$CHANNEL' — test 또는 stable 만 허용" >&2
    exit 1
    ;;
esac
# 셸에 남은 lab 용 127.0.0.1:18095 가 channel 기본을 덮어쓰지 못하게 한다.
if [[ -n "${WHICK_CC_API_URL:-}" ]] && [[ "$WHICK_CC_API_URL" == *127.0.0.1* || "$WHICK_CC_API_URL" == *localhost* ]]; then
  if [[ "${WHICK_ALLOW_LOCALHOST_CC:-0}" != "1" ]]; then
    echo "WARN: ignoring inherited localhost WHICK_CC_API_URL=$WHICK_CC_API_URL — using $DEFAULT_CC_API_URL" >&2
    unset WHICK_CC_API_URL WHICK_CANONICAL_CC_API_URL
  fi
fi
export WHICK_CC_API_URL="${WHICK_CC_API_URL:-$DEFAULT_CC_API_URL}"
export WHICK_CANONICAL_CC_API_URL="${WHICK_CANONICAL_CC_API_URL:-$WHICK_CC_API_URL}"
export WHICK_ALLOW_NON_TUNNEL_CC="${WHICK_ALLOW_NON_TUNNEL_CC:-1}"
if [[ "$WHICK_CC_API_URL" == *127.0.0.1* || "$WHICK_CC_API_URL" == *localhost* ]]; then
  if [[ "${WHICK_ALLOW_LOCALHOST_CC:-0}" != "1" ]]; then
    echo "ERROR: refusing localhost CC URL for channel=$CHANNEL: $WHICK_CC_API_URL" >&2
    exit 1
  fi
fi
if [[ -n "$CHANNEL_DIST" ]]; then
  mkdir -p "$CHANNEL_DIST"
  export WHICK_CONNECT_CUSTOMER_DIST="$CHANNEL_DIST"
fi

# Live ISO 는 live-debug.env 만 source — bootstrap secret 을 여기서 반드시 주입한다.
# stable → 실차 CC_INSTALL_BOOTSTRAP_SECRET / test → CC_TEST_INSTALL_BOOTSTRAP_SECRET
if [[ -z "${WHICK_INSTALL_BOOTSTRAP_SECRET:-}" ]]; then
  local_env_file=""
  local_secret_key=""
  case "$CHANNEL" in
    stable)
      local_env_file="${WHICK_CC_ENV_FILE:-/data/whick-ai/9_env/control-center.env}"
      local_secret_key="CC_INSTALL_BOOTSTRAP_SECRET"
      ;;
    test)
      local_env_file="${WHICK_TEST_ENV_FILE:-/mnt/ssd2/dev/whick-ai/9_env/control-center.test.env}"
      local_secret_key="CC_TEST_INSTALL_BOOTSTRAP_SECRET"
      ;;
  esac
  if [[ -f "$local_env_file" ]]; then
    WHICK_INSTALL_BOOTSTRAP_SECRET="$(
      grep -E "^${local_secret_key}=" "$local_env_file" | head -1 | cut -d= -f2-
    )"
  fi
  export WHICK_INSTALL_BOOTSTRAP_SECRET
fi
if [[ -z "${WHICK_INSTALL_BOOTSTRAP_SECRET:-}" ]]; then
  echo "ERROR: WHICK_INSTALL_BOOTSTRAP_SECRET empty (channel=$CHANNEL) — refuse USB build" >&2
  exit 1
fi

echo "========================================"
echo " Whick USB release — $SOLUTION_CODE ($LABEL)"
echo " channel: $CHANNEL"
echo " cc api : $WHICK_CC_API_URL"
echo " bootstrap secret: set (len=${#WHICK_INSTALL_BOOTSTRAP_SECRET})"
echo " $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "========================================"

PRODUCT_MAP="${WHICK_PRODUCT_MAP:-/data/whick-ai_music_server/3_product/scripts/apply-product-map.py}"
# 설치안내용 리모트포털·판매 remote 표시 버전 = remote-mobile.json SSOT (USB 빌드마다 투영 강제)
# index/config/portal_app 이 어긋난 채로 ISO/zip 이 나가거나 remote.whick.org 가 낡은 문자열을 유지하는 사고 방지
echo ">>> [0/4] product map versions (remote-portal-ui · sales-remote-ui-footer ← remote-mobile)"
python3 "$PRODUCT_MAP" apply --scope versions --version-id remote-portal-ui
python3 "$PRODUCT_MAP" apply --scope versions --version-id sales-remote-ui-footer
python3 "$PRODUCT_MAP" verify --scope versions --version-id remote-portal-ui
python3 "$PRODUCT_MAP" verify --scope versions --version-id sales-remote-ui-footer
if [[ "$CHANNEL" == "stable" && "${WHICK_SKIP_PORTAL_DEPLOY:-0}" != "1" ]]; then
  echo ">>> [0/4] deploy remote-portal (install guide on remote.whick.org matches SSOT version)"
  bash /data/whick-ai_music_server/3_product/packages/remote-portal/scripts/deploy-remote-portal.sh
fi

if [[ "$NO_BUMP" -eq 0 ]]; then
  NEW_VER="$(solution_version_bump "$SOLUTION_CODE" "${WHICK_RELEASE_NOTES:-}")"
  echo ">>> [1/4] bump → ${NEW_VER}"
else
  NEW_VER="$(solution_version_field "$SOLUTION_CODE" version)"
  echo ">>> [1/4] no bump → ${NEW_VER}"
fi
export WHICK_CONNECT_VERSION="$NEW_VER"

echo ">>> [2/4] build Whick OS Live ($WHICK_USB_PROFILE ISO)"
WHICK_OS_NET_PROFILE="$WHICK_USB_PROFILE" bash "$OS_SCRIPTS/build-whick-os-live.sh" --iso
solution_version_json "$SOLUTION_CODE" set-build "$(date +%Y%m%d%H)" >/dev/null

echo ">>> [3/4] pack customer zip (ISO + USB Maker)"
WHICK_USB_PROFILE="$WHICK_USB_PROFILE" WHICK_CONNECT_ZIP_NAME="$WHICK_CONNECT_ZIP_NAME" \
  bash "$SCRIPTS/pack-connect-customer-zip.sh"

echo ">>> [4/4] CC register $SOLUTION_CODE ($WHICK_CONNECT_ZIP_NAME · $CHANNEL)"
if [[ -n "$CHANNEL_DIST" ]]; then
  # catalog dist_dir 은 판매 경로만 가리키므로 test 는 zip 경로를 직접 넘긴다.
  "$CC_SCRIPTS/register-solution-cc.sh" "$SOLUTION_CODE" "$CHANNEL_DIST/$WHICK_CONNECT_ZIP_NAME"
else
  "$CC_SCRIPTS/register-solution-cc.sh" "$SOLUTION_CODE"
fi

if [[ "$CHANNEL" == "test" ]]; then
  # 다운로드 게시판은 stable 등록본만 표시 — 테스트 빌드는 노출하지 않는다.
  echo "OK  $SOLUTION_CODE ${WHICK_CONNECT_VERSION} (channel=test · 다운로드 게시판 미노출)"
  exit 0
fi

if [[ "$SKIP_PUBLISH" -eq 1 ]]; then
  echo "OK  $SOLUTION_CODE ${WHICK_CONNECT_VERSION} (등록 완료 · 다운로드 게시판 자동 반영)"
  exit 0
fi

echo "OK  $SOLUTION_CODE ${WHICK_CONNECT_VERSION} (stable · 다운로드 게시판 자동 반영)"
