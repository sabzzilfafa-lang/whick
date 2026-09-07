#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""notes_fix.sh를 base64로 감싸 전송 (LF 강제 — CRLF 제거)."""
import base64
from pathlib import Path

src = Path(__file__).parent / "notes_fix.sh"
raw = src.read_bytes().replace(b"\r\n", b"\n")
b64 = base64.b64encode(raw).decode("ascii")
wrapper = (
    "#!/bin/bash\n"
    "base64 -d > /tmp/notes_fix_inner.sh <<'B64EOF'\n" + b64 + "\nB64EOF\n"
    "bash /tmp/notes_fix_inner.sh\n"
    "rm -f /tmp/notes_fix_inner.sh\n"
)
Path(__file__).parent.joinpath("notes_fix_b64.sh").write_text(wrapper, encoding="ascii", newline="\n")
print(f"OK wrapper rebuilt (LF-forced), b64 {len(b64)}")
