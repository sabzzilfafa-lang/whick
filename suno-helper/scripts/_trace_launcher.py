# -*- coding: utf-8 -*-
"""launcher.pyw 실제 실행 추적 — 단계별 로그로 어디서 죽는지 확인."""
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(r"C:\Users\user\AppData\Local\SunoHelper")
PY = ROOT / "backend" / ".venv" / "Scripts" / "python.exe"
LOG = ROOT / "data" / "logs" / "launcher.log"

if LOG.exists():
    LOG.unlink()

print("=== run launcher.pyw via python (console) ===")
r = subprocess.run([str(PY), "-X", "utf8", str(ROOT / "launcher.pyw")],
                   capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
print("exit:", r.returncode)
print("stdout:", (r.stdout or "")[:500])
print("stderr:", (r.stderr or "")[:800])
time.sleep(1)
print("=== launcher.log ===")
if LOG.exists():
    print(LOG.read_text(encoding="utf-8"))
else:
    print("(no log file)")
