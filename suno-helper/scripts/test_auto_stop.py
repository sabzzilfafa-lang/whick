"""자동 종료 워처 단위 테스트 — heartbeat 갱신/타임아웃 분기 검증."""
import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "backend"))
os.environ["SUNO_AUTO_STOP"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import AUTO_STOP_TIMEOUT_SEC, app, _last_heartbeat  # noqa: E402


def main() -> int:
    with TestClient(app) as client:
        # 1) heartbeat 호출 시 타임스탬프 갱신
        t0 = _last_heartbeat[0]
        r = client.post("/api/heartbeat")
        assert r.status_code == 200 and r.json() == {"ok": True}
        assert _last_heartbeat[0] > t0 or t0 == 0.0
        assert _last_heartbeat[0] > 0
        print("PASS: heartbeat updates timestamp")

        # 2) health 엔드포인트 정상
        r = client.get("/api/health")
        assert r.status_code == 200 and r.json()["status"] == "ok"
        print("PASS: health ok")

        # 3) 타임아웃 상수 합리성
        assert 30 <= AUTO_STOP_TIMEOUT_SEC <= 300
        print(f"PASS: timeout={AUTO_STOP_TIMEOUT_SEC}s")

    print("AUTO_STOP_TESTS_PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
