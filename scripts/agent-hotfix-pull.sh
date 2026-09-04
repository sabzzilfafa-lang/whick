#!/bin/sh
# 서버 remote pull bootstrap — agent 가동 중 hotfix (통합관제 무영향)
# agent가 runtime을 ro mount 중이면 즉시 stop 불가 → nohup으로 자기 자신 재기동
set -e
TAR="${WHICK_HTTPS_TAR:-https://whick.org/whick-content/customer/whick-3product-20260612-pullfix.tar.gz}"
TMP="/tmp/whick-pull.tar.gz"
ENV_BAK="/tmp/whick-env.bak"
LOG="/tmp/whick-hotfix.log"

resolve_h() {
  for d in /opt/whick/runtime "$HOME/whick-3product"; do
    if [ -f "$d/compose.yaml" ]; then echo "$d"; return; fi
  done
  H="$(docker inspect whick-agent --format '{{range .Mounts}}{{if eq .Destination "/opt/whick/runtime"}}{{.Source}}{{end}}{{end}}' 2>/dev/null || true)"
  if [ -n "$H" ] && [ "$H" != "." ] && [ -d "$(dirname "$H")" ]; then echo "$H"; return; fi
  echo "/opt/whick/runtime"
}

H="$(resolve_h)"
P="$(dirname "$H")"
mkdir -p "$P"
[ -f "$H/.env" ] && cp "$H/.env" "$ENV_BAK"

nohup sh -c "
set -e
sleep 3
docker stop whick-agent whick-audio 2>/dev/null || true
docker run --rm -v /tmp:/tmp curlimages/curl:8.5.0 curl -fSL4 -o '$TMP' '$TAR?v='$(date +%s)
docker run --rm -v /tmp:/tmp -v '$P:$P' alpine sh -c \"set -e; rm -rf '$H' '$P/whick-3product'; mkdir -p '$P'; tar xzf '$TMP' -C '$P'; if [ ! -d '$H' ] && [ -d '$P/whick-3product' ]; then mv '$P/whick-3product' '$H'; fi; test -d '$H'; rm -f '$TMP'\"
if [ -f '$ENV_BAK' ]; then cp '$ENV_BAK' '$H/.env'; rm -f '$ENV_BAK'
elif [ ! -f '$H/.env' ] && [ -f '$H/.env.example' ]; then cp '$H/.env.example' '$H/.env'; fi
grep -q '^WHICK_RUNTIME_HOST_DIR=' '$H/.env' 2>/dev/null && sed -i 's|^WHICK_RUNTIME_HOST_DIR=.*|WHICK_RUNTIME_HOST_DIR=$H|' '$H/.env' || echo 'WHICK_RUNTIME_HOST_DIR=$H' >>'$H/.env'
grep -q admin.whick.org '$H/.env' 2>/dev/null || echo 'WHICK_CC_API_URL=https://admin.whick.org/api/v1' >>'$H/.env'
docker compose -p whick-runtime -f '$H/compose.yaml' --env-file '$H/.env' up -d --build agent audio
echo OK hotfix pull >>'$LOG'
" >"$LOG" 2>&1 &

echo "hotfix-scheduled log=$LOG target=$H"
