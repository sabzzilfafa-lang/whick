#!/usr/bin/env bash
# Ubuntu 노트북·미니PC — 관제 runtime 상시 가동
# 절전/최대절전 해제 · 뚜껑 닫아도 유지 · 전원/슬립 키 무시
#
# USB install-from-usb.sh · laptop-first-boot.sh 에서 Docker보다 먼저 실행.
# sudo 필요 (logind · sleep.conf)
set -euo pipefail

LOGIND_DROP=/etc/systemd/logind.conf.d/whick-always-on.conf
SLEEP_DROP=/etc/systemd/sleep.conf.d/whick-no-sleep.conf
MASK_TARGETS=(sleep.target suspend.target hibernate.target hybrid-sleep.target)

usage() {
  cat <<'EOF'
Usage: ./scripts/laptop-power-always-on.sh [apply|write-config-only|status]

  apply              — 절전 해제·뚜껑/전원키 무시 (전체 적용)
  write-config-only  — 설정 파일만 기록 (고객 설치 · 로그아웃 방지)
  status             — 현재 설정 요약

고객 미니PC·테스트 노트북(test-750XDA)은 runtime·CC 연결 유지가 우선입니다.
물리 전원 버튼 5초 이상 = 하드웨어 차단은 BIOS/펌웨어 영역이라 막을 수 없습니다.
EOF
}

show_status() {
  echo "==> Whick 전원·절전 상태"
  if [[ -f "$LOGIND_DROP" ]]; then
    echo "--- $LOGIND_DROP ---"
    grep -E '^(Handle|Idle)' "$LOGIND_DROP" 2>/dev/null || true
  else
    echo "logind drop-in: (미적용)"
  fi
  if [[ -f "$SLEEP_DROP" ]]; then
    echo "--- $SLEEP_DROP ---"
    cat "$SLEEP_DROP"
  else
    echo "sleep.conf drop-in: (미적용)"
  fi
  echo "--- masked targets ---"
  for t in "${MASK_TARGETS[@]}"; do
    systemctl is-enabled "$t" 2>/dev/null || echo "$t ?"
  done
  if command -v gsettings >/dev/null; then
    echo "--- GNOME (현재 사용자) ---"
    gsettings get org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type 2>/dev/null || true
    gsettings get org.gnome.settings-daemon.plugins.power sleep-inactive-battery-type 2>/dev/null || true
    gsettings get org.gnome.desktop.session idle-delay 2>/dev/null || true
  fi
}

apply_gnome_session() {
  if ! command -v gsettings >/dev/null; then
    return 0
  fi
  # 데스크톱 세션이 없으면 건너뜀 (SSH만)
  if [[ -z "${DBUS_SESSION_BUS_ADDRESS:-}" && -z "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" ]]; then
    echo "SKIP GNOME gsettings (GUI 세션 없음 — 로그인 후 한 번 더 apply 권장)"
    return 0
  fi
  echo "==> GNOME 자동 절전 해제"
  gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type 'nothing' || true
  gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-battery-type 'nothing' || true
  gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-timeout 0 || true
  gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-battery-timeout 0 || true
  gsettings set org.gnome.desktop.session idle-delay 0 || true
}

apply_system_files_only() {
  echo "==> 전원 설정 파일만 기록 (logind 재시작·mask 없음)"
  sudo mkdir -p /etc/systemd/logind.conf.d /etc/systemd/sleep.conf.d

  sudo tee "$LOGIND_DROP" >/dev/null <<'EOF'
# Whick customer runtime — suspend on lid/power blocked
[Login]
HandleLidSwitch=ignore
HandleLidSwitchExternalPower=ignore
HandleLidSwitchDocked=ignore
HandlePowerKey=ignore
HandleSuspendKey=ignore
HandleHibernateKey=ignore
IdleAction=ignore
IdleActionSec=0
EOF

  sudo tee "$SLEEP_DROP" >/dev/null <<'EOF'
[Sleep]
AllowSuspend=no
AllowHibernation=no
AllowHybridSleep=no
AllowSuspendThenHibernate=no
EOF
  echo "   OK  재부팅 후 전원 설정 적용"
}

apply_system() {
  echo "==> systemd-logind — 뚜껑·전원·슬립 키 → 무시"
  sudo mkdir -p /etc/systemd/logind.conf.d /etc/systemd/sleep.conf.d

  sudo tee "$LOGIND_DROP" >/dev/null <<'EOF'
# Whick customer runtime — suspend on lid/power blocked
[Login]
HandleLidSwitch=ignore
HandleLidSwitchExternalPower=ignore
HandleLidSwitchDocked=ignore
HandlePowerKey=ignore
HandleSuspendKey=ignore
HandleHibernateKey=ignore
IdleAction=ignore
IdleActionSec=0
EOF

  sudo tee "$SLEEP_DROP" >/dev/null <<'EOF'
[Sleep]
AllowSuspend=no
AllowHibernation=no
AllowHybridSleep=no
AllowSuspendThenHibernate=no
EOF

  echo "==> sleep/suspend/hibernate target mask"
  for t in "${MASK_TARGETS[@]}"; do
    sudo systemctl mask "$t" 2>/dev/null || true
  done

  echo "==> systemd-logind 설정 반영 (재시작 없음 — 로그아웃 방지)"
  # restart systemd-logind 는 GUI 세션을 끊어 로그아웃됨 → ReloadConfiguration 만 사용
  if sudo busctl call org.freedesktop.login1 /org/freedesktop/login1 \
      org.freedesktop.login1.Manager ReloadConfiguration >/dev/null 2>&1; then
    echo "   OK  logind 설정 반영"
  else
    echo "   ⚠ logind 즉시 반영 실패 — 재부팅 후 전원 설정 완전 적용"
  fi
}

apply_systemd_inhibit_hint() {
  cat <<'EOF'

선택 — 부팅 시 Docker 전에 한 번 더 막기 (이미 logind로 대부분 충분):
  sudo systemctl enable whick-no-sleep.service   # 추후 패키지화 시

EOF
}

main() {
  local cmd="${1:-apply}"
  case "$cmd" in
    write-config-only)
      apply_system_files_only
      ;;
    apply)
      echo "==> Whick 전원 유지 (절전 해제 · 뚜껑 닫아도 가동)"
      apply_system
      apply_gnome_session
      echo ""
      echo "OK  적용 완료"
      echo "  · 뚜껑 닫음 → 절전/종료 안 함"
      echo "  · 전원/슬립 키 → OS 동작 없음 (5초 강제 전원은 펌웨어)"
      echo "  · 화면은 꺼질 수 있음 — runtime(agent)은 계속 동작"
      show_status
      apply_systemd_inhibit_hint
      ;;
    status)
      show_status
      ;;
    -h | --help | help)
      usage
      ;;
    *)
      echo "Unknown: $cmd" >&2
      usage >&2
      exit 1
      ;;
  esac
}

main "$@"
