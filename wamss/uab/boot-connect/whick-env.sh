#!/bin/sh
# Whick offline tools — Live ISO /usr·lib 와 분리 (apkovl fsck 충돌 방지)
WHICK_MINI="${WHICK_MINI:-/opt/whick-boot-connect/mini}"
if [ -d "$WHICK_MINI/usr/bin" ] || [ -d "$WHICK_MINI/bin" ]; then
  PATH="$WHICK_MINI/bin:$WHICK_MINI/usr/bin:$WHICK_MINI/usr/sbin:$WHICK_MINI/sbin:$PATH"
  export PATH
  _lp="$WHICK_MINI/usr/lib:$WHICK_MINI/lib"
  if [ -n "${LD_LIBRARY_PATH:-}" ]; then
    LD_LIBRARY_PATH="$_lp:$LD_LIBRARY_PATH"
  else
    LD_LIBRARY_PATH="$_lp"
  fi
  export LD_LIBRARY_PATH
fi

# mini python3 → HTTPS (admin.whick.org) — apkovl /etc/ssl 우선
for _ca in \
  /etc/ssl/certs/ca-certificates.crt \
  "${WHICK_MINI}/etc/ssl/certs/ca-certificates.crt"; do
  if [ -f "$_ca" ]; then
    SSL_CERT_FILE="$_ca"
    export SSL_CERT_FILE
    break
  fi
done

# HW ID — 서버 CC_INSTALL_SKIP_HW=0 과 쌍 (기본: 메인보드 DMI SSOT)
export WHICK_SKIP_HW_ID="${WHICK_SKIP_HW_ID:-0}"

# 설치 세션 생성 시크릿 — 서버 CC_INSTALL_BOOTSTRAP_SECRET 과 동일 값(USB 빌드 시 주입)
# 비어 있으면 POST /install/sessions 가 401 됩니다.
export WHICK_INSTALL_BOOTSTRAP_SECRET="${WHICK_INSTALL_BOOTSTRAP_SECRET:-}"

# 실디스크 Ubuntu 설치 — apkovl 빌드 시 WHICK_PROD_INSTALL=1 로 고정 (고객 USB)
export WHICK_PROD_INSTALL="${WHICK_PROD_INSTALL:-1}"
# Wave C — install device WS push (poll fallback 유지)
export WHICK_CC_INSTALL_PUSH="${WHICK_CC_INSTALL_PUSH:-1}"
if [ "${WHICK_PROD_INSTALL}" = "1" ]; then
  export WHICK_LINUX_INSTALL_DRY_RUN=0
  export WHICK_ALLOW_LIVE_DISK_APPLY=1
  export WHICK_DISK_APPLY=1
else
  export WHICK_LINUX_INSTALL_DRY_RUN="${WHICK_LINUX_INSTALL_DRY_RUN:-1}"
fi

# 레거시: 파티션 apply만 (bootstrap 없음)
if [ "${WHICK_REAL_DISK_INSTALL:-0}" = "1" ]; then
  export WHICK_LINUX_INSTALL_DRY_RUN=0
  export WHICK_ALLOW_LIVE_DISK_APPLY=1
  export WHICK_DISK_APPLY=1
fi
