#!/bin/bash
python3 /tmp/rebuild_account.py 2>&1 | tail -4
echo "==== 서버 파일 최종 확인 ===="
python3 -c "
from pathlib import Path
src = Path('/data/whick-ai/2_control_center/git-home/account.html').read_text(encoding='utf-8')
print('section korean:', '내 PC 등록' in src)
print('button korean:', '활성화 토큰 발급' in src)
print('status korean:', '등록된 PC가 없습니다' in src)
print('js korean:', '복사됨' in src)
"
echo "==== 외부 브라우저 관점 ===="
curl -s https://whick.org/account.html | grep -o "내 PC 등록" | head -1
curl -s https://whick.org/account.html | grep -o "활성화 토큰 발급" | head -1
echo REBUILD_FINAL_DONE
