"""suno-helper:// 프로토콜 핸들러 — 웹에서 "실행" 클릭 시 Windows가 호출.

흐름:
1. Windows 레지스트리(suno-helper://)가 launcher.pyw를 인자와 함께 실행
2. 여기서 백엔드(8765) 기동 대기 → 기본 브라우저로 http://127.0.0.1:8765 오픈
3. 창 없이 조용히 종료 (백엔드는 이미 독립 프로세스로 기동됨)

보안:
- 백엔드 /api/local/launch 가 web_launch.lock 플래그를 확인 (웹 설치 흐름만 허용)
- 이 런처는 URL의 실제 쿼리를 파싱하지 않고 "실행 트리거"로만 사용 (인젝션 차단)
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY_EXE = ROOT / "backend" / ".venv" / "Scripts" / "pythonw.exe"
if not PY_EXE.is_file():
    PY_EXE = ROOT / "backend" / ".venv" / "Scripts" / "python.exe"
START_BAT = ROOT / "start.bat"


def _server_up(timeout: float = 45.0) -> bool:
    """127.0.0.1:8765가 LISTENING이 될 때까지 대기."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True, errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        for line in (r.stdout or "").splitlines():
            if ":8765" in line and "LISTENING" in line.upper():
                return True
        time.sleep(0.7)
    return False


def _spawn_backend() -> None:
    """서버가 꺼져 있으면 start.bat의 백엔드 기동 부분을 조용히 실행."""
    if _server_up(timeout=1.0):
        return
    # start.bat를 직접 실행하면 콘솔이 뜨므로, run_server.py를 숨김 프로세스로 기동
    subprocess.Popen(
        [str(PY_EXE), str(ROOT / "backend" / "run_server.py")],
        cwd=str(ROOT / "backend"),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )


def main() -> None:
    _spawn_backend()
    _server_up()
    # 웹 플래그 확인 (웹 설치 흐름이 아니면 실행하지 않음)
    flag = ROOT / "data" / "web_launch.lock"
    if not flag.is_file():
        return
    url = os.environ.get("SUNO_LAUNCH_URL", "http://127.0.0.1:8765/?launch=web")
    os.startfile(url)  # noqa: S606 — 기본 브라우저 오픈


if __name__ == "__main__":
    main()
