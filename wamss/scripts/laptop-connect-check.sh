#!/usr/bin/env bash
# 노트북 관제 연결 진단 — Docker OK인데 fetch failed 일 때
#   curl -fsSL https://whick.org/whick-content/customer/laptop-connect-check.sh | bash
set -euo pipefail

ROOT="${WHICK_INSTALL_ROOT:-$HOME/whick-3product}"
CC="${WHICK_CC_API_URL:-https://admin.whick.org/api/v1}"
HEALTH="${CC%/api/v1}/api/system/health"

fail=0
ok() { echo "  OK  $*"; }
ng() { echo "  NG  $*"; fail=1; }

echo "== Whick 노트북 — 관제 연결 진단 =="
echo ""

echo "[1] 인터넷"
if ping -c1 -W3 8.8.8.8 >/dev/null 2>&1; then ok "ping 8.8.8.8"; else ng "인터넷 없음 — Wi-Fi 확인"; fi

echo "[2] admin.whick.org (IPv4)"
if curl -4 -sf --max-time 15 "$HEALTH" | grep -q '"ok":true'; then
  ok "$HEALTH"
else
  ng "IPv4 접속 실패 — Wi-Fi·DNS·방화벽 확인"
  echo "      시도: curl -4 -v $HEALTH"
fi

echo "[3] admin.whick.org (IPv6, 참고)"
if curl -6 -sf --max-time 8 "$HEALTH" 2>/dev/null | grep -q '"ok":true'; then
  ok "IPv6도 됨"
else
  echo "  --  IPv6 불가 (흔함) — agent는 IPv4 우선 패치 필요"
fi

echo "[4] Docker whick-agent"
if docker ps --format '{{.Names}}' | grep -qx whick-agent; then
  ok "whick-agent 실행 중"
else
  ng "whick-agent 없음 — laptop-dev-update.sh 재실행"
fi

echo "[5] .env WHICK_CC_API_URL"
if [[ -f "$ROOT/.env" ]]; then
  grep '^WHICK_CC_API_URL=' "$ROOT/.env" || true
  if grep -q 'admin.whick.org' "$ROOT/.env" 2>/dev/null; then
    ok "admin.whick.org 설정됨"
  else
    ng ".env가 localhost 등 — 수정 필요"
  fi
else
  ng "$ROOT/.env 없음"
fi

echo "[6] agent 컨테이너 env"
docker inspect whick-agent --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null \
  | grep WHICK_CC_API_URL || ng "컨테이너 env 확인 불가"

echo "[7] agent 로그 (최근)"
docker logs whick-agent --tail 8 2>&1 | sed 's/^/      /' || true

echo ""
if [[ "$fail" == "0" ]] && docker logs whick-agent 2>&1 | tail -3 | grep -qE 'registered|heartbeat every'; then
  echo "== 연결 정상 — 관제 admin.whick.org 에서 test-750XDA 확인 =="
elif [[ "$fail" == "0" ]]; then
  echo "== 네트워크는 OK — agent 재기동 시도 =="
  echo ""
  echo "  cd $ROOT && docker compose --env-file .env up -d --build agent"
  echo "  sleep 5 && docker logs whick-agent --tail 10"
  echo ""
  echo "또는:"
  echo "  curl -fsSL https://whick.org/whick-content/customer/laptop-dev-update.sh | bash"
else
  echo "== NG 항목 먼저 해결 (대부분 Wi-Fi 또는 IPv4/admin.whick.org) =="
fi

exit "$fail"
