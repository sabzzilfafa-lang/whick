"""공간음향 마법사 — 스마트폰↔뮤직서버 동기화 (체험 spatial_sync 대체)."""
from __future__ import annotations

import asyncio
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Awaitable

import httpx

SWEEP_LEAD_MS = int(os.getenv("WHICK_SPATIAL_SWEEP_LEAD_MS", "900"))
SWEEP_WAV = os.getenv("WHICK_SWEEP_WAV", "/var/lib/whick/library/sweep/log-sweep.wav")
AUDIO_URL = os.getenv("WHICK_AUDIO_URL", "http://audio:8787")


@dataclass
class SpatialState:
    phase: str = "idle"
    point_index: int = 0
    point_total: int = 5
    completed_points: int = 0
    run_id: str = ""
    sweep_at_ms: int = 0
    sweep_lead_ms: int = 0
    sweep_trigger: str = "mic"
    speaker_online: bool = True
    error: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {"event": "spatial", **asdict(self)}


STATE = SpatialState()
_broadcast: Callable[[dict[str, Any]], Awaitable[None]] | None = None
_play_sweep: Callable[[], None] | None = None
_play_test_tone: Callable[[str], Awaitable[None]] | None = None
_clear_mpd: Callable[[], None] | None = None
_delayed_play_task: asyncio.Task | None = None

# 마법사 종료·초기화 시 스윕/톤 MPD 큐 잔류를 걷어낼 phase
_CLEAR_MPD_PHASES = frozenset({"idle", "applied", "result"})


def _cancel_delayed_play() -> None:
    global _delayed_play_task
    if _delayed_play_task and not _delayed_play_task.done():
        _delayed_play_task.cancel()
    _delayed_play_task = None


def bind_handlers(
    broadcast: Callable[[dict[str, Any]], Awaitable[None]],
    play_sweep: Callable[[], None],
    play_test_tone: Callable[[str], Awaitable[None]] | None = None,
    clear_mpd: Callable[[], None] | None = None,
) -> None:
    global _broadcast, _play_sweep, _play_test_tone, _clear_mpd
    _broadcast = broadcast
    _play_sweep = play_sweep
    _play_test_tone = play_test_tone
    _clear_mpd = clear_mpd


def _clear_calibration_mpd() -> None:
    if _clear_mpd:
        try:
            _clear_mpd()
        except Exception as exc:
            print(f"[spatial] clear mpd: {exc}")


async def emit() -> None:
    if _broadcast:
        await _broadcast(STATE.to_payload())


async def reset() -> None:
    global STATE
    _cancel_delayed_play()
    _clear_calibration_mpd()
    STATE = SpatialState(speaker_online=True)
    await emit()


