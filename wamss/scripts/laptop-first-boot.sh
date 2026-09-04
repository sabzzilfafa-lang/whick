#!/usr/bin/env bash
# Ubuntu 26.04 노트북 — UAB Phase 6~7 수동 재현 (Docker + runtime 준비)
# Cursor는 집 PC → 본사 서버 SSH 개발. 노트북 = 고객 미니PC 테스트만.
#
# 사용:
#   USB: whick-laptop-usb/install-from-usb.sh
#   VIP: whick.org VIP Room → whick-3product-*.tar.gz → docs/LAPTOP-INSTALL-VIP.md
#   1) ./scripts/laptop-first-boot.sh   (전원 유지 → Docker)
#   2) ssh -N -L 8090:127.0.0.1:8090 whick@ssh.whick.org
#   3) ./scripts/laptop-test-setup.sh
set -euo pipefail

ROOT="${WHICK_INSTALL_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
WHICK_SCRIPTS_DIR="${WHICK_SCRIPTS_DIR:-$ROOT/scripts}"

echo "==> Whick 노트북 1차 준비 (Ubuntu Desktop · Docker)"
echo "    경로: $ROOT"
echo ""

if [[ "$(id -u)" -eq 0 ]]; then
  echo "root 로 실행하지 마세요. 일반 사용자로: ./scripts/laptop-first-boot.sh"
  exit 1
fi

if [[ "${WHICK_CUSTOMER_MODE:-}" == "1" ]]; then
  echo "==> [1/2] 전원 설정 — 설치 완료·재부팅 후 적용 (설치 중 건너뜀 · 로그아웃 방지)"
else
  echo "==> [1/2] 전원 유지 (절전·뚜껑·전원키) — runtime 연결 전 필수"
  "$WHICK_SCRIPTS_DIR/laptop-power-always-on.sh" apply
fi

echo ""
echo "==> [2/2] Docker · runtime 준비"

if ! grep -qE '^VERSION_ID="(24\.04|26\.04)"' /etc/os-release 2>/dev/null; then
  echo "WARN: Ubuntu 24.04/26.04 LTS 가 아닐 수 있습니다. (/etc/os-release 확인)"
fi

if command -v docker >/dev/null && docker compose version >/dev/null 2>&1; then
  echo "OK  Docker + Compose 이미 설치됨"
  docker --version
  docker compose version
else
  echo "==> Docker CE 설치 (공식 저장소)"
  sudo apt-get update
  sudo apt-get install -y ca-certificates curl gnupg
  sudo install -m 0755 -d /etc/apt/keyrings
  if [[ ! -f /etc/apt/keyrings/docker.gpg ]]; then
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    sudo chmod a+r /etc/apt/keyrings/docker.gpg
  fi
  echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
    $(. /etc/os-release && echo "${VERSION_CODENAME:-noble}") stable" |
    sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
  sudo apt-get update
  sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  echo "OK  Docker 설치 완료"
fi

if ! groups "$USER" | grep -q '\bdocker\b'; then
  sudo usermod -aG docker "$USER"
  echo ""
  if [[ "${WHICK_CUSTOMER_MODE:-}" == "1" ]]; then
    echo "docker 그룹에 추가했습니다. 이 설치는 로그아웃 없이 계속됩니다."
  else
    echo "docker 그룹에 추가했습니다. **로그아웃 후 재로그인** 하거나:"
    echo "  newgrp docker"
    echo ""
  fi
fi

for pkg in curl git rsync; do
  if ! command -v "$pkg" >/dev/null; then
    sudo apt-get install -y "$pkg"
  fi
done

if [[ ! -f "$ROOT/.env" ]]; then
  cp "$ROOT/.env.example" "$ROOT/.env"
  echo "Created $ROOT/.env"
fi

mkdir -p "$ROOT/library/incoming"

cat <<EOF

==> 1차 준비 완료

다음 (노트북):

  # docker 그룹 적용 (재로그인 안 했으면)
  newgrp docker

  # CC 터널 — 집 PC 또는 노트북 터미널에서 유지
  ssh -N -L 8090:127.0.0.1:8090 whick@ssh.whick.org

  # runtime 기동
  cd $ROOT
  ./scripts/laptop-test-setup.sh

확인:
  curl -s http://127.0.0.1:8787/health
  관제: https://admin.whick.org/ → 뮤직서버관제

---
USB: install/bootstrap IMG 전 · **whick-laptop-usb** 번들 (build-laptop-usb.sh).
지금 노트북: **Ubuntu Desktop** → runtime 테스트만.

3_product 복사 (집 PC 예시):
  rsync -avz --exclude .env whick@ssh.whick.org:/data/whick-ai_music_server/3_product/ ~/whick-3_product/
  또는 USB: ./install-from-usb.sh

EOF
