#!/usr/bin/env bash
# Whick runtime dev — 3_product only (5_site / CC 미수정)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

ENV_FILE="${WHICK_ENV_FILE:-$ROOT/.env}"
if [[ ! -f "$ENV_FILE" ]]; then
  cp "$ROOT/.env.example" "$ENV_FILE"
  echo "Created $ENV_FILE — edit WHICK_CC_API_URL if needed"
fi

mkdir -p "$ROOT/library/incoming"

echo "==> docker compose config"
docker compose --env-file "$ENV_FILE" config >/dev/null

echo "==> build + up (player + local-ai)"
docker compose --env-file "$ENV_FILE" --profile local-ai up -d --build

echo "==> logs (agent register → monitor snapshot)"
sleep 3
docker compose --env-file "$ENV_FILE" logs --tail=20 agent monitor audio
