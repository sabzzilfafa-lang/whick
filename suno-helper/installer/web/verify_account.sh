#!/bin/bash
# 무엇이 삽입됐는지 서버에서 직접 확인
HTML=/data/whick-ai/2_control_center/git-home/account.html
grep -c "sunoPcBox" "$HTML"
grep -o "Suno Helper[^<]*" "$HTML" | head -3
grep -n "btnSunoToken" "$HTML" | head -2
# 헥스로 실제 바이트 확인 (한글이 정상 UTF-8인지)
python3 -c "
from pathlib import Path
src = Path('$HTML').read_bytes().decode('utf-8', errors='replace')
i = src.find('sunoPcBox')
if i >= 0:
    seg = src[i:i+400]
    print(repr(seg[:200]))
else:
    print('sunoPcBox NOT FOUND')
"
