# -*- coding: utf-8 -*-
"""E2E: /api/local/status, /api/local/launch, 게이트 동작 검증."""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

BASE = "http://127.0.0.1:8765"
FAIL = []


def req(path, method="GET"):
    r = urllib.request.Request(BASE + path, method=method)
    try:
        with urllib.request.urlopen(r, timeout=6) as resp:
            return resp.status, json.loads(resp.read())
    except Exception as e:
        return None, str(e)


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}  {detail}")
    if not cond:
        FAIL.append(name)


# 1. 서버 응답
st, j = req("/api/local/status")
check("status reachable", st == 200, f"st={st} j={j}")
check("status fields", isinstance(j, dict) and "installed" in j and "version" in j, str(j))
check("version 1.1.0", j.get("version") == "1.1.0", str(j.get("version")))

# 2. web_launch 잠금 상태 (플래그 없음)
check("web_launch initially False", j.get("web_launch") is False, str(j.get("web_launch")))

# 3. launch 거부
st, j = req("/api/local/launch")
check("launch refused without flag", j.get("ok") is False, str(j))

# 4. 플래그 생성 → launch 허용
flag = ROOT / "data" / "web_launch.lock"
flag.parent.mkdir(exist_ok=True)
flag.write_text("")
st, j = req("/api/local/status")
check("web_launch True after flag", j.get("web_launch") is True)
st, j = req("/api/local/launch")
check("launch ok with flag", j.get("ok") is True and len(j.get("token", "")) == 32, str(j))

# 5. PN 헤더
try:
    with urllib.request.urlopen(BASE + "/api/local/status", timeout=6) as resp:
        check("private-network header", resp.headers.get("Access-Control-Allow-Private-Network") == "true")
except Exception as e:
    check("private-network header", False, str(e))

# 6. 정리
flag.unlink(missing_ok=True)
st, j = req("/api/local/status")
check("web_launch False after cleanup", j.get("web_launch") is False)

print("\n" + ("ALL_E2E_OK" if not FAIL else f"FAILED: {FAIL}"))
sys.exit(1 if FAIL else 0)
