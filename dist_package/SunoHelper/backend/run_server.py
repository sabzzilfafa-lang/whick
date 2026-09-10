"""Windows 백그라운드 실행용 uvicorn 런처 (stdout 없을 때 로깅 오류 방지)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT.parent / "data" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def _ensure_stdio() -> None:
    if sys.stdout is None:
        sys.stdout = open(LOG_DIR / "backend.log", "a", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(LOG_DIR / "backend.err", "a", encoding="utf-8")


if __name__ == "__main__":
    _ensure_stdio()
    import uvicorn

    # Windows: reload=True leaves orphan listeners; code changes need stop/start.
    # Retry bind a few times: a stale backend from a previous install may
    # still hold port 8765 — install.bat kills it, but give it a moment.
    import time

    last_exc: Exception | None = None
    for _ in range(4):
        try:
            uvicorn.run(
                "app.main:app",
                host="127.0.0.1",
                port=8765,
                reload=False,
                app_dir=str(ROOT),
                log_level="info",
            )
            last_exc = None
            break
        except SystemExit:
            raise
        except OSError as exc:  # WinError 10048 etc.
            last_exc = exc
            time.sleep(2.0)
    if last_exc is not None:
        raise last_exc
