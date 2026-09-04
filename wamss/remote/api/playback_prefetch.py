"""다음 재생 곡 OS 페이지캐시 프리로드 — 트랙 전환 끊김 완화."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

_PREFETCH_BYTES = int(os.getenv("WHICK_TRACK_PREFETCH_BYTES", str(8 * 1024 * 1024)))
_task: asyncio.Task | None = None


def _prefetch_file(path: str) -> None:
    p = Path(path)
    if not p.is_file():
        return
    try:
        with open(p, "rb") as f:
            # Sequential read → page cache warm
            remaining = _PREFETCH_BYTES
            while remaining > 0:
                chunk = f.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
            try:
                os.posix_fadvise(f.fileno(), 0, 0, os.POSIX_FADV_WILLNEED)
            except (AttributeError, OSError):
                pass
    except OSError as exc:
        print(f"[prefetch] skip {p.name}: {exc}")


async def prefetch_track_paths(paths: list[str]) -> None:
    global _task
    clean = [str(p) for p in paths if p]
    if not clean:
        return
    if _task and not _task.done():
        _task.cancel()
        try:
            await _task
        except (asyncio.CancelledError, Exception):
            pass

    async def _run() -> None:
        for path in clean:
            await asyncio.to_thread(_prefetch_file, path)

    _task = asyncio.create_task(_run())
