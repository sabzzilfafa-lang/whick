#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""suno.html 커밋 전 검증: ASCII 안전성·스크립트 순서·필수 요소."""
import re
import sys
from pathlib import Path

p = Path(__file__).parent / "suno.html"
html = p.read_text(encoding="ascii")  # ascii 아니면 즉시 예외

errs = []
order = [html.find("i18n-cats.js"), html.find("SUNO_I18N_EXTRA"), html.find("js/i18n.js?v=")]
if not (0 < order[0] < order[1] < order[2]):
    errs.append(f"script order bad: {order}")
if 'id="langSel"' not in html:
    errs.append("langSel missing")
if html.count("data-i18n") < 30:
    errs.append("data-i18n too few")
for anchor in ["intro", "features", "license", "manual", "download"]:
    if f'id="{anchor}"' not in html:
        errs.append(f"anchor #{anchor} missing")
if "/account.html#sunoPcBox" not in html:
    errs.append("mypage CTA missing")

# 스크립트 블록 문법 검증 (node)
import tempfile
scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
chk = Path(tempfile.gettempdir()) / "suno_chk.js"
chk.write_text("\n;\n".join(scripts), encoding="utf-8")
print(f"chkjs={chk}")

print("\n".join(errs) if errs else "ALL_CHECKS_OK")
sys.exit(1 if errs else 0)
