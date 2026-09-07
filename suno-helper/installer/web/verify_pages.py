#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""생성된 suno.html / suno-app.html 검증: 스크립트 문법 + 플레이스홀더 잔존 + 필수 요소."""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

errs = []
HERE = Path(__file__).parent

for name in ("suno.html", "suno-app.html"):
    p = HERE / name
    html = p.read_text(encoding="ascii")  # ascii 검증 겸용
    # 1) 플레이스홀더 잔존 검사
    for ph in ("__EXTRA__", "__I18N_MERGE__", "__OPTS__"):
        if ph in html:
            errs.append(f"{name}: placeholder {ph} left")
    # 2) 스크립트 문법
    scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
    chk = Path(tempfile.gettempdir()) / f"chk_{name}.js"
    chk.write_text("\n;\n".join(scripts), encoding="utf-8")
    r = subprocess.run(["node", "--check", str(chk)], capture_output=True, text=True)
    if r.returncode != 0:
        errs.append(f"{name}: syntax {r.stderr[:200]}")
    # 3) i18n 병합 구조: cats -> merge -> init
    i_cats = html.find("i18n-cats.js")
    i_merge = html.find("SUNO_I18N_EXTRA")
    i_init = html.find("js/i18n.js")
    if not (0 <= i_cats < i_merge < i_init):
        errs.append(f"{name}: script order bad cats={i_cats} merge={i_merge} init={i_init}")
    # 4) 카탈로그에 한글 이스케이프 존재 (ko 키 유무 간접 확인)
    if name == "suno-app.html" and "\\uc18c\\uac1c" not in html:
        errs.append(f"{name}: ko catalog missing")
    # 5) 필수 요소
    if name == "suno-app.html":
        for need in ('id="dashBtn"', 'id="dashStatus"', "suno-helper://", "Setup.bat"):
            if need not in html:
                errs.append(f"{name}: missing {need}")

print("\n".join(errs) if errs else "ALL_OK")
sys.exit(1 if errs else 0)
