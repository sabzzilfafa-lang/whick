#!/usr/bin/env bash
# 노트북(test-750XDA)에서 실행 — 최신 3_product + agent 재빌드
#   curl -fsSL https://whick.org/whick-content/customer/laptop-dev-update.sh | bash
set -euo pipefail

SERVER="${WHICK_SERVER:-whick@ssh.whick.org}"
REMOTE="${WHICK_REMOTE_3PRODUCT:-/data/whick-ai_music_server/3_product/}"
ROOT="${WHICK_INSTALL_ROOT:-$HOME/whick-3product}"
HTTPS_TAR="${WHICK_HTTPS_TAR:-https://whick.org/whick-content/customer/whick-3product-20260612-pullfix.tar.gz}"

ok() { echo "  OK  $*"; }
die() { echo "  NG  $*" >&2; exit 1; }

echo "== Whick laptop dev-update =="
echo "   to $ROOT"
echo ""

command -v docker >/dev/null || die "Docker 없음 — ./scripts/laptop-first-boot.sh 먼저"
mkdir -p "$(dirname "$ROOT")"

sync_ok=0
if command -v rsync >/dev/null; then
  echo "== [1] rsync (SSH IPv4) =="
  export RSYNC_RSH="${RSYNC_RSH:-ssh -4 -o ConnectTimeout=20 -o StrictHostKeyChecking=accept-new}"
  if rsync -avz --delete \
    --exclude '.env' \
    --exclude 'library/incoming/*' \
    --exclude 'dist/' \
    --exclude '.git/' \
    "$SERVER:$REMOTE" "$ROOT/" 2>&1; then
    sync_ok=1
    ok "rsync"
  else
    echo "  ⚠ rsync 실패 — HTTPS tar 로 대체"
  fi
else
  echo "  ⚠ rsync 없음 — HTTPS tar 사용"
fi

if [[ "$sync_ok" != "1" ]]; then
  echo "== [1b] HTTPS tar 다운로드 (ssh 불필요) =="
  command -v curl >/dev/null || die "curl 없음"
  TMP="$(mktemp)"
  curl -fSL4 --max-time 120 "${HTTPS_TAR}?v=$(date +%s)" -o "$TMP" || die "tar 다운로드 실패 — Wi-Fi·whick.org 확인"
  rm -rf "$ROOT"
  tar xzf "$TMP" -C "$(dirname "$ROOT")"
  rm -f "$TMP"
  ok "tar from whick.org"
fi

chmod +x "$ROOT"/scripts/*.sh "$ROOT"/install-whick.sh 2>/dev/null || true

ENV_FILE="$ROOT/.env"
[[ -f "$ENV_FILE" ]] || cp "$ROOT/.env.example" "$ENV_FILE"
# 노트북은 항상 admin.whick.org (localhost:8090 이면 fetch failed)
if grep -q '^WHICK_CC_API_URL=' "$ENV_FILE"; then
  sed -i 's|^WHICK_CC_API_URL=.*|WHICK_CC_API_URL=https://admin.whick.org/api/v1|' "$ENV_FILE"
else
  echo 'WHICK_CC_API_URL=https://admin.whick.org/api/v1' >>"$ENV_FILE"
fi
ok "CC URL → $(grep '^WHICK_CC_API_URL=' "$ENV_FILE")"

echo "== [1c] 관제 연결 사전 확인 =="
curl -4 -sf --max-time 15 https://admin.whick.org/api/system/health | grep -q '"ok":true' \
  || die "Wi-Fi·admin.whick.org 확인 — 정확히: curl -4 -sf https://admin.whick.org/api/system/health"
ok "admin.whick.org reachable"

echo "== [2] agent 토큰 초기화 =="
docker compose -f "$ROOT/compose.yaml" stop agent 2>/dev/null || true
docker run --rm -v whick-runtime_whick-data:/var/lib/whick alpine rm -f /var/lib/whick/runtime-state.json 2>/dev/null || true
ok "state cleared"

echo "== [3] docker build agent + up =="
cd "$ROOT"
export WHICK_SCRIPTS_DIR="$ROOT/scripts"
docker compose --env-file "$ENV_FILE" build agent
docker compose --env-file "$ENV_FILE" up -d --force-recreate agent
sleep 6

echo "== agent env =="
docker inspect whick-agent --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null | grep WHICK_CC || true

echo "== agent 로그 =="
docker logs --tail=15 whick-agent 2>&1 || true

if docker logs whick-agent 2>&1 | tail -8 | grep -qE 'register retry fetch failed|fetch failed'; then
  die "관제 연결 실패 — 노트북에서: curl -4 -sf https://admin.whick.org/api/system/health"
fi
if docker logs whick-agent 2>&1 | tail -5 | grep -q 'AGENT_AUTH_INVALID'; then
  die "토큰 오류 — WHICK_CC_API_URL·Wi-Fi 확인 후 재실행"
fi
if docker logs whick-agent 2>&1 | tail -8 | grep -qE 'registered device_id|heartbeat every|re-registered'; then
  ok "agent 기동"
else
  echo "  ⚠ docker logs -f whick-agent 로 확인"
fi

echo ""
echo "완료. 관제 → https://admin.whick.org/ → 속도 테스트"
