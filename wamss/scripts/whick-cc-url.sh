#!/usr/bin/env bash
# CC API URL 자동 선택 · .env 반영
# shellcheck disable=SC2034
WHICK_CC_LOCAL="${WHICK_CC_LOCAL:-http://127.0.0.1:8090/api/v1}"
WHICK_CC_DIRECT="${WHICK_CC_DIRECT:-https://admin.whick.org/api/v1}"

whick_cc_health_ok() {
  local base="${1%/}"
  curl -sf --max-time "${2:-4}" "${base}/system/health" >/dev/null 2>&1
}

whick_resolve_cc_url() {
  if whick_cc_health_ok "$WHICK_CC_LOCAL" 2; then
    echo "$WHICK_CC_LOCAL"
    return 0
  fi
  if whick_cc_health_ok "$WHICK_CC_DIRECT" 5; then
    echo "$WHICK_CC_DIRECT"
    return 0
  fi
  return 1
}

whick_set_env_cc_url() {
  local env_file="$1"
  local example="${2:-}"
  local url
  url="$(whick_resolve_cc_url)" || return 1
  if [[ ! -f "$env_file" ]]; then
    if [[ -n "$example" && -f "$example" ]]; then
      cp -f "$example" "$env_file"
    else
      touch "$env_file"
    fi
  fi
  if grep -q '^WHICK_CC_API_URL=' "$env_file"; then
    sed -i "s|^WHICK_CC_API_URL=.*|WHICK_CC_API_URL=${url}|" "$env_file"
  else
    echo "WHICK_CC_API_URL=${url}" >>"$env_file"
  fi
  echo "$url"
}

whick_docker_ready() {
  command -v docker >/dev/null && docker compose version >/dev/null 2>&1 && docker ps >/dev/null 2>&1
}

whick_with_docker() {
  if whick_docker_ready; then
    "$@"
    return $?
  fi
  if groups 2>/dev/null | grep -q '\bdocker\b'; then
    exec sg docker -c "$(printf '%q ' "$@")"
  fi
  echo "Docker 그룹 권한이 없습니다. 터미널을 닫고 다시 로그인하거나: newgrp docker" >&2
  return 1
}
