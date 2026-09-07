#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""account.html 최종 재작성 — payload.sh의 b64에서 직접 복원 (검증 문자열도 b64로)."""
import base64
import re
import shutil
import subprocess
import tempfile
import os
import sys
from pathlib import Path

HTML = Path("/data/whick-ai/2_control_center/git-home/account.html")
raw = Path("/tmp/payload.sh").read_text()


def grab(key: str) -> bytes:
    m = re.search(key + r"=(\S+)", raw)
    return base64.b64decode(m.group(1))


sec_bytes = grab("SECTION_B64")
js_bytes = grab("JS_B64")
sec = sec_bytes.decode("utf-8")
js = js_bytes.decode("utf-8")

# 한글 바이트 검증 (EB82B4 = '내')
assert b"\xeb\x82\xb4" in sec_bytes, "section has no korean"
print("payload korean: OK")

shutil.copy2(HTML, str(HTML) + ".bak3")
src = HTML.read_text(encoding="utf-8", errors="replace")

# 기존 섹션/JS 제거
i = src.find('id="sunoPcBox"')
if i >= 0:
    start = src.rfind('<div class="acc-box"', 0, i)
    nxt = src.find('<div class="acc-box">', i)
    if start >= 0 and nxt > start:
        src = src[:start] + src[nxt:]
        print("old section removed")
m = re.search(r"\n[ \t]*// ===== Suno Helper.*?(?=\n</script>)", src, re.S)
if m:
    src = src[: m.start()] + src[m.end() :]
    print("old js removed")

# 삽입
anchor = '    <div class="acc-box">\n      <h2 style="font-size:1.05rem;margin:0 0 6px;" data-i18n="acc.changeTitle">Change password</h2>'
assert anchor in src, "anchor missing"
src = src.replace(anchor, sec.rstrip() + "\n\n" + anchor, 1)
idx = src.rfind("</script>")
src = src[:idx] + js + "\n" + src[idx:]
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
print("syntax:", "OK" if r.returncode == 0 else r.stderr[:300])

# 한글 바이트로 최종 검증 (문자열 비교가 아닌 바이트 비교)
final = HTML.read_bytes()
assert "\ub0b4 PC \ub4f1\ub85d".encode("utf-8") in final, "final korean missing"
print("FINAL_KOREAN_OK")