async def start_sweep(point_index: int, point_total: int = 5) -> SpatialState:
    global STATE, _delayed_play_task
    # 스윕 중 같은 포인트 중복 start 만 무시 (then/catch 더블파이어)
    # 다음 포인트는 진행 허용 (이전 delayed_play 는 아래에서 cancel)
    if STATE.phase == "sweeping" and int(point_index) == int(STATE.point_index):
        print(
            f"[spatial] ignore duplicate sweep_start "
            f"(phase=sweeping point={STATE.point_index}) run={STATE.run_id}"
        )
        await emit()
        return STATE
    # 이전 스윕 예약이 남아 있으면 다음 측정 비프를 끊거나 중복 재생함
    _cancel_delayed_play()
    STATE.phase = "sweeping"
    STATE.point_index = max(0, int(point_index))
    STATE.point_total = max(1, int(point_total))
    STATE.run_id = uuid.uuid4().hex[:12]
    run_id = STATE.run_id
    lead_sec = max(0.0, SWEEP_LEAD_MS / 1000.0)
    STATE.sweep_lead_ms = int(lead_sec * 1000)
    # 참고용 절대시각(구클라)·클라는 sweep_lead_ms 상대 대기 권장
    STATE.sweep_at_ms = int(time.time() * 1000) + STATE.sweep_lead_ms
    STATE.sweep_trigger = "mic"
    STATE.error = ""
    await emit()

    async def _delayed_play() -> None:
        try:
            await asyncio.sleep(lead_sec)
        except asyncio.CancelledError:
            return
        if STATE.run_id != run_id:
            return
        if _play_sweep:
            try:
                _play_sweep()
            except Exception as exc:
                # WAV 누락 등으로 스윕 실패 시 points 로 넘기지 않음 (Bugbot)
                print(f"[spatial] sweep play: {exc}")
                if STATE.run_id != run_id:
                    return
                STATE.error = f"sweep_play_failed: {exc}"
                STATE.phase = "idle"
                STATE.sweep_at_ms = 0
                STATE.sweep_lead_ms = 0
                await emit()
                return
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                await client.post(f"{AUDIO_URL}/sweep/play")
        except Exception as exc:
            print(f"[spatial] audio sweep notify: {exc}")
        if STATE.run_id != run_id:
            return
        # 재생이 끝난 뒤에야 points — 재생 중 phase=points 면 중복 start 가드가 풀림
        wav_sec = 8.0
        for cand in (
            os.getenv("WHICK_SWEEP_WAV", "/var/lib/whick/library/music/tones/log-sweep.wav"),
            SWEEP_WAV,
        ):
            try:
                import wave

                if not os.path.isfile(cand):
                    continue
                with wave.open(cand, "rb") as wf:
                    rate = float(wf.getframerate() or 0)
                    frames = float(wf.getnframes() or 0)
                    if rate > 0 and frames > 0:
                        wav_sec = frames / rate
                        break
            except Exception:
                continue
        try:
            await asyncio.sleep(max(0.5, wav_sec))
        except asyncio.CancelledError:
            return
        if STATE.run_id != run_id:
            return
        if STATE.phase == "sweeping":
            STATE.phase = "points"
            STATE.sweep_lead_ms = 0
            await emit()

    _delayed_play_task = asyncio.create_task(_delayed_play())
    return STATE


async def point_done(completed: int) -> None:
    STATE.completed_points = max(0, int(completed))
    # 마지막 포인트여도 스윕 WAV 재생 중 clear 는 clear_spatial_mpd 가 defer
    STATE.phase = "points" if STATE.completed_points < STATE.point_total else "result"
    if STATE.phase == "result":
        _clear_calibration_mpd()
    await emit()


async def set_phase(phase: str) -> None:
    STATE.phase = phase
    if phase in _CLEAR_MPD_PHASES:
        _clear_calibration_mpd()
    await emit()


async def play_test_tone(channel: str, *, swap_channels: bool | None = None) -> None:
    ch = "right" if str(channel).lower().startswith("r") else "left"
    played = False
    if _play_test_tone:
        try:
            await _play_test_tone(ch, swap_channels=swap_channels)
            played = True
        except Exception as exc:
            print(f"[spatial] test tone mpd: {exc}")
            STATE.error = str(exc)
            await emit()
            return
    if not played:
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                await client.post(f"{AUDIO_URL}/test-tone/play", json={"channel": ch})
        except Exception as exc:
            print(f"[spatial] test tone audio: {exc}")
            STATE.error = str(exc)
            await emit()
            return
    STATE.error = ""
    await emit()


async def handle_command(cmd: dict[str, Any]) -> None:
    action = cmd.get("cmd")
    if action == "spatial_reset":
        await reset()
    elif action == "spatial_sweep_start":
        await start_sweep(
            int(cmd.get("point_index", 0)),
            int(cmd.get("point_total", STATE.point_total or 5)),
        )
    elif action == "spatial_point_done":
        await point_done(int(cmd.get("completed_points", STATE.completed_points + 1)))
    elif action == "spatial_set_phase":
        await set_phase(str(cmd.get("phase") or "idle"))
    elif action == "spatial_test_tone":
        swap = cmd.get("swapChannels")
        if swap is None:
            swap = cmd.get("swap_channels")
        await play_test_tone(
            str(cmd.get("channel") or "left"),
            swap_channels=bool(swap) if swap is not None else None,
        )
