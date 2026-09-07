"""suno-helper:// 프로토콜 핸들러 — 웹에서 "실행" 클릭 시 Windows가 호출.

흐름:
1. Windows 레지스트리(suno-helper://)가 launcher.pyw를 인자와 함께 실행
2. 백엔드(8765) 기동 → HTTP 200 확인 → 기본 브라우저로 앱 오픈
3. 창 없이 조용히 종료 (백엔드는 독립 프로세스로 유지)

보안:
- web_launch.lock 플래그가 있어야만 실행 (웹 설치 흐름만 허용)
- URL 인자는 파싱하지 않고 "실행 트리거"로만 사용 (인젝션 차단)
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent  # launcher.pyw는 앱 루트 바로 아래에 있다
PY_EXE = ROOT / "backend" / ".venv" / "Scripts" / "pythonw.exe"
if not PY_EXE.is_file():
    PY_EXE = ROOT / "backend" / ".venv" / "Scripts" / "python.exe"

LOG_DIR = ROOT / "data" / "logs"


def _log(msg: str) -> None:
    """디버그 로그 (실행 실패 원인 추적용)."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_DIR / "launcher.log", "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except Exception:
        pass


def _server_http_ok(timeout: float = 45.0) -> bool:
    """백엔드가 HTTP로 응답할 때까지 대기 (LISTENING만으로는 부족 — 응답 확인 필요)."""
    deadline = time.time() + timeout
    last_err = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen("http://127.0.0.1:8765/api/local/status", timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception as e:
            last_err = str(e)
        time.sleep(1.0)
    _log(f"server http wait failed: {last_err}")
    return False


def _spawn_backend() -> None:
    """서버가 꺼져 있으면 숨김 프로세스로 기동."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:8765/api/local/status", timeout=2) as r:
            if r.status == 200:
                _log("backend already running")
                return
    except Exception:
        pass
    _log("spawning backend")
    subprocess.Popen(
        [str(PY_EXE), str(ROOT / "backend" / "run_server.py")],
        cwd=str(ROOT / "backend"),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )


def main() -> None:
    _log(f"launch invoked argv0={sys.argv[0] if sys.argv else ''}")
    _spawn_backend()
    if not _server_http_ok():
        _log("backend never became healthy - abort")
        return
    flag = ROOT / "data" / "web_launch.lock"
    if not flag.is_file():
        _log("web_launch.lock missing - abort (direct install flow)")
        return
    url = os.environ.get("SUNO_LAUNCH_URL", "http://127.0.0.1:8765/?launch=web")
    _log(f"opening browser: {url}")
    try:
        # os.startfile 대신 시작 메뉴의 기본 브라우저 핸들러로 명시적 오픈
        subprocess.Popen(
            ["cmd", "/c", "start", "", url],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            shell=False,
        )
        _log("browser open command issued")
    except Exception as e:
        _log(f"browser open failed: {e}")


if __name__ == "__main__":
    main()
