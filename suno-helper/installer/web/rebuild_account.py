#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""로컬에서 account.html 최종본을 만들어 서버에 통째로 업로드 (인코딩 확실)."""
import re
import shutil
import subprocess
import sys
import tempfile
import os
from pathlib import Path

HTML = Path("/data/whick-ai/2_control_center/git-home/account.html")
SECTION = Path("/tmp/account_suno_section.html").read_text(encoding="utf-8")
JS = Path("/tmp/account_suno_script.js").read_text(encoding="utf-8")

shutil.copy2(HTML, str(HTML) + ".bak2")
src = HTML.read_text(encoding="utf-8", errors="replace")

# 기존 섹션 제거
i = src.find('id="sunoPcBox"')
if i >= 0:
    start = src.rfind('<div class="acc-box"', 0, i)
    # 섹션은 sunoPcBox div 하나 — 그 closing을 찾자: 다음 <div class="acc-box"> 직전
    nxt = src.find('<div class="acc-box">', i)
    if start >= 0 and nxt > start:
        src = src[:start] + src[nxt:]
        print("old section removed")

# 기존 JS 제거
m = re.search(r"\n[ \t]*// ===== Suno Helper.*?(?=\n</script>)", src, re.S)
if m:
    src = src[: m.start()] + src[m.end() :]
    print("old js removed")

# 섹션 삽입
anchor = '''    <div class="acc-box">
      <h2 style="font-size:1.05rem;margin:0 0 6px;" data-i18n="acc.changeTitle">Change password</h2>'''
assert anchor in src, "anchor missing"
src = src.replace(anchor, SECTION + anchor, 1)

# JS 삽입
idx = src.rfind("</script>")
src = src[:idx] + JS + "\n" + src[idx:]
old = "$('accountView').hidden = false;"
if old in src and "sunoLoad();" not in src:
    src = src.replace(old, old + "\n      if (typeof sunoLoad === 'function') sunoLoad();", 1)

HTML.write_bytes(src.encode("utf-8"))
print("written")

# 문법 검증
scripts = re.findall(r"<script>(.*?)</script>", src, re.S)
code = "\n".join(scripts)
stub = "var document={getElementById:function(){return{addEventListener:function(){},style:{},hidden:false,textContent:'',value:''}}},localStorage={getItem:function(){return null},setItem:function(){}},navigator={clipboard:{writeText:function(){return Promise.resolve()}}},fetch=function(){return Promise.resolve({json:function(){return Promise.resolve({ok:true,data:{license:null}})})}},confirm=function(){return true},window=self;"
with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
    f.write(stub + code)
    path = f.name
r = subprocess.run(["node", "--check", path], capture_output=True, text=True)
os.unlink(path)
print("syntax:", "OK" if r.returncode == 0 else r.stderr[:400])

# 한글 확인
ok1 = "내 PC 등록" in src
ok2 = "활성화 토큰 발급" in src
print("korean check:", ok1, ok2)
if not (ok1 and ok2):
    sys.exit("KOREAN BROKEN")
print("BUILD_OK")
