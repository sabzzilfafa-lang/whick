#!/bin/bash
# nginx: /dl/suno-helper/Setup.bat (attachment) 추가 + html/Setup.bat 배포
set -e
GIT_HOME=/data/whick-ai/2_control_center/git-home

echo '=== 1. deploy pages ==='
cp "$GIT_HOME/index.html" "$GIT_HOME/index.html.bak-suno2"
ls -la "$GIT_HOME/suno.html" "$GIT_HOME/suno-app.html" 2>/dev/null || true

echo '=== 2. nginx Setup.bat route ==='
CONF=/data/whick-ai/2_control_center/git-home/nginx/default.conf
cp "$CONF" "${CONF}.bak-setup"
if ! grep -q 'suno-helper/Setup.bat' "$CONF"; then
  python3 - <<'PY'
from pathlib import Path
p = Path("/data/whick-ai/2_control_center/git-home/nginx/default.conf")
src = p.read_text(encoding="utf-8")
anchor = "  location /dl/ {"
block = """  # Suno Helper one-click downloader (always latest, attachment)
  location = /dl/suno-helper/Setup.bat {
    alias /opt/solutions/suno-helper/Setup.bat;
    add_header Content-Disposition 'attachment; filename="SunoHelper-Setup.bat"';
    add_header X-Content-Type-Options "nosniff" always;
    default_type application/octet-stream;
  }

"""
assert anchor in src, "anchor not found"
src = src.replace(anchor, block + anchor, 1)
p.write_text(src, encoding="utf-8")
print("nginx conf updated")
PY
else
  echo "already present"
fi

echo '=== 3. place Setup.bat in SSOT ==='
ls -la /mnt/music/whick-cc/solutions/suno-helper/Setup.bat 2>/dev/null || echo '(will be scp-ed separately)'

echo '=== 4. reload nginx ==='
docker exec whick-git-web nginx -t 2>&1 | head -3
docker exec whick-git-web nginx -s reload 2>&1 | head -2
sleep 1
curl -s -o /dev/null -w "Setup.bat HTTP %{http_code} type=%{content_type}\n" "https://whick.org/dl/suno-helper/Setup.bat"
curl -s -o /dev/null -w "suno.html HTTP %{http_code}\n" "https://whick.org/suno.html"
curl -s -o /dev/null -w "suno-app.html HTTP %{http_code}\n" "https://whick.org/suno-app.html"
echo NGINX_DONE
