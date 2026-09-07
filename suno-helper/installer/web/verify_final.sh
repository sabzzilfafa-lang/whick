#!/bin/bash
cd /data/whick-ai/2_control_center/git-home
echo '=== extract scripts from suno-app.html + node check ==='
python3 - <<'PY'
import re, subprocess
from pathlib import Path
for f in ["suno.html", "suno-app.html"]:
    html = Path(f).read_text(encoding="utf-8")
    scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
    Path("/tmp/chk.js").write_text("\n;\n".join(scripts), encoding="utf-8")
    r = subprocess.run(["node", "--check", "/tmp/chk.js"], capture_output=True, text=True)
    print(f, "syntax:", "OK" if r.returncode == 0 else r.stderr[:300])
PY
echo '=== live pages ==='
for u in suno.html suno-app.html; do
  curl -s "https://whick.org/$u" -o /tmp/live.html
  echo "$u bytes: $(wc -c < /tmp/live.html), data-i18n: $(grep -c 'data-i18n' /tmp/live.html), dashBtn: $(grep -c 'dashBtn' /tmp/live.html)"
done
echo '=== Setup.bat content check ==='
curl -s "https://whick.org/dl/suno-helper/Setup.bat" -o /tmp/s.bat
echo "bytes: $(wc -c < /tmp/s.bat), version API call: $(grep -c 'api/suno/version' /tmp/s.bat)"
rm -f /tmp/chk.js /tmp/live.html /tmp/s.bat
echo VERIFY_DONE
