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
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8765,
        reload=False,
        app_dir=str(ROOT),
        log_level="info",
    )
