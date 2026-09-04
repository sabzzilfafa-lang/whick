#!/bin/sh
# whick-setup deb — App Center 설치 직후 설치 터미널 자동 실행
set -e

whick_active_user() {
  if [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ]; then
    echo "$SUDO_USER"
    return 0
  fi
  if command -v loginctl >/dev/null 2>&1; then
    u="$(loginctl list-sessions --no-legend 2>/dev/null | awk '$4 == "active" { print $3; exit }')"
    if [ -n "$u" ] && [ "$u" != "root" ]; then
      echo "$u"
      return 0
    fi
  fi
  u="$(users 2>/dev/null | awk '{ print $1 }')"
  [ -n "$u" ] && echo "$u"
}

whick_user_display() {
  u="$1"
  if command -v loginctl >/dev/null 2>&1; then
    d="$(loginctl show-user "$u" -p Display --value 2>/dev/null || true)"
    if [ -n "$d" ]; then
      echo "$d"
      return 0
    fi
  fi
  echo ":0"
}

whick_schedule_install() {
  u="$(whick_active_user)"
  [ -n "$u" ] || return 0
  id -u "$u" >/dev/null 2>&1 || return 0

  home="$(getent passwd "$u" | cut -d: -f6)"
  dl="${home}/Downloads"
  [ -d "${home}/다운로드" ] && dl="${home}/다운로드"

  uid="$(id -u "$u")"
  runtime="/run/user/${uid}"
  disp="$(whick_user_display "$u")"
  dbus="unix:path=${runtime}/bus"

  # App Center 창이 닫힌 뒤, 로그인 사용자로 터미널 설치 실행
  nohup sh -c "
    sleep 5
    if command -v runuser >/dev/null 2>&1; then
      runuser -u '${u}' -- env \
        WHICK_TERM_LAUNCHED=1 WHICK_FROM_DEB=1 WHICK_DOWNLOAD_DIR='${dl}' \
        DISPLAY='${disp}' DBUS_SESSION_BUS_ADDRESS='${dbus}' XDG_RUNTIME_DIR='${runtime}' \
        /usr/lib/whick/launch-install.sh
    fi
  " >/dev/null 2>&1 &
}

case "$1" in
  configure)
    whick_schedule_install
    ;;
esac

exit 0
