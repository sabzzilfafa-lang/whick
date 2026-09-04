#!/usr/bin/env bash
# 노트북에서 실행 — cloudflared quick tunnel로 SSH를 본사에 노출 (선택, 전체 shell용)
#   curl -fsSL https://whick.org/whick-content/customer/laptop-dev-tunnel.sh | bash
set -euo pipefail

CC_URL="${WHICK_CC_API_URL:-https://admin.whick.org/api/v1}"
SSH_USER="${WHICK_TUNNEL_SSH_USER:-$(whoami)}"
SSH_PORT="${WHICK_TUNNEL_SSH_PORT:-22}"
LOG="/tmp/whick-dev-tunnel.log"
PIDFILE="/tmp/whick-dev-tunnel.pid"

ok() { echo "  OK  $*"; }
die() { echo "  NG  $*" >&2; exit 1; }

command -v cloudflared >/dev/null || die "cloudflared 없음 — https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/"
command -v docker >/dev/null || die "docker 없음"

TOKEN=""
if docker ps --format '{{.Names}}' | grep -qx whick-agent; then
  TOKEN="$(docker exec whick-agent cat /var/lib/whick/runtime-state.json 2>/dev/null \
    | python3 -c "import json,sys; print(json.load(sys.stdin).get('token',''))" 2>/dev/null || true)"
fi
[[ -n "$TOKEN" ]] || die "agent 토큰 없음 — whick-agent 기동·등록 후 재시도"

if [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  die "이미 tunnel 실행 중 (pid $(cat "$PIDFILE")) — kill $(cat "$PIDFILE") 후 재시도"
fi

echo "== Whick dev tunnel (cloudflared quick) =="
echo "   SSH localhost:${SSH_PORT} → 본사 관제 meta.dev_tunnel"
echo ""

: >"$LOG"
cloudflared tunnel --url "tcp://127.0.0.1:${SSH_PORT}" >>"$LOG" 2>&1 &
CF_PID=$!
echo "$CF_PID" >"$PIDFILE"

HOST=""
for i in $(seq 1 30); do
  sleep 1
  HOST="$(grep -oE '[a-z0-9-]+\.trycloudflare\.com' "$LOG" | head -1 || true)"
  [[ -n "$HOST" ]] && break
done

[[ -n "$HOST" ]] || { kill "$CF_PID" 2>/dev/null || true; rm -f "$PIDFILE"; die "tunnel URL 파싱 실패 — cat $LOG"; }
ok "tunnel host: $HOST"

BODY="$(python3 -c "import json; print(json.dumps({'host':'${HOST}','ssh_user':'${SSH_USER}','ssh_port':${SSH_PORT},'tunnel_type':'cloudflared-quick'}))")"
HTTP="$(curl -fsSL4 -w '%{http_code}' -o /tmp/whick-tunnel-res.json \
  -X POST "${CC_URL}/agent/dev-tunnel" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "$BODY")"

[[ "$HTTP" == "200" ]] || die "등록 실패 HTTP $HTTP — $(cat /tmp/whick-tunnel-res.json 2>/dev/null)"
ok "관제 등록 완료 (device meta.dev_tunnel)"

echo ""
echo "본사 서버에서:"
echo "  /data/whick-ai/2_control_center/scripts/remote-laptop-ops.sh tunnel <DEVICE_ID>"
echo ""
echo "tunnel 종료: kill $CF_PID && rm -f $PIDFILE"
echo "로그: tail -f $LOG"
