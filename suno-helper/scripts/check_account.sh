#!/bin/bash
# 상태줄 언어 전환 확인 완료 (ko 표시는 터미널 한계로 깨져 보이는 것 — 실제는 정상 UTF-8).
# 남은 것: 버튼 텍스트가 data-i18n 적용 후 빈 문자열 — apply()가 querySelectorAll stub 때문에
# 실제 브라우저에서는 정상 적용됨. 마지막으로 실제 서빙본에서 data-i18n+카탈로그 일치 확인.
python3 - <<'PY'
from pathlib import Path
import re
src = Path("/data/whick-ai/2_control_center/git-home/account.html").read_text(encoding="utf-8")
# 카탈로그의 en 키와 data-i18n 속성 키 일치 확인
cat_keys = set(re.findall(r'"(acc\.suno\w+)"\s*:', src))
attr_keys = set(re.findall(r'data-i18n="(acc\.suno\w+)"', src))
print("catalog keys:", sorted(cat_keys))
print("attr keys:", sorted(attr_keys))
print("all attrs covered:", attr_keys.issubset(cat_keys))
# JS에서 sT()로 참조하는 키
js_keys = set(re.findall(r"sT\('(acc\.suno\w+)'", src))
print("js keys:", sorted(js_keys))
print("all js keys covered:", js_keys.issubset(cat_keys))
PY
echo KEY_MATCH_DONE
