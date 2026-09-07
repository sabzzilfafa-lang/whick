#!/bin/bash
set -e
CC=/data/whick-ai/2_control_center
VER=1.1.0

echo '=== 1. catalog update (1.0.x -> 1.1.x, zip_name) ==='
python3 - <<'PY'
import json
p = "/data/whick-ai/2_control_center/config/solutions-catalog.json"
c = json.load(open(p, encoding="utf-8"))
e = c["solutions"]["suno-helper"]
e["version_semver"] = "1.1.x"
e["package"]["zip_name"] = "SunoHelper-Setup-v1.1.0.zip"
json.dump(c, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("catalog:", e["version_semver"], e["package"]["zip_name"])
PY

echo '=== 2. version file update ==='
cat > "$CC/config/solutions/suno-helper.json" <<EOF
{
  "product": "suno-helper",
  "version": "$VER",
  "notes": "Web-driven install: Setup.bat one-click downloader, suno-helper:// protocol launch from whick.org, local direct-run guard",
  "url": "https://whick.org/dl/suno-helper/v$VER/wamss-current.zip",
  "released_at": "$(date -u +%Y-%m-%dT%H:%M:%S.000Z)"
}
EOF
cat "$CC/config/solutions/suno-helper.json"

echo '=== 3. how does site-api read version file? ==='
docker exec whick-cc-site-api sh -c "grep -rn 'suno-helper\|/config/solutions' /app/src 2>/dev/null | head -10" || true
echo '=== 4. version API check ==='
curl -s https://whick.org/api/suno/version
echo
echo REG2_DONE
