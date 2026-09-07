#!/bin/bash
# index.html modal: suno.html(셸)이 아닌 suno-app.html(대시보드 본문)을 iframe으로 로드
set -e
python3 - <<'PY'
from pathlib import Path
p = Path("/data/whick-ai/2_control_center/git-home/index.html")
src = p.read_text(encoding="utf-8")
changed = False
if "frame.src = '/suno.html'" in src:
    src = src.replace("frame.src = '/suno.html'", "frame.src = '/suno-app.html'")
    changed = True
if 'href="/suno.html"' in src:
    src = src.replace('href="/suno.html"', 'href="/suno-app.html"')
    changed = True
p.write_text(src, encoding="utf-8")
print("modal updated" if changed else "no change")
PY
grep -c "suno-app.html" /data/whick-ai/2_control_center/git-home/index.html
echo IDX_DONE
