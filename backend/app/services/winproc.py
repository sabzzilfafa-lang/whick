"""Windows 콘솔창 숨김 — ffmpeg/ffprobe 등 자식 프로세스 콘솔 깜빡임 방지 (v0.9.64).

pythonw(무콘솔) 백엔드에서 subprocess.run으로 콘솔 프로그램을 실행하면
Windows가 새 콘솔 창을 생성해 도스창이 떴다 사라지는 현상이 발생한다.
CREATE_NO_WINDOW 플래그로 방지 (Windows 전용, 다른 OS는 0).
"""

from __future__ import annotations

import subprocess


def creation_flags() -> int:
    """subprocess.run/Popen의 creationflags 인자 값 — Windows에서만 CREATE_NO_WINDOW."""
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)
