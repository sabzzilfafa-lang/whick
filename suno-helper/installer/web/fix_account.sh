#!/bin/bash
# account.html 한글 깨짐 복구 — 기존 깨진 섹션/스크립트 제거 후 UTF-8 바이트로 재삽입
set -e
HTML=/data/whick-ai/2_control_center/git-home/account.html
cp "$HTML" "${HTML}.bak-mojibake-$(date +%Y%m%d%H%M%S)"

python3 - "$HTML" <<'PY'
import re, sys
from pathlib import Path

p = Path(sys.argv[1])
raw = p.read_bytes()
src = raw.decode('utf-8', errors='replace')

# 1) 이전에 삽입된(깨진 가능성 있는) Suno 섹션 제거 — id 기준으로 div 블록 통째로 제거
m = re.search(r'\n?[ \t]*<div class="acc-box" id="sunoPcBox".*?</div>\s*(?=\n\s*<div class="acc-box">\s*\n\s*<h2[^>]*data-i18n="acc\.changeTitle")', src, re.S)
if m:
    src = src[:m.start()] + src[m.end():]
    print('old section removed')
else:
    # changeTitle 앵커가 다르면: sunoPcBox부터 그 뒤 첫 <div class="acc-box"> 전까지 제거
    i = src.find('id="sunoPcBox"')
    if i >= 0:
        start = src.rfind('<div class="acc-box"', 0, i)
        nxt = src.find('<div class="acc-box">', src.find('</div>', i))
        if start >= 0 and nxt > start:
            src = src[:start] + src[nxt:]
            print('old section removed (fallback)')

# 2) 이전 JS 블록 제거 (주석 마커 기준)
m2 = re.search(r'\n[ \t]*// ===== Suno Helper PC 등록 =====.*?(?=\n</script>)', src, re.S)
if m2:
    src = src[:m2.start()] + src[m2.end():]
    print('old js removed')
else:
    m2 = re.search(r'\n[ \t]*// ===== Suno Helper[^\n]*=====.*?(?=\n</script>)', src, re.S)
    if m2:
        src = src[:m2.start()] + src[m2.end():]
        print('old js removed (fallback)')

p.write_bytes(src.encode('utf-8'))
PY

# 3) 섹션 HTML 삽입 (changeTitle 박스 앞) — 파일에서 직접 읽어 바이트 보존
python3 - "$HTML" <<'PY'
import sys
from pathlib import Path
p = Path(sys.argv[1])
src = p.read_text(encoding='utf-8')
section = Path('/tmp/account_suno_section.html').read_text(encoding='utf-8')
anchor = '''    <div class="acc-box">
      <h2 style="font-size:1.05rem;margin:0 0 6px;" data-i18n="acc.changeTitle">Change password</h2>'''
if 'id="sunoPcBox"' in src:
    print('section already present')
else:
    assert anchor in src, 'anchor not found'
    src = src.replace(anchor, section + anchor, 1)
    p.write_text(src, encoding='utf-8')
    print('section inserted')
PY

# 4) JS 삽입 (</script> 앞) — 훅도 함께
python3 - "$HTML" <<'PY'
import sys
from pathlib import Path
p = Path(sys.argv[1])
src = p.read_text(encoding='utf-8')
js = Path('/tmp/account_suno_script.js').read_text(encoding='utf-8')
if 'function sunoLoad' in src:
    print('js already present')
else:
    idx = src.rfind('</script>')
    src = src[:idx] + js + '\n' + src[idx:]
    # accountView 표시 시점에 상태 로드
    old = "$('accountView').hidden = false;"
    if old in src and "sunoLoad();" not in src:
        src = src.replace(old, old + "\n      if (typeof sunoLoad === 'function') sunoLoad();", 1)
    p.write_text(src, encoding='utf-8')
    print('js inserted')
PY

echo "==== 문법 검증 ===="
python3 - "$HTML" <<'PY'
import re, subprocess, tempfile, os, sys
src = Path(sys.argv[1]).read_text(encoding='utf-8')
scripts = re.findall(r'<script>(.*?)</script>', src, re.S)
code = '\n'.join(scripts)
stub = "var document={getElementById:function(){return{addEventListener:function(){},style:{},hidden:false,textContent:'',value:''}}},localStorage={getItem:function(){return null},setItem:function(){}},navigator={clipboard:{writeText:function(){return Promise.resolve()}}},fetch=function(){return Promise.resolve({json:function(){return Promise.resolve({ok:true,data:{}})})}},confirm=function(){return true},window=self;"
with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as f:
    f.write(stub + code)
    path = f.name
r = subprocess.run(['node', '--check', path], capture_output=True, text=True)
os.unlink(path)
print('syntax:', 'OK' if r.returncode == 0 else r.stderr[:400])
# 한글 정상 여부 샘플 출력
import io
for line in src.splitlines():
    if '내 PC 등록' in line:
        print('korean ok:', line.strip()[:60])
        break
PY
echo FIX_ACCOUNT_DONE
