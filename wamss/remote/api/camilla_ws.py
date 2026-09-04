"""CamillaDSP websocket client — PatchConfig / SetConfig / Reload (상주 데몬)."""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
from typing import Any


def ws_host() -> str:
    return (os.getenv("WHICK_CAMILLA_WS_HOST") or "127.0.0.1").strip()


def ws_port() -> int:
    try:
        return int(os.getenv("WHICK_CAMILLA_WS_PORT", "1234"))
    except ValueError:
        return 1234


def ws_url() -> str:
    return f"ws://{ws_host()}:{ws_port()}"


def _strip_yaml_doc_marker(yaml_text: str) -> str:
    text = yaml_text.strip()
    if text.startswith("---"):
        text = text.split("\n", 1)[1].lstrip()
    return text


async def _ws_command(cmd: Any, *, timeout: float = 5.0) -> dict[str, Any]:
    import websockets

    payload = json.dumps(cmd)
    async with websockets.connect(ws_url(), open_timeout=timeout, close_timeout=2) as ws:
        await ws.send(payload)
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"ok": False, "error": f"invalid ws response: {raw[:200]}"}
    if not isinstance(data, dict) or len(data) != 1:
        return {"ok": False, "error": f"unexpected ws response: {data!r}", "raw": data}
    key, body = next(iter(data.items()))
    if isinstance(body, dict) and body.get("result") == "Ok":
        return {"ok": True, "command": key, "value": body.get("value")}
    return {"ok": False, "command": key, "error": body, "raw": data}


def _run_sync(coro: Any, *, timeout: float = 8.0) -> dict[str, Any]:
    """uvicorn 이벤트 루프 안에서도 안전하게 실행.

    Future.result()에 반드시 timeout을 건다 — timeout 없으면 CamillaDSP가
    ALSA EINVAL 등으로 응답 불능일 때 호출 스레드가 영구 블록된다.
    (그 스레드가 이벤트루프면 /health 포함 전 요청이 먹통이 됨)
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        try:
            return asyncio.run(asyncio.wait_for(coro, timeout=timeout))
        except asyncio.TimeoutError:
            return {"ok": False, "error": f"camilla ws sync timeout after {timeout}s"}
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        try:
            return pool.submit(asyncio.run, coro).result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            return {"ok": False, "error": f"camilla ws sync timeout after {timeout}s"}


def patch_config(yaml_text: str, *, timeout: float = 3.0) -> dict[str, Any]:
    """Camilla ≥3 PatchConfig — JSON 부분객체 (YAML 문자열 아님).

    filters/mixers/pipeline만 담은 YAML을 dict로 파싱해 보낸다.
    2.0.x는 명령 미지원 → ok=False.
    """
    text = _strip_yaml_doc_marker(yaml_text)
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text)
        if not isinstance(data, dict):
            return {"ok": False, "error": "patch payload is not a mapping"}
        # WS open/recv timeout + 여유분 — 바깥 .result()도 같은 상한으로 묶는다
        return _run_sync(
            _ws_command({"PatchConfig": data}, timeout=timeout),
            timeout=timeout + 3.0,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def set_config(yaml_text: str, *, timeout: float = 3.0) -> dict[str, Any]:
    """전체 yaml을 즉시 적용 (구조 변경·폴백)."""
    text = _strip_yaml_doc_marker(yaml_text)
    try:
        return _run_sync(
            _ws_command({"SetConfig": text}, timeout=timeout),
            timeout=timeout + 3.0,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def reload_from_file(*, timeout: float = 3.0) -> dict[str, Any]:
    try:
        return _run_sync(_ws_command("Reload", timeout=timeout), timeout=timeout + 3.0)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def ping(*, timeout: float = 2.0) -> dict[str, Any]:
    try:
        return _run_sync(_ws_command("GetVersion", timeout=timeout), timeout=timeout + 3.0)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
