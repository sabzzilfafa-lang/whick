#!/bin/bash
# b64 복원만 먼저 (검증 없이)
python3 - <<'PY'
import base64, re
from pathlib import Path
raw = Path('/tmp/payload.sh').read_text()
def grab(key):
    m = re.search(key + r'=(\S+)', raw)
    return base64.b64decode(m.group(1)).decode('utf-8')
sec = grab('SECTION_B64')
js = grab('JS_B64')
Path('/tmp/account_suno_section.html').write_text(sec, encoding='utf-8')
Path('/tmp/account_suno_script.js').write_text(js, encoding='utf-8')
print('restored', len(sec), len(js))
PY
python3 /tmp/rebuild_account.py 2>&1 | tail -3
echo "==== 서버 파일에서 직접 확인 ===="
python3 -c "
from pathlib import Path
src = Path('/data/whick-ai/2_control_center/git-home/account.html').read_text(encoding='utf-8')
print('korean section:', '내 PC 등록' in src)
print('korean button:', '활성화 토큰 발급' in src)
print('korean status:', '등록된 PC가 없습니다' in src)
"
echo B64_RESTORE_DONE
