"""미니PC 라이브러리 라우드니스 정규화 — 백그라운드 1곡씩 · 재생 중 일시정지.

원본 재인코딩 없음. tracks.replay_gain_db 에 저장 후 재생 시 볼륨에만 반영.
ffmpeg ebur128 은 nice 로 낮춰 호출한다.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import asyncpg

SETTINGS_PATH = Path(
    os.getenv(
        "WHICK_LOUDNESS_SETTINGS",
        "/var/lib/whick/state/loudness-settings.json",
    )
)
TARGET_LUFS = float(os.getenv("WHICK_LOUDNESS_TARGET_LUFS", "-14"))
MAX_GAIN = float(os.getenv("WHICK_LOUDNESS_MAX_GAIN", "12"))
MIN_GAIN = float(os.getenv("WHICK_LOUDNESS_MIN_GAIN", "-6"))
IDLE_SLEEP_SEC = float(os.getenv("WHICK_LOUDNESS_IDLE_SLEEP", "8"))
BETWEEN_TRACK_SEC = float(os.getenv("WHICK_LOUDNESS_BETWEEN_SEC", "1.5"))
# 재생 종료 후 이 시간(초) 이상 조용해야 정규화 재개 (기본 5분)
IDLE_AFTER_PLAYBACK_SEC = float(os.getenv("WHICK_LOUDNESS_IDLE_AFTER_PLAYBACK", "300"))
# 재생/유휴 판정 폴링 (대기 중 CPU 거의 없음)
IDLE_POLL_SEC = float(os.getenv("WHICK_LOUDNESS_IDLE_POLL", "30"))

DEFAULT_SETTINGS = {
    "enabled": True,
    "target_lufs": TARGET_LUFS,
    "max_gain_db": MAX_GAIN,
    "min_gain_db": MIN_GAIN,
    "pause_while_playing": True,
    "idle_after_playback_sec": IDLE_AFTER_PLAYBACK_SEC,
}

I_RE = re.compile(r"^\s*I:\s*([+-]?\d+(?:\.\d+)?)\s*LUFS", re.M)
TP_RE = re.compile(r"True peak:\s*\n\s*Peak:\s*([+-]?\d+(?:\.\d+)?)\s*dBFS", re.M)

_worker_task: asyncio.Task | None = None
_status: dict[str, Any] = {
    "running": False,
    "enabled": True,
    "pending": 0,
    "done": 0,
    "failed": 0,
    "current_track_id": None,
    "current_title": "",
    "last_error": "",
    "updated": "",
}


def load_settings() -> dict[str, Any]:
    settings = dict(DEFAULT_SETTINGS)
    if SETTINGS_PATH.is_file():
        try:
            raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                settings["enabled"] = bool(raw.get("enabled", True))
                if raw.get("target_lufs") is not None:
                    settings["target_lufs"] = float(raw["target_lufs"])
                if raw.get("max_gain_db") is not None:
                    settings["max_gain_db"] = float(raw["max_gain_db"])
                if raw.get("min_gain_db") is not None:
                    settings["min_gain_db"] = float(raw["min_gain_db"])
                settings["pause_while_playing"] = bool(raw.get("pause_while_playing", True))
                if raw.get("idle_after_playback_sec") is not None:
                    settings["idle_after_playback_sec"] = float(raw["idle_after_playback_sec"])
        except Exception:
            pass
    return settings


def save_settings(body: dict[str, Any] | None) -> dict[str, Any]:
    cur = load_settings()
    if isinstance(body, dict):
        if "enabled" in body:
            cur["enabled"] = bool(body["enabled"])
        if body.get("target_lufs") is not None:
            cur["target_lufs"] = float(body["target_lufs"])
        if body.get("max_gain_db") is not None:
            cur["max_gain_db"] = float(body["max_gain_db"])
        if body.get("min_gain_db") is not None:
            cur["min_gain_db"] = float(body["min_gain_db"])
        if "pause_while_playing" in body:
            cur["pause_while_playing"] = bool(body["pause_while_playing"])
        if body.get("idle_after_playback_sec") is not None:
            cur["idle_after_playback_sec"] = max(60.0, float(body["idle_after_playback_sec"]))
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(cur, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _status["enabled"] = cur["enabled"]
    return cur


async def ensure_loudness_schema(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "ALTER TABLE tracks ADD COLUMN IF NOT EXISTS replay_gain_db DOUBLE PRECISION"
        )
        await conn.execute(
            "ALTER TABLE tracks ADD COLUMN IF NOT EXISTS loudness_i DOUBLE PRECISION"
        )
        await conn.execute(
            "ALTER TABLE tracks ADD COLUMN IF NOT EXISTS true_peak_db DOUBLE PRECISION"
        )
        await conn.execute(
            "ALTER TABLE tracks ADD COLUMN IF NOT EXISTS loudness_measured_at TIMESTAMPTZ"
        )


def _measure_file(path: Path, *, target: float, min_g: float, max_g: float) -> dict[str, float]:
    cmd = [
        "nice",
        "-n",
        "19",
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-i",
        str(path),
        "-af",
        # framelog=quiet 는 일부 ffmpeg/FLAC(24-bit) 조합에서 Summary I=0 / Peak -inf 로
        # 깨져 전 곡에 min_gain(-6dB)이 박히는 원인이 됨 — 기본 로그 사용
        "ebur128=peak=true",
        "-f",
        "null",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    err = proc.stderr or ""
    # Summary 블록의 Integrated loudness 만 (진행 중 t: 줄의 I: 제외)
    mi = re.search(
        r"Integrated loudness:\s*\n\s*I:\s*([+-]?\d+(?:\.\d+)?)\s*LUFS",
        err,
    )
    if not mi:
        mi = I_RE.search(err)
    if not mi:
        raise RuntimeError(f"loudness parse failed: {path.name}")
    integrated = float(mi.group(1))
    mt = TP_RE.search(err)
    true_peak = float(mt.group(1)) if mt else 0.0
    # 깨진 측정(무음으로 읽힘) 거부 — 예전엔 I=0 → gain=-14 clamp → 전 곡 -6dB
    if integrated > -1.0 or (mt is not None and true_peak < -60.0):
        raise RuntimeError(
            f"loudness invalid integrated={integrated} peak={true_peak}: {path.name}"
        )
    gain = max(min_g, min(max_g, target - integrated))
    return {
        "loudness_i": round(integrated, 2),
        "true_peak_db": round(true_peak, 2),
        "replay_gain_db": round(gain, 2),
    }


async def count_pending(pool: asyncpg.Pool) -> int:
    async with pool.acquire() as conn:
        return int(
            await conn.fetchval(
                "SELECT COUNT(*) FROM tracks WHERE replay_gain_db IS NULL AND file_path IS NOT NULL"
            )
            or 0
        )


async def status(pool: asyncpg.Pool | None) -> dict[str, Any]:
    settings = load_settings()
    pending = await count_pending(pool) if pool else 0
    out = dict(_status)
    out.update(
        {
            "enabled": settings["enabled"],
            "pending": pending,
            "settings": settings,
            "warning": (
                "음량 정규화는 곡마다 CPU를 사용합니다. "
                "미니PC에서는 백그라운드로 1곡씩만 처리하며, "
                "재생 중·재생 직후 5분 동안은 자동으로 멈춥니다. "
                "대량 추가 직후에는 완료까지 시간이 걸릴 수 있습니다."
            ),
        }
    )
    return out


_last_playback_mono: float | None = None


def _playing_now() -> bool:
    try:
        from api.music_api import STATE

        return bool(STATE.playing and (STATE.mpd_active or STATE.server_audio_active))
    except Exception:
        return False


def _idle_ready(settings: dict[str, Any]) -> tuple[bool, str]:
    """재생 중이 아니고, 마지막 재생 종료 후 idle_after 초 이상 지나야 True."""
    global _last_playback_mono
    import time

    if not settings.get("pause_while_playing", True):
        return True, ""

    now = time.monotonic()
    if _playing_now():
        _last_playback_mono = now
        return False, "(재생 중 — 대기)"

    need = float(settings.get("idle_after_playback_sec") or IDLE_AFTER_PLAYBACK_SEC)
    need = max(60.0, need)
    if _last_playback_mono is None:
        return True, ""

    elapsed = now - _last_playback_mono
    if elapsed < need:
        left = int(need - elapsed)
        mins = max(1, (left + 59) // 60)
        return False, f"(재생 후 유휴 대기 · 약 {mins}분 후 재개)"
    return True, ""


async def _process_one(pool: asyncpg.Pool, settings: dict[str, Any]) -> bool:
    """한 곡 처리. True=일 했음, False=대기할 일 없음."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT track_id, title, file_path
            FROM tracks
            WHERE replay_gain_db IS NULL AND file_path IS NOT NULL
            ORDER BY track_id ASC
            LIMIT 1
            """
        )
    if not row:
        return False

    tid = int(row["track_id"])
    title = str(row["title"] or "")
    path = Path(str(row["file_path"]))
    _status.update(
        {
            "running": True,
            "current_track_id": tid,
            "current_title": title[:120],
            "last_error": "",
            "updated": datetime.now(timezone.utc).astimezone().isoformat(),
        }
    )

    if not path.is_file():
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE tracks
                SET replay_gain_db = 0, loudness_i = NULL, true_peak_db = NULL,
                    loudness_measured_at = now()
                WHERE track_id = $1
                """,
                tid,
            )
        _status["failed"] = int(_status.get("failed") or 0) + 1
        _status["last_error"] = f"missing file track_id={tid}"
        return True

    try:
        result = await asyncio.to_thread(
            _measure_file,
            path,
            target=float(settings.get("target_lufs", TARGET_LUFS)),
            min_g=float(settings.get("min_gain_db", MIN_GAIN)),
            max_g=float(settings.get("max_gain_db", MAX_GAIN)),
        )
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE tracks
                SET replay_gain_db = $2,
                    loudness_i = $3,
                    true_peak_db = $4,
                    loudness_measured_at = now()
                WHERE track_id = $1
                """,
                tid,
                result["replay_gain_db"],
                result["loudness_i"],
                result["true_peak_db"],
            )
        _status["done"] = int(_status.get("done") or 0) + 1
    except Exception as exc:
        _status["failed"] = int(_status.get("failed") or 0) + 1
        _status["last_error"] = str(exc)[:240]
        # 재시도 루프 방지: 실패도 0dB로 표시
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE tracks
                SET replay_gain_db = 0, loudness_measured_at = now()
                WHERE track_id = $1 AND replay_gain_db IS NULL
                """,
                tid,
            )
    return True


