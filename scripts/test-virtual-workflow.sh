#!/usr/bin/env bash
# 가상 E2E: 파티션 계획 → CC 원격설치(5~7 dry-run) → player → Ollama AI
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAMP="$(TZ=Asia/Seoul date +%Y%m%d-%H%M%S)"
RUN_DIR="/data/whick-ai/sandbox-scratch/runs/virtual-workflow-${STAMP}"
LOG="$RUN_DIR/workflow.log"
FAIL=0
CC="${WHICK_CC_API_URL:-https://admin.whick.org/api/v1}"
PLAYER_URL="${WHICK_PLAYER_URL:-http://127.0.0.1:8080}"

mkdir -p "$RUN_DIR"
die() { echo "  FAIL  $*" | tee -a "$LOG"; FAIL=$((FAIL + 1)); }
ok()  { echo "  PASS  $*" | tee -a "$LOG"; }
section() { echo "" | tee -a "$LOG"; echo "== $* ==" | tee -a "$LOG"; }

section "Whick virtual workflow (partition → install → player → AI)"
echo "log=$LOG" | tee -a "$LOG"

section "1. Partition plan (Phase 5 — disk_plan.py)"
if "$ROOT/uab/scripts/test-disk-plan.sh" >>"$LOG" 2>&1; then
  ok "disk_plan unit tests"
else
  die "disk_plan unit tests"
fi

section "2. Remote install E2E (Phase 5~7 dry-run + CC)"
if WHICK_CC_API_URL="$CC" "$ROOT/uab/scripts/test-remote-install-e2e.sh" >>"$LOG" 2>&1; then
  ok "remote install phases (CC orchestrator)"
else
  die "remote install phases"
fi

section "3. HW ID SSOT"
if "$ROOT/uab/scripts/test-hw-id-verify.sh" >>"$LOG" 2>&1; then
  ok "hw_id verify"
else
  die "hw_id verify"
fi

section "4. Player stack (library · radio · DSP · WebSocket)"
if "$ROOT/scripts/test-player-docker.sh" >>"$LOG" 2>&1; then
  ok "player docker integration"
else
  die "player docker integration"
fi

section "5. Local AI (Ollama gemma4:e2b)"
cd "$ROOT"
ENV_FILE="$ROOT/.env"
if [[ ! -f "$ENV_FILE" ]]; then
  cp "$ROOT/.env.example" "$ENV_FILE"
fi
if ! grep -q '^OLLAMA_URL=' "$ENV_FILE" 2>/dev/null; then
  echo 'OLLAMA_URL=http://ollama:11434' >>"$ENV_FILE"
fi

# 기존 whick-ollama(타 프로젝트)가 있으면 whick_net에 연결해 재사용
if docker ps -a --format '{{.Names}}' | grep -qx whick-ollama; then
  NET="$(docker inspect whick-player --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}' 2>/dev/null || true)"
  if [[ -n "$NET" ]]; then
    docker network connect "$NET" whick-ollama 2>/dev/null || true
  fi
  if grep -q '^OLLAMA_URL=http://ollama:' "$ENV_FILE" 2>/dev/null; then
    sed -i 's|^OLLAMA_URL=.*|OLLAMA_URL=http://whick-ollama:11434|' "$ENV_FILE"
  fi
  ok "reuse existing whick-ollama container"
else
  if docker compose --profile local-ai up -d ollama >>"$LOG" 2>&1; then
    ok "compose ollama (local-ai profile)"
  else
    die "compose ollama start"
  fi
fi

docker compose up -d --force-recreate player >>"$LOG" 2>&1 || die "player recreate for OLLAMA_URL"

ready=0
for i in $(seq 1 40); do
  ai_ok=$(curl -fsS --max-time 8 "$PLAYER_URL/api/dashboard" 2>/dev/null \
    | python3 -c "import json,sys; d=json.load(sys.stdin); print('1' if d.get('ai',{}).get('ok') else '0')" 2>/dev/null || echo 0)
  if [[ "$ai_ok" == "1" ]]; then
    ready=1
    break
  fi
  sleep 3
done
[[ "$ready" -eq 1 ]] && ok "dashboard ai.ok" || die "Ollama unreachable from player (check OLLAMA_URL / network)"

QUERY=$(python3 -c "import urllib.parse; print(urllib.parse.quote('잔잔한 피아노'))")
curl -fsS --max-time 90 "$PLAYER_URL/api/ai-search?q=$QUERY" >/tmp/whick-ai-search.json 2>>"$LOG" || die "GET /api/ai-search"
python3 >>"$LOG" 2>&1 <<'PY'
import json
with open("/tmp/whick-ai-search.json") as f:
    d = json.load(f)
assert d.get("ai", {}).get("ok") is True, d.get("ai")
assert "query" in d and "extracted" in d, d
print(f"  ai-search query={d['query']!r} results={len(d.get('results') or [])}")
PY
ok "GET /api/ai-search (gemma4:e2b)"

section "Summary"
if [[ "$FAIL" -eq 0 ]]; then
  echo "ALL PASS virtual workflow ($LOG)" | tee -a "$LOG"
  exit 0
fi
echo "FAILED: $FAIL check ($LOG)" | tee -a "$LOG"
exit 1
