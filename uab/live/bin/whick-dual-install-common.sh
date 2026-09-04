#!/usr/bin/env bash
# Whick 설치 공통 — CC 우선(디폴트) · 인터넷은 동일 핀 비상 폴백
# 정책: cc_first_internet_emergency
set -euo pipefail

WHICK_ONLINE_INSTALL_TIMEOUT="${WHICK_ONLINE_INSTALL_TIMEOUT:-180}"

dual_log() { echo "[whick-install] $*"; }

cc_api_base() {
  echo "${WHICK_CC_API_URL:-https://admin.whick.org/api/v1}"
}

cc_artifact_url() {
  local name="$1"
  local base
  base="$(basename "$name")"
  # 공개 cdn이 더 안정적 — auth 없이 Cloudflare edge에서 직접
  echo "https://whick.org/downloads/$base"
}
cc_api_artifact_url() {
  local name="$1"
  echo "$(cc_api_base)/install/bootstrap/artifact/$(basename "$name")"
}

read_lock_json() {
  local lock="${WHICK_COMPONENTS_LOCK:-/opt/whick/runtime/components.lock.json}"
  [[ -f "$lock" ]] || return 1
  python3 -c "import json; print(json.dumps(json.load(open('$lock'))))"
}

# Docker CE — apt/docker.com 핀 버전 (비상 폴백 전용 · 디폴트는 CC deb)
# 정책: cc_first_internet_emergency · latest 금지
try_online_docker_ce() {
  local lock_json docker_ver compose_ver codename
  lock_json="$(read_lock_json || echo '{}')"
  docker_ver="$(python3 -c "import json,sys; c=json.loads(sys.argv[1]); print(c.get('components',{}).get('docker_ce',{}).get('version',''))" "$lock_json")"
  compose_ver="$(python3 -c "import json,sys; c=json.loads(sys.argv[1]); print(c.get('components',{}).get('docker_compose_plugin',{}).get('version',''))" "$lock_json")"
  codename="$(python3 -c "import json,sys; c=json.loads(sys.argv[1]); print((c.get('host_os') or {}).get('codename','resolute'))" "$lock_json")"
  [[ -n "$docker_ver" && -n "$compose_ver" ]] || return 1

  dual_log "online docker attempt (pinned) codename=$codename"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq ca-certificates curl gnupg
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL --connect-timeout 20 --max-time 60 https://download.docker.com/linux/ubuntu/gpg \
    | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu ${codename} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt-get install -y --no-install-recommends \
    "docker-ce=${docker_ver}" \
    "docker-ce-cli=${docker_ver}" \
    "docker-compose-plugin=${compose_ver}" \
    containerd.io \
    docker-buildx-plugin
  command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1
}

docker_ready() {
  command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1
}

verify_file_sha256() {
  local file="$1" expected="$2"
  [[ -n "$expected" && -f "$file" ]] || return 0
  local got
  got="$(sha256sum "$file" | awk '{print $1}')"
  [[ "$got" == "$expected" ]]
}