async def worker_loop(pool: asyncpg.Pool) -> None:
    print(
        "[loudness] background worker started "
        f"(1 track, resume after {int(IDLE_AFTER_PLAYBACK_SEC)}s idle)"
    )
    while True:
        try:
            settings = load_settings()
            _status["enabled"] = settings["enabled"]
            if not settings.get("enabled", True):
                _status["running"] = False
                _status["current_track_id"] = None
                _status["current_title"] = ""
                await asyncio.sleep(IDLE_SLEEP_SEC)
                continue

            ready, wait_msg = _idle_ready(settings)
            if not ready:
                _status["running"] = False
                _status["current_track_id"] = None
                _status["current_title"] = wait_msg
                await asyncio.sleep(IDLE_POLL_SEC)
                continue

            did = await _process_one(pool, settings)
            _status["pending"] = await count_pending(pool)
            if not did:
                _status["running"] = False
                _status["current_track_id"] = None
                _status["current_title"] = ""
                await asyncio.sleep(IDLE_SLEEP_SEC)
            else:
                await asyncio.sleep(BETWEEN_TRACK_SEC)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _status["last_error"] = str(exc)[:240]
            print(f"[loudness] worker error: {exc}")
            await asyncio.sleep(IDLE_SLEEP_SEC)


def start_worker(pool: asyncpg.Pool) -> asyncio.Task:
    global _worker_task
    if _worker_task and not _worker_task.done():
        return _worker_task
    _worker_task = asyncio.create_task(worker_loop(pool), name="loudness-normalize")
    return _worker_task


def stop_worker() -> None:
    global _worker_task
    if _worker_task and not _worker_task.done():
        _worker_task.cancel()
    _worker_task = None


def kick() -> None:
    """신규 추가 직후 — 워커가 곧 pending 을 보게 idle sleep 만 짧게."""
    _status["updated"] = datetime.now(timezone.utc).astimezone().isoformat()
