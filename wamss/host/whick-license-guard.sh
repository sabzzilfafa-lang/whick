#!/bin/sh
# Whick runtime license gate (v0.2 stub — wired USB v0.1.40+ 문서·다음 패치용)
#
# 목적: register-product·HW attest·CC policy 없이 whick-audio/runtime 기동 차단
#       (SSD 통째 복제 → 타 PC, grace_no_attest, suspended_*)
#
# 연동 예정:
#   - systemd ExecStartPre / docker compose wrapper
#   - agent: attest 실패 시 compose stop whick-audio whick-runtime
#
# Exit: 0 = 기동 허용 · 1 = 차단 (compose stop)
set -eu

STATE_FILE="${WHICK_RUNTIME_STATE:-/var/lib/whick/runtime-state.json}"
GUARD_MODE="${WHICK_LICENSE_GUARD_MODE:-enforce}" # enforce | warn | off
CC_POLICY_URL="${WHICK_CC_POLICY_URL:-}"

log() { echo "[whick-license-guard] $*" >&2; }

# --- v0.2: CC GET /agent/policy (agent token 필요) ---
check_cc_policy() {
  [ -n "$CC_POLICY_URL" ] || return 0
  # TODO v0.2: curl + agent bearer token → license_status active only
  return 0
}

# --- 로컬 캐시 (agent가 policy 반영 후 runtime-state.json 갱신) ---
check_local_state() {
  [ -f "$STATE_FILE" ] || {
    log "no runtime-state — pending install (allow boot USB phase)"
    return 0
  }
  status="$(python3 - <<'PY' 2>/dev/null || echo active
import json, os, sys
p = os.environ.get("STATE_FILE", "/var/lib/whick/runtime-state.json")
try:
    d = json.load(open(p))
except Exception:
    sys.exit(0)
print(str(d.get("license_status") or d.get("licenseStatus") or "active").lower())
PY
)"
  case "$status" in
    active|warn_mac_only|pending) return 0 ;;
    grace_no_attest)
      log "grace_no_attest — playback allowed until grace deadline (v0.2 timer TBD)"
      return 0
      ;;
    suspended_*|revoked|expired)
      log "blocked: license_status=$status"
      return 1
      ;;
    *) return 0 ;;
  esac
}

main() {
  case "$GUARD_MODE" in
    off) exit 0 ;;
    warn)
      check_local_state || log "WARN would block (enforce in v0.2)"
      check_cc_policy || true
      exit 0
      ;;
  esac
  check_local_state || exit 1
  check_cc_policy || exit 1
  exit 0
}

export STATE_FILE
main "$@"
