#!/usr/bin/env bash
# deb 설치 후 · 앱 메뉴 「Whick 설치」 — 본격 설치 시작
export WHICK_TERM_LAUNCHED=1
export WHICK_FROM_DEB=1

if [ -z "${WHICK_DOWNLOAD_DIR:-}" ]; then
  dl="$(xdg-user-dir DOWNLOAD 2>/dev/null || true)"
  [ -d "$HOME/다운로드" ] && dl="$HOME/다운로드"
  [ -n "$dl" ] && export WHICK_DOWNLOAD_DIR="$dl"
fi

if [[ -t 1 ]]; then
  exec bash /usr/lib/whick/customer-install.sh
fi

for term in gnome-terminal x-terminal-emulator konsole xfce4-terminal xterm; do
  if command -v "$term" >/dev/null 2>&1; then
    case "$term" in
      gnome-terminal)
        exec gnome-terminal --title="Whick 설치" -- bash -lc '/usr/lib/whick/customer-install.sh; echo; read -r -p "Enter로 종료…" _'
        ;;
      *)
        exec "$term" -e bash -lc '/usr/lib/whick/customer-install.sh; echo; read -r -p "Enter로 종료…" _'
        ;;
    esac
  fi
done
exec bash /usr/lib/whick/customer-install.sh
