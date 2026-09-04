"""
Whick 뮤직서버 — FastAPI (v4 remote_api.js 계약 SSOT)
재생: WebSocket + MPD(mpc) · 카탈로그: PostgreSQL
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import re
import subprocess
import time
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from pathlib import Path
from datetime import datetime, timezone

import asyncpg
import httpx
from fastapi import Body, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.device_auth import auth_enabled, load_device_token, token_from_ws, verify_destructive, verify_http
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from api.radio_catalog import (
    RADIO_STATIONS,
    radio_public_station,
    radio_station_by_id,
    resolve_radio_stream_url,
)
from api.playback_prefetch import prefetch_track_paths

RepeatMode = Literal["none", "one", "all"]
SourceMode = Literal["library", "radio", "idle", "spotify", "tidal"]
StreamingProvider = Literal["spotify", "tidal"]

DB_URL = os.getenv("DATABASE_URL", "postgresql://whick:password@localhost/whickdb")
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")
# 1차: YouTube·Tidal 등 외부 음원 제공업체 제외 (라디오·룸보정·로컬 FLAC 포함)
EXTERNAL_PROVIDERS_ENABLED = os.getenv("WHICK_PLAYER_EXTERNAL_PROVIDERS", "0") == "1"


@dataclass
class PlayerState:
    source: SourceMode = "idle"
    playing: bool = False
    track_id: int | None = None
    radio_station_id: str | None = None
    streaming_provider: StreamingProvider | None = None
    stream_id: str | None = None
    stream_queue: list[dict[str, Any]] = field(default_factory=list)
    title: str = ""
    artist: str = ""
    album: str = ""
    genre: str = ""
    composer: str = ""
    filename: str = ""
    format: str = ""
    play_count: int = 0
    duration: int = 0
    position: int = 0
    volume: int = 70
    track_replay_gain_db: float = 0.0
    shuffle: bool = False
    repeat: RepeatMode = "none"
    quality: str = ""
    playback: dict[str, Any] = field(default_factory=dict)
    play_context: dict[str, str] = field(default_factory=dict)
    queue: list[int] = field(default_factory=list)
    library_total: int = 0
    mpd_active: bool = False
    server_audio_active: bool = False
    # 레거시 필드 — 모바일 독립 존(MOBILE_SESSIONS) 도입 후 전역 독점에 쓰지 않음
    mobile_owner_client_id: str | None = None
    _transition: bool = field(default=False, repr=False, compare=False)  # MPD 전환 중 — 브로드캐스트 블록

    def to_payload(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("_transition", None)
        return {"event": "state", **d}


STATE = PlayerState()
db_pool: asyncpg.Pool | None = None

# 각 브라우저/PWA의 모바일 출력은 독립 존이다. 서버 스피커 STATE와 섞지 않는다.
# 프로세스 재시작 후에는 클라이언트가 현재 곡을 다시 선택하면 세션이 복원된다.
MOBILE_SESSIONS: dict[str, PlayerState] = {}
MAX_MOBILE_SESSIONS = 128


def _mobile_session(client_id: str) -> PlayerState:
    state = MOBILE_SESSIONS.get(client_id)
    if state is None:
        if len(MOBILE_SESSIONS) >= MAX_MOBILE_SESSIONS:
            MOBILE_SESSIONS.pop(next(iter(MOBILE_SESSIONS)), None)
        state = PlayerState(mobile_owner_client_id=client_id)
        MOBILE_SESSIONS[client_id] = state
    return state


def _mobile_payload(client_id: str, state: PlayerState | None = None) -> dict[str, Any]:
    payload = (state or _mobile_session(client_id)).to_payload()
    payload["output_scope"] = "mobile"
    payload["mobile_owner_client_id"] = client_id
    return payload


class ConnectionManager:
    def __init__(self) -> None:
        self.connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.connections.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self.connections:
            self.connections.remove(ws)

    async def broadcast(self, data: dict[str, Any]) -> None:
        msg = json.dumps(data, ensure_ascii=False)
        dead: list[WebSocket] = []
        for ws in self.connections:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()
spectrum_engine: Any = None


def mpd_cmd(command: str) -> None:
    try:
        subprocess.run(
            ["mpc", "--quiet", *command.split()],
            timeout=3,
            capture_output=True,
            check=False,
        )
    except Exception as exc:
        print(f"[MPD] {command} → {exc}")


def mpd_sync_repeat_from_state() -> None:
    """STATE.repeat → mpc (repeat 액션과 동일)."""
    mpd_cmd(f"repeat {'1' if STATE.repeat in ('one', 'all') else '0'}")
    mpd_cmd(f"single {'on' if STATE.repeat == 'one' else 'off'}")


def mpd_disable_loop_for_calibration() -> None:
    """룸보정 스윕/톤 — MPD 반복 재생 금지 (repeat on 이면 8s WAV 무한 루프)."""
    mpd_cmd("repeat off")
    mpd_cmd("single off")


def effective_volume_gain_db() -> float:
    """믹서에 곱할 dB 게인 — 라이브러리 라우드니스 + 라디오 감쇠.

    라디오 스트림은 방송 레벨이 보통 더 뜨거워 라이브러리와 갈아타면 놀랄 수 있다.
    WHICK_RADIO_VOLUME_OFFSET_DB (기본 -1.5, 0~-12만) 로 라디오만 살짝 줄인다.
    """
    if STATE.source == "radio":
        try:
            off = float(os.getenv("WHICK_RADIO_VOLUME_OFFSET_DB", "-1.5") or "-1.5")
        except ValueError:
            off = -1.5
        return max(-12.0, min(0.0, off))

    rg = float(STATE.track_replay_gain_db or 0.0)
    try:
        from api.loudness_normalize import load_settings

        # 라우드니스 OFF면 DB에 남아 있는 replay_gain_db도 믹서에 섞지 않음
        if not load_settings().get("enabled", True):
            return 0.0
    except Exception:
        pass
    return rg


def mpd_set_volume(vol: int) -> None:
    from api.alsa_device import set_playback_volume

    set_playback_volume(vol, replay_gain_db=effective_volume_gain_db())


def set_track_replay_gain(db: float | None) -> None:
    try:
        STATE.track_replay_gain_db = float(db or 0.0)
    except (TypeError, ValueError):
        STATE.track_replay_gain_db = 0.0
    mpd_set_volume(STATE.volume)


def stop_server_audio_output() -> None:
    """MPD + 외부 DSD ffmpeg 프로세스 정지."""
    from api.dsd_playback import stop_external_dsd_player

    stop_external_dsd_player()
    mpd_cmd("stop")


_CALIBRATION_NAME_MARKERS = (
    "log-sweep",
    "test-left",
    "test-right",
    "test-tone",
)


def mpd_current_file() -> str:
    try:
        proc = subprocess.run(
            ["mpc", "--quiet", "-f", "%file%", "current"],
            timeout=3,
            capture_output=True,
            text=True,
            check=False,
        )
        return (proc.stdout or "").strip()
    except Exception:
        return ""


def mpd_is_calibration_current() -> bool:
    cur = mpd_current_file().lower()
    if not cur:
        return False
    return any(marker in cur for marker in _CALIBRATION_NAME_MARKERS)


# 룸보정 스윕/테스트톤 재생 중 — cmd_next·stop 이 큐를 바꿔 비프를 끊지 못하게 함
_calibration_guard_until = 0.0


def _arm_calibration_guard(duration_sec: float) -> None:
    global _calibration_guard_until
    _calibration_guard_until = time.time() + max(1.0, float(duration_sec)) + 0.75


def _clear_calibration_guard() -> None:
    global _calibration_guard_until
    _calibration_guard_until = 0.0


def calibration_playback_active() -> bool:
    if time.time() < _calibration_guard_until:
        return True
    return mpd_is_calibration_current()


def _wav_duration_sec(path: str, fallback: float = 8.0) -> float:
    try:
        import wave

        with wave.open(path, "rb") as wf:
            rate = float(wf.getframerate() or 0)
            frames = float(wf.getnframes() or 0)
            if rate > 0 and frames > 0:
                return frames / rate
    except Exception:
        pass
    return fallback


def mpd_clear_queue() -> None:
    """MPD 큐 비우기 — 공간음향 스윕/테스트톤 잔류 제거."""
    try:
        subprocess.run(
            ["mpc", "--quiet", "stop"],
            timeout=3,
            capture_output=True,
            check=False,
        )
        subprocess.run(
            ["mpc", "--quiet", "clear"],
            timeout=3,
            capture_output=True,
            check=False,
        )
    except Exception as exc:
        print(f"[MPD] clear queue: {exc}")


def mpd_play_file(path: str) -> None:
    music_root = os.getenv("WHICK_MUSIC_DIR", "/var/lib/whick/library/music")
    rel = path
    use_abs = False
    if path.startswith(music_root + "/"):
        rel = path[len(music_root) + 1 :]
    elif path.startswith("/media/") or path.startswith("/run/media/"):
        # 외장 — MPD music_directory 밖 절대경로
        rel = path
        use_abs = True
    elif path.startswith("/"):
        rel = f"tones/{os.path.basename(path)}"
    print(f"[DIAG] mpd_play_file path={path} → rel={rel} abs={use_abs}")
    try:
        r1 = subprocess.run(
            ["mpc", "--quiet", "clear"],
            timeout=3,
            capture_output=True,
            text=True,
            check=False,
        )
        print(f"[DIAG] mpc clear → rc={r1.returncode} err={r1.stderr.strip()[:100]}")
        r2 = subprocess.run(
            ["mpc", "--quiet", "add", rel],
            timeout=3,
            capture_output=True,
            text=True,
            check=False,
        )
        print(f"[DIAG] mpc add {rel} → rc={r2.returncode} err={r2.stderr.strip()[:100]}")
        r3 = subprocess.run(
            ["mpc", "--quiet", "play"],
            timeout=3,
            capture_output=True,
            text=True,
            check=False,
        )
        print(f"[DIAG] mpc play → rc={r3.returncode} err={r3.stderr.strip()[:100]}")
    except Exception as exc:
        print(f"[MPD] play {path} → {exc}")


def mpd_play_url(url: str) -> None:
    """HTTP(S) 라디오 스트림 — MPD → CamillaDSP 재생 경로."""
    try:
        subprocess.run(
            ["mpc", "--quiet", "clear"],
            timeout=5,
            capture_output=True,
            check=False,
        )
        subprocess.run(
            ["mpc", "--quiet", "add", url],
            timeout=5,
            capture_output=True,
            check=False,
        )
        subprocess.run(
            ["mpc", "--quiet", "play"],
            timeout=5,
            capture_output=True,
            check=False,
        )
    except Exception as exc:
        print(f"[MPD] play url → {exc}")


def mpd_status() -> tuple[int, int, bool]:
    """(elapsed_sec, duration_sec, playing)"""
    try:
        out = subprocess.run(
            ["mpc", "status"],
            timeout=3,
            capture_output=True,
            text=True,
            check=False,
        )
        text = out.stdout or ""
        playing = "[playing]" in text
        elapsed, duration = 0, 0
        m = re.search(r"(\d+):(\d+)/(\d+):(\d+)", text)
        if m:
            elapsed = int(m.group(1)) * 60 + int(m.group(2))
            duration = int(m.group(3)) * 60 + int(m.group(4))
        return elapsed, duration, playing
    except Exception:
        return STATE.position, STATE.duration, STATE.playing


async def refresh_library_total() -> None:
    if not db_pool:
        return
    try:
        STATE.library_total = await db_pool.fetchval("SELECT COUNT(*) FROM tracks") or 0
    except Exception:
        pass


async def sync_state_from_mpd() -> None:
    if not STATE.mpd_active:
        return
    if STATE.source not in ("library", "tidal", "radio"):
        return
    elapsed, duration, playing = mpd_status()
    if duration > 0:
        STATE.duration = duration
        STATE.position = min(elapsed, duration)
    # STATE.playing 은 명령 핸들러가 SSOT — MPD polling 으로 덮어쓰지 않음


async def broadcast_spectrum(bands: list[float], source: str) -> None:
    if not STATE.playing or not STATE.server_audio_active:
        return
    if STATE.source == "radio":
        return
    await manager.broadcast(
        {
            "event": "spectrum",
            "source": source,
            "playing": True,
            "bands": [round(float(b), 4) for b in bands],
            "band_count": len(bands),
        }
    )


async def broadcast_state() -> None:
    await sync_state_from_mpd()
    print(f"[DIAG] broadcast_state source={STATE.source} tid={STATE.track_id} title={STATE.title[:30] if STATE.title else ''} radio={STATE.radio_station_id} playing={STATE.playing} mpd_active={STATE.mpd_active} qlen={len(STATE.queue)}")
    await manager.broadcast(STATE.to_payload())


async def state_broadcaster() -> None:
    tick = 0
    while True:
        if manager.connections and not STATE._transition:
            if STATE.source in ("library", "tidal") and STATE.playing and STATE.duration > 0:
                await sync_state_from_mpd()
                # 스윕/톤이 MPD에 있으면 duration=8s 로 바뀌어 cmd_next 가 스윕을 끊음
                if (
                    STATE.source == "library"
                    and STATE.position >= STATE.duration
                    and STATE.duration > 0
                    and not calibration_playback_active()
                ):
                    await cmd_next()
            elif STATE.source in ("library", "tidal"):
                await sync_state_from_mpd()
            if STATE.source == "library" and STATE.playing and tick % 5 == 0 and STATE.track_id:
                try:
                    from api.dsp_store import get_profile
                    from api.playback_router import build_playback_state

                    prof = await get_profile(db_pool) if db_pool else {}
                    dsp = prof.get("dsp") or {}
                    pb = STATE.playback or {}
                    STATE.playback = build_playback_state(
                        dsp,
                        source_bit_depth=pb.get("source_bit_depth"),
                        source_sample_rate=pb.get("source_sample_rate"),
                        source_format=pb.get("source_format", ""),
                        file_path=str(pb.get("file_path") or ""),
                    )
                except Exception:
                    pass
            if tick % 30 == 0:
                await refresh_library_total()
            await manager.broadcast(STATE.to_payload())
        tick += 1
        await asyncio.sleep(1)


async def wait_for_tracks_table(pool: asyncpg.Pool, *, attempts: int = 60) -> None:
    """player-db init.sql 또는 install-runtime schema apply 대기."""
    for attempt in range(attempts):
        try:
            async with pool.acquire() as conn:
                if await conn.fetchval("SELECT to_regclass('public.tracks')"):
                    return
        except Exception as exc:
            print(f"[DB] tracks table wait {attempt + 1}/{attempts}: {exc}")
        await asyncio.sleep(2)
    raise RuntimeError("tracks table not ready — check player-db init.sql / install-runtime")


async def ensure_play_context_schema(pool: asyncpg.Pool) -> None:
    """기존 고객 DB에도 날씨·시간·분위기 재생 차원을 안전하게 추가."""
    async with pool.acquire() as conn:
        for column, sql_type in (
            ("weather", "VARCHAR(32)"),
            ("period", "VARCHAR(32)"),
            ("mood", "VARCHAR(64)"),
            ("location_label", "VARCHAR(128)"),
        ):
            await conn.execute(
                f"ALTER TABLE play_history ADD COLUMN IF NOT EXISTS {column} {sql_type}"
            )


async def ensure_tracks_meta_schema(pool: asyncpg.Pool) -> None:
    """기존 고객 DB에 작곡가·스토리지 출처·검색 키워드 컬럼을 안전하게 추가."""
    async with pool.acquire() as conn:
        await conn.execute(
            "ALTER TABLE tracks ADD COLUMN IF NOT EXISTS composer VARCHAR(300)"
        )
        await conn.execute(
            "ALTER TABLE tracks ADD COLUMN IF NOT EXISTS storage_source VARCHAR(20) DEFAULT 'internal'"
        )
        # robot-classifier가 분류 시점에 1회 생성하는 AI 검색 보조 키워드
        # (원어+영어 번역/원제/동의어). 검색 때마다 AI를 부르지 않고 여기 저장된
        # 값을 함께 ILIKE 매칭해 안정적으로 재사용한다.
        await conn.execute(
            "ALTER TABLE tracks ADD COLUMN IF NOT EXISTS search_keywords TEXT"
        )
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
        # 오타·유사 검색 (없으면 조용히 스킵 — 권한 없는 환경 대비)
        try:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tracks_title_trgm "
                "ON tracks USING gin (title gin_trgm_ops)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tracks_composer_trgm "
                "ON tracks USING gin (composer gin_trgm_ops)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tracks_keywords_trgm "
                "ON tracks USING gin (search_keywords gin_trgm_ops)"
            )
        except Exception as exc:
            print(f"[DB] pg_trgm skip: {exc}")


async def ensure_ops_consent_schema(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ops_consent (
                id              VARCHAR(64) PRIMARY KEY,
                title           VARCHAR(200) NOT NULL DEFAULT '원격 조치 동의 요청',
                message         TEXT NOT NULL DEFAULT '',
                purpose         VARCHAR(100) DEFAULT '',
                command_type    VARCHAR(100) DEFAULT '',
                agree_url       VARCHAR(500) DEFAULT '',
                reject_url      VARCHAR(500) DEFAULT '',
                status          VARCHAR(20) NOT NULL DEFAULT 'pending',
                received_at     TIMESTAMPTZ DEFAULT now()
            )
            """
        )


def track_list_row(row: asyncpg.Record) -> dict[str, Any]:
    """라이브러리·메타 패널용 공통 직렬화."""
    fp = str(row.get("file_path") or "")
    composer = (row.get("composer") or "").strip() if "composer" in row.keys() else ""
    genre = (row.get("genre") or "").strip() if "genre" in row.keys() else ""
    if not composer and genre and ("classical" in genre.lower() or "클래식" in genre):
        composer = (row.get("artist") or "").strip()
    if "storage_source" in row.keys() and row.get("storage_source"):
        storage_source = str(row.get("storage_source"))
    elif fp.startswith("/media/") or fp.startswith("/run/media/"):
        storage_source = "external"
    else:
        storage_source = "internal"
    return {
        "track_id": row["track_id"],
        "title": row.get("title") or "",
        "artist": row.get("artist") or "",
        "album": row.get("album") or "",
        "genre": genre or None,
        "composer": composer or None,
        "duration_sec": row.get("duration_sec"),
        "bit_depth": row.get("bit_depth"),
        "sample_rate": row.get("sample_rate"),
        "format": row.get("format"),
        "file_path": fp or None,
        "filename": Path(fp).name if fp else None,
        "play_count": int(row.get("play_count") or 0),
        "quality": row.get("quality"),
        "license": row.get("license"),
        "storage_source": storage_source,
        "offline": bool(fp) and not Path(fp).is_file(),
        "replay_gain_db": (
            float(row["replay_gain_db"])
            if "replay_gain_db" in row.keys() and row.get("replay_gain_db") is not None
            else None
        ),
        "loudness_i": (
            float(row["loudness_i"])
            if "loudness_i" in row.keys() and row.get("loudness_i") is not None
            else None
        ),
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool
    for attempt in range(30):
        try:
            db_pool = await asyncpg.create_pool(DB_URL, min_size=2, max_size=10)
            break
        except Exception as exc:
            print(f"[DB] connect retry {attempt + 1}/30: {exc}")
            await asyncio.sleep(2)
    if not db_pool:
        raise RuntimeError("PostgreSQL unavailable")
    await wait_for_tracks_table(db_pool)
    await ensure_play_context_schema(db_pool)
    await ensure_tracks_meta_schema(db_pool)
    try:
        from api.loudness_normalize import ensure_loudness_schema, start_worker

        await ensure_loudness_schema(db_pool)
        loud_task = start_worker(db_pool)
    except Exception as exc:
        print(f"[loudness] start skip: {exc}")
        loud_task = None
    # mpc CLI 는 `volume <n>` (절대값) 사용 — `setvol` 은 MPD 프로토콜 전용이라
    # `mpc setvol` 은 "unknown command" 로 실패한다(리모컨 볼륨이 안 먹던 원인).
    mpd_set_volume(STATE.volume)
    if os.getenv("WHICK_LIBRARY_SCAN_ON_START", "1") == "1":
        from api.library_scanner import scan_library, scan_paths_from_env

        await scan_library(db_pool, scan_paths_from_env())
        await refresh_library_total()
        mpd_cmd("update")
    from api.dsp_store import ensure_schema, get_profile
    from api import spatial_session

    # 스윕/톤 종료 후 clear 가 다음 측정 재생을 끊지 않도록 세대(token)로 무효화
    calib_cleanup_gen = {"n": 0}
    calib_cleanup_task: dict[str, asyncio.Task | None] = {"task": None}

    def _cancel_calib_cleanup() -> None:
        task = calib_cleanup_task.get("task")
        if task and not task.done():
            task.cancel()
        calib_cleanup_task["task"] = None
        calib_cleanup_gen["n"] += 1

    def _schedule_calib_cleanup(delay_sec: float, label: str) -> None:
        _cancel_calib_cleanup()
        calib_cleanup_gen["n"] += 1
        gen = calib_cleanup_gen["n"]
        delay = max(1.0, float(delay_sec))

        async def _cleanup() -> None:
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                return
            if gen != calib_cleanup_gen["n"]:
                return
            if mpd_is_calibration_current():
                clear_spatial_mpd(force=True)
                print(f"[spatial] {label} MPD queue cleared")

        try:
            calib_cleanup_task["task"] = asyncio.get_running_loop().create_task(_cleanup())
        except RuntimeError:
            pass

    def play_sweep_file() -> None:
        path = os.getenv("WHICK_SWEEP_WAV", "/var/lib/whick/library/music/tones/log-sweep.wav")
        if not os.path.isfile(path):
            raise FileNotFoundError(path)
        # 이미 스윕 재생 중이면 clear+play 금지 (중간에 끊겼다가 처음부터 다시 재생됨)
        if calibration_playback_active() and mpd_is_calibration_current():
            elapsed, duration, playing = mpd_status()
            if playing and duration > 0 and elapsed < max(0.5, duration - 0.5):
                print(
                    f"[spatial] skip duplicate sweep play "
                    f"(elapsed={elapsed}s/{duration}s)"
                )
                return
        # 라이브러리 재생 중이면 duration 동기화가 스윕 길이로 바뀌며 cmd_next 가 개입함 → 가드
        wav_sec = _wav_duration_sec(path, 8.0)
        sweep_sec = float(os.getenv("WHICK_SPATIAL_SWEEP_SEC", str(wav_sec + 1.0)))
        _arm_calibration_guard(sweep_sec)
        mpd_disable_loop_for_calibration()
        mpd_play_file(path)
        # 스윕 종료 후 큐 clear — 안 하면 ▶ 가 부밍음(스윕)을 재개함
        _schedule_calib_cleanup(sweep_sec, "sweep")

    async def play_test_tone_mpd(channel: str, *, swap_channels: bool | None = None) -> None:
        # swap_channels는 API 호환용으로만 받음. 파일 선반전 금지 —
        # 좌우반전은 CamillaDSP mixer(swapChannels)가 단독 적용해야
        # 테스트 톤으로 반전 on/off를 귀로 확인할 수 있다.
        _ = swap_channels
        logical = "right" if str(channel).lower().startswith("r") else "left"
        base = os.getenv("WHICK_TONE_DIR", "/var/lib/whick/library/music/tones")
        path = os.path.join(base, f"test-{logical}.wav")
        if not os.path.isfile(path):
            raise FileNotFoundError(path)
        tone_sec = _wav_duration_sec(path, 3.0)
        _arm_calibration_guard(max(3.0, tone_sec + 0.5))
        mpd_disable_loop_for_calibration()
        mpd_play_file(path)
        _schedule_calib_cleanup(max(3.0, tone_sec + 0.5), "test-tone")

    def clear_spatial_mpd(*, force: bool = False) -> None:
        # 스윕/톤이 아직 나오면 reset·result 로 clear 해도 비프가 끊김 → 끝날 때까지 미룸
        if not force and mpd_is_calibration_current():
            elapsed, duration, playing = mpd_status()
            if playing and duration > 0:
                remaining = float(duration) - float(elapsed)
                if remaining > 0.35:
                    _schedule_calib_cleanup(remaining + 0.6, "deferred-clear")
                    print(
                        f"[spatial] defer clear "
                        f"(calibration still playing {elapsed}s/{duration}s)"
                    )
                    return
        _cancel_calib_cleanup()
        calib_cleanup_gen["n"] += 1
        _clear_calibration_guard()
        mpd_clear_queue()
        mpd_sync_repeat_from_state()
        # MPD만 비우고 STATE.playing 이 True로 남으면 리모컨 UI가 재생 중으로 표시됨 (Bugbot)
        STATE.playing = False
        STATE.mpd_active = False
        try:
            asyncio.get_running_loop().create_task(broadcast_state())
        except RuntimeError:
            pass

    spatial_session.bind_handlers(
        manager.broadcast,
        play_sweep_file,
        play_test_tone_mpd,
        clear_mpd=clear_spatial_mpd,
    )

    from api.spectrum_engine import SpectrumEngine

    global spectrum_engine
    fifo_path = os.getenv("WHICK_SPECTRUM_FIFO", "/var/lib/whick/run/mpd-spectrum.pcm")
    spectrum_engine = SpectrumEngine(
        fifo_path,
        broadcast_spectrum,
        is_playing=lambda: STATE.playing and STATE.server_audio_active,
        source=lambda: STATE.source,
    )
    spec_task = spectrum_engine.start()

    await ensure_schema(db_pool)
    from api.dac_capability import ensure_dac_capability_detected

    ensure_dac_capability_detected()
    from api.guest_share_store import ensure_schema as guest_share_ensure_schema

    await guest_share_ensure_schema(db_pool)
    await ensure_ops_consent_schema(db_pool)
    prof = await get_profile(db_pool)
    from api.audio_pipeline import ensure_default_profile, reload_profile
    from api.playback_router import ensure_mpd_after_boot, sync_playback_route

    dsp = prof.get("dsp") or {}
    if not prof.get("camillaPath"):
        ensure_default_profile()
    else:
        reload_profile(dsp)
    try:
        # entrypoint가 이미 mpd를 기동함 — conf 불변·healthy면 kill/restart 생략
        boot = ensure_mpd_after_boot(dsp)
        print(
            "[player] mpd boot sync",
            f"ok={boot.get('mpd', {}).get('ok')}",
            f"skipped={boot.get('mpd', {}).get('skipped')}",
            f"conf_changed={boot.get('conf_changed')}",
        )
    except Exception as exc:
        print(f"[player] mpd conf sync: {exc}")
        sync_playback_route(dsp)
    task = asyncio.create_task(state_broadcaster())
    usb_task = asyncio.create_task(usb_library_watcher())
    dac_task = asyncio.create_task(dac_hotplug_watcher())
    camilla_task = asyncio.create_task(camilla_watchdog())
    yield
    camilla_task.cancel()
    dac_task.cancel()
    usb_task.cancel()
    task.cancel()
    if loud_task is not None:
        loud_task.cancel()
    try:
        from api.loudness_normalize import stop_worker

        stop_worker()
    except Exception:
        pass
    spec_task.cancel()
    if spectrum_engine:
        spectrum_engine.stop()
    if db_pool:
        await db_pool.close()


app = FastAPI(title="Whick Music Server API", version="1.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

_PUBLIC_HTTP = {"/health", "/docs", "/openapi.json", "/redoc", "/api/radio", "/favicon.ico", "/index.html", "/manifest.webmanifest", "/sw.js"}

# 음원 파일 파괴 경로 — 인증 여부와 무관하게 항상 device_token 검증
# (소유자 1명만 쓰기 허용, LAN WiFi 접근 기기는 읽기 전용)
_DESTRUCTIVE_PATHS = {
    "/api/library/fs/delete",
    "/api/library/fs/rename",
    "/api/library/delete-incoming",
    "/api/library/tracks/delete",
}

REMOTE_UI_ROOT = Path(os.getenv("WHICK_REMOTE_UI_ROOT", "/app/remote-ui"))


@app.middleware("http")
async def device_token_http_middleware(request: Request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)

    # 파일시스템 파괴 경로 — 항상 device_token 검증 (미설정 시에도 차단)
    if request.url.path in _DESTRUCTIVE_PATHS:
        try:
            verify_destructive(request)
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        return await call_next(request)

    if not auth_enabled():
        return await call_next(request)
    if request.url.path in _PUBLIC_HTTP:
        return await call_next(request)
    if request.url.path == "/":
        return await call_next(request)
    if request.url.path.startswith(("/js/", "/css/", "/img/")):
        return await call_next(request)
    if request.url.path.startswith("/api/guest/stream/") or request.url.path == "/api/guest/shares/resolve":
        return await call_next(request)
    # GET 요청은 읽기 전용 — 토큰 없이 허용 (WS에서 이미 쓰기 인증)
    if request.method == "GET" and request.url.path.startswith("/api/"):
        return await call_next(request)
    try:
        verify_http(request)
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    return await call_next(request)


def _mount_remote_ui_static() -> None:
    if not REMOTE_UI_ROOT.is_dir():
        return
    for name in ("js", "css", "img"):
        d = REMOTE_UI_ROOT / name
        if d.is_dir():
            app.mount(f"/{name}", StaticFiles(directory=str(d)), name=f"remote_ui_{name}")


_mount_remote_ui_static()


def clear_library_meta_fields() -> None:
    STATE.genre = ""
    STATE.composer = ""
    STATE.filename = ""
    STATE.format = ""
    STATE.play_count = 0
    STATE.track_replay_gain_db = 0.0


def track_quality(row: asyncpg.Record) -> str:
    bd = row.get("bit_depth") or 16
    sr = row.get("sample_rate") or 44100
    sr_k = sr // 1000 if sr >= 1000 else sr
    fmt = row.get("format") or "FLAC"
    return f"{bd}/{sr_k} {fmt}"


async def prepare_library_playback(row: asyncpg.Record) -> dict[str, Any]:
    """곡 재생 전 경로 선택 · MPD 출력 전환 · playback 상태."""
    from api.dsp_store import get_profile, write_camilla_file
    from api.dsd_playback import is_dsd_file, stop_external_dsd_player
    from api.playback_router import (
        build_playback_state,
        profile_needs_dsp,
        sync_playback_route,
        write_current_playback,
    )

    dsp_profile: dict[str, Any] = {}
    if db_pool:
        prof = await get_profile(db_pool)
        dsp_profile = prof.get("dsp") or {}

    fp = str(row.get("file_path") or "")
    is_dsd = is_dsd_file(fp)
    raw_sr = int(row.get("sample_rate") or 44100)
    write_current_playback(
        bit_depth=int(row.get("bit_depth") or (1 if is_dsd else 16)),
        sample_rate=raw_sr,
        source_format=str(row.get("format") or ""),
        file_path=fp,
        is_dsd=is_dsd,
    )
    stop_external_dsd_player()
    if profile_needs_dsp(dsp_profile) and not is_dsd:
        write_camilla_file(dsp_profile)
    sync_playback_route(dsp_profile)
    return build_playback_state(
        dsp_profile,
        source_bit_depth=int(row.get("bit_depth") or (1 if is_dsd else 16)),
        source_sample_rate=raw_sr,
        source_format=str(row.get("format") or ""),
        file_path=fp,
    )


async def play_library_file(row: asyncpg.Record, *, mpd_play: bool = True) -> None:
    """라이브러리 곡 재생 — 페이드 · DSD/PCM 경로."""
    from api.dsd_playback import (
        dsd_format_from_rate,
        dop_wrapper_rate,
        is_dsd_file,
        play_dsd_external,
        stop_external_dsd_player,
    )
    from api.playback_fade import transition_if_rate_changed, write_last_playback

    path = str(row.get("file_path") or "")
    is_dsd = is_dsd_file(path)
    raw_sr = int(row.get("sample_rate") or 44100)
    fade_sr = dop_wrapper_rate(dsd_format_from_rate(raw_sr)) if is_dsd else raw_sr

    if mpd_play:
        await transition_if_rate_changed(
            new_sample_rate=fade_sr,
            is_dsd=is_dsd,
            current_volume=STATE.volume,
        )
        stop_external_dsd_player()
        mpd_play_file(path)
        if is_dsd:
            await asyncio.sleep(0.4)
            _, _, playing = mpd_status()
            if not playing:
                print(f"[DSD] MPD play failed — ffmpeg fallback: {path}")
                if play_dsd_external(path, raw_sample_rate=raw_sr):
                    STATE.mpd_active = False
        write_last_playback(sample_rate=fade_sr, is_dsd=is_dsd)


async def build_album_queue(track_id: int) -> list[int]:
    if not db_pool:
        return [track_id]
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT album, artist FROM tracks WHERE track_id = $1",
            track_id,
        )
        if not row or not row["album"]:
            return [track_id]
        rows = await conn.fetch(
            """SELECT track_id, sample_rate FROM tracks
               WHERE album = $1 AND artist = $2
               ORDER BY title""",
            row["album"],
            row["artist"],
        )
    ids = [r["track_id"] for r in rows] or [track_id]
    if os.getenv("WHICK_QUEUE_ALIGN_SR", "0") != "1" or len(ids) <= 1:
        return ids
    indexed = list(enumerate(rows))
    indexed.sort(key=lambda t: (int(t[1]["sample_rate"] or 44100), t[0]))
    return [t[1]["track_id"] for t in indexed]


async def cmd_play_streaming(
    provider: StreamingProvider,
    stream_id: str,
    *,
    meta: dict[str, Any] | None = None,
    queue: list[dict[str, Any]] | None = None,
    mpd_play: bool = True,
) -> None:
    from api import streaming_playback

    meta = meta or {}
    if queue is not None:
        STATE.stream_queue = queue
    elif not STATE.stream_queue:
        STATE.stream_queue = [
            {
                "source": provider,
                "stream_id": stream_id,
                "title": meta.get("title", ""),
                "artist": meta.get("artist", ""),
                "album": meta.get("album", ""),
                "duration_sec": meta.get("duration_sec", 0),
                "quality": meta.get("quality", ""),
                "uri": meta.get("uri", stream_id),
            }
        ]

    await streaming_playback.play_streaming_track(
        provider,
        stream_id,
        meta=meta,
        queue=STATE.stream_queue,
        mpd_play=mpd_play,
    )

    STATE.source = provider
    STATE.streaming_provider = provider
    STATE.stream_id = stream_id
    STATE.track_id = None
    STATE.radio_station_id = None
    STATE.title = str(meta.get("title") or "")
    STATE.artist = str(meta.get("artist") or "")
    STATE.album = str(meta.get("album") or "")
    clear_library_meta_fields()
    STATE.duration = int(meta.get("duration_sec") or 0)
    STATE.position = 0
    STATE.quality = str(meta.get("quality") or "")
    STATE.playing = True
    STATE.mpd_active = mpd_play
    STATE.server_audio_active = mpd_play
    if mpd_play:
        mpd_set_volume(STATE.volume)
    if not STATE.stream_queue or not STATE.stream_id:
        return
    ids = [str(t.get("stream_id") or "") for t in STATE.stream_queue]
    if STATE.stream_id not in ids:
        nxt = STATE.stream_queue[0]
    else:
        idx = ids.index(STATE.stream_id)
        if idx + 1 >= len(STATE.stream_queue):
            if STATE.repeat == "all":
                nxt = STATE.stream_queue[0]
            else:
                STATE.playing = False
                await broadcast_state()
                return
        else:
            nxt = STATE.stream_queue[idx + 1]
    provider = str(nxt.get("source") or STATE.streaming_provider or "spotify")
    if provider not in ("spotify", "tidal"):
        provider = "spotify"
    await cmd_play_streaming(
        provider,  # type: ignore[arg-type]
        str(nxt.get("stream_id") or ""),
        meta=nxt,
        queue=STATE.stream_queue,
        mpd_play=mpd_play,
    )


async def cmd_prev_streaming(*, mpd_play: bool = True) -> None:
    if not STATE.stream_queue or not STATE.stream_id:
        STATE.position = 0
        return
    ids = [str(t.get("stream_id") or "") for t in STATE.stream_queue]
    idx = ids.index(STATE.stream_id) if STATE.stream_id in ids else 0
    nxt = STATE.stream_queue[max(0, idx - 1)]
    provider = str(nxt.get("source") or STATE.streaming_provider or "spotify")
    if provider not in ("spotify", "tidal"):
        provider = "spotify"
    await cmd_play_streaming(
        provider,  # type: ignore[arg-type]
        str(nxt.get("stream_id") or ""),
        meta=nxt,
        queue=STATE.stream_queue,
        mpd_play=mpd_play,
    )


async def cmd_play_track(
    track_id: int,
    *,
    queue: list[int] | None = None,
    mpd_play: bool = True,
    context: dict[str, Any] | None = None,
) -> None:
    if not db_pool:
        return
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM tracks WHERE track_id = $1", track_id)
    if not row:
        return
    if queue is not None:
        STATE.queue = queue
    elif not STATE.queue or track_id not in STATE.queue:
        STATE.queue = await build_album_queue(track_id)
    STATE.source = "library"
    STATE.radio_station_id = None
    STATE.streaming_provider = None
    STATE.stream_id = None
    STATE.track_id = track_id
    STATE.title = row["title"] or ""
    STATE.artist = row["artist"] or ""
    STATE.album = row["album"] or ""
    STATE.genre = (row.get("genre") or "") if "genre" in row.keys() else ""
    composer = (row.get("composer") or "").strip() if "composer" in row.keys() else ""
    if not composer and STATE.genre and (
        "classical" in STATE.genre.lower() or "클래식" in STATE.genre
    ):
        composer = STATE.artist
    STATE.composer = composer
    fp = str(row.get("file_path") or "")
    STATE.filename = Path(fp).name if fp else ""
    STATE.format = str(row.get("format") or "")
    STATE.play_count = int(row.get("play_count") or 0) + 1  # 곧 +1 반영
    STATE.duration = row["duration_sec"] or 0
    STATE.position = 0
    STATE.quality = track_quality(row)
    if isinstance(context, dict):
        STATE.play_context = {
            key: str(context.get(key) or "")[:limit]
            for key, limit in (
                ("weather", 32),
                ("period", 32),
                ("mood", 64),
                ("location_label", 128),
            )
            if str(context.get(key) or "").strip()
        }
    try:
        rg = row.get("replay_gain_db") if "replay_gain_db" in row.keys() else None
        STATE.track_replay_gain_db = float(rg) if rg is not None else 0.0
    except (TypeError, ValueError):
        STATE.track_replay_gain_db = 0.0
    STATE.playback = await prepare_library_playback(row)
    STATE.mpd_active = mpd_play
    STATE.server_audio_active = mpd_play
    if mpd_play:
        STATE._transition = True
        try:
            await play_library_file(row, mpd_play=True)
            # 곡별 정규화 게인 반영 (play 직후 볼륨 재적용)
            mpd_set_volume(STATE.volume)
            # mpc 실패해도 playing=True로 두면 /health mpd:false 와 UI가 어긋난다
            if STATE.mpd_active:
                _, _, mpc_playing = mpd_status()
                STATE.playing = bool(mpc_playing)
                if not mpc_playing:
                    STATE.mpd_active = False
                    STATE.server_audio_active = False
                    print(f"[MPD] play requested but mpc not playing track_id={track_id}")
            else:
                # DSD external 등 MPD 우회 경로
                STATE.playing = True
        finally:
            STATE._transition = False
    else:
        STATE.playing = True
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE tracks SET play_count = play_count + 1, last_played = now() WHERE track_id = $1",
            track_id,
        )
        try:
            await conn.execute(
                """INSERT INTO play_history
                     (track_id, weather, period, mood, location_label)
                   VALUES ($1, $2, $3, $4, $5)""",
                track_id,
                STATE.play_context.get("weather"),
                STATE.play_context.get("period"),
                STATE.play_context.get("mood"),
                STATE.play_context.get("location_label"),
            )
        except Exception as exc:
            # 재생 자체는 유지 — 컨텍스트 컬럼 미적용 DB에서도 끊기지 않게.
            print(f"[play_history] insert skipped: {exc}")
            try:
                await conn.execute(
                    "INSERT INTO play_history (track_id) VALUES ($1)",
                    track_id,
                )
            except Exception as exc2:
                print(f"[play_history] fallback insert failed: {exc2}")

    # 다음 곡(들)을 페이지캐시에 올려 트랙 전환·순간 끊김 완화
    try:
        await _prefetch_upcoming_tracks(track_id)
    except Exception as exc:
        print(f"[prefetch] skipped: {exc}")


async def _prefetch_upcoming_tracks(current_id: int) -> None:
    q = list(STATE.queue or [])
    if not q or current_id not in q:
        return
    idx = q.index(current_id)
    upcoming: list[int] = []
    for offset in (1, 2):
        ni = idx + offset
        if ni < len(q):
            upcoming.append(q[ni])
        elif STATE.repeat == "all" and q:
            upcoming.append(q[ni % len(q)])
    if not upcoming or not db_pool:
        return
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT file_path FROM tracks WHERE track_id = ANY($1::int[])",
            upcoming,
        )
    paths = [str(r["file_path"]) for r in rows if r.get("file_path")]
    await prefetch_track_paths(paths)


async def cmd_next(*, mpd_play: bool = True) -> None:
    if mpd_play and calibration_playback_active():
        print("[spatial] skip cmd_next during calibration sweep/tone")
        return
    if STATE.source in ("spotify", "tidal"):
        await cmd_next_streaming(mpd_play=mpd_play)
        return
    if STATE.source == "radio":
        return
    if not STATE.queue:
        if mpd_play:
            mpd_cmd("next")
            await sync_state_from_mpd()
        return
    if STATE.shuffle and len(STATE.queue) > 1:
        candidates = [t for t in STATE.queue if t != STATE.track_id]
        nxt = random.choice(candidates) if candidates else STATE.queue[0]
        await cmd_play_track(nxt, queue=STATE.queue, mpd_play=mpd_play)
        return
    q = STATE.queue
    if STATE.track_id not in q:
        nxt = q[0]
    else:
        idx = q.index(STATE.track_id)
        if STATE.repeat == "one":
            nxt = STATE.track_id
        elif idx + 1 < len(q):
            nxt = q[idx + 1]
        elif STATE.repeat == "all":
            nxt = q[0]
        else:
            STATE.playing = False
            await broadcast_state()
            return
    await cmd_play_track(nxt, queue=STATE.queue, mpd_play=mpd_play)


async def cmd_prev(*, mpd_play: bool = True) -> None:
    if STATE.source in ("spotify", "tidal"):
        await cmd_prev_streaming(mpd_play=mpd_play)
        return
    if STATE.source == "radio":
        return
    if not STATE.queue or STATE.track_id not in STATE.queue:
        STATE.position = 0
        if mpd_play:
            mpd_cmd("seek 0")
        return
    idx = STATE.queue.index(STATE.track_id)
    await cmd_play_track(STATE.queue[max(0, idx - 1)], queue=STATE.queue, mpd_play=mpd_play)


def mpd_enabled_for_cmd(cmd: dict[str, Any]) -> bool:
    return str(cmd.get("output") or "server").lower() != "mobile"


def _format_codec_label(codec: str, sample_rate: str, bit_rate: str) -> str:
    name = (codec or "").strip().lower()
    pretty = {
        "aac": "AAC",
        "mp3": "MP3",
        "mp2": "MP2",
        "opus": "Opus",
        "vorbis": "Vorbis",
        "flac": "FLAC",
        "alac": "ALAC",
        "ac3": "AC3",
        "pcm_s16le": "PCM",
    }.get(name, name.upper() if name else "")
    parts = [p for p in [pretty] if p]
    if sample_rate and sample_rate.isdigit():
        parts.append(f"{int(sample_rate) // 1000}kHz")
    if bit_rate and bit_rate.isdigit():
        kbps = int(bit_rate) // 1000
        if kbps > 0:
            parts.append(f"{kbps}k")
    return " ".join(parts)


async def probe_and_update_radio_quality(url: str, station_id: str) -> None:
    """라디오 스트림 실제 코덱/샘플레이트를 ffprobe 로 분석해 STATE.quality 갱신.
    재생 시작을 막지 않도록 백그라운드 태스크로 호출한다(HLS 분석에 수 초 소요)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_name,sample_rate,bit_rate",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        parts = out.decode(errors="ignore").split()
        codec = parts[0] if len(parts) > 0 else ""
        sample_rate = parts[1] if len(parts) > 1 else ""
        bit_rate = parts[2] if len(parts) > 2 else ""
        label = _format_codec_label(codec, sample_rate, bit_rate)
        if label and STATE.source == "radio" and STATE.radio_station_id == station_id:
            STATE.quality = label
            await broadcast_state()
    except Exception as exc:
        print(f"[radio] quality probe failed: {exc}")


async def silence_server_playback() -> None:
    """미니PC DSP 경로(MPD · librespot · 외부 DSD)만 끔 — 모바일 출력 시 서버 스피커 무음."""
    if STATE.source == "spotify":
        from api import streaming_playback

        await streaming_playback.spotify_player_action("pause")
    stop_server_audio_output()
    STATE.mpd_active = False
    STATE.server_audio_active = False


def cycle_repeat(current: RepeatMode) -> RepeatMode:
    order: list[RepeatMode] = ["none", "all", "one"]
    i = order.index(current) if current in order else 0
    return order[(i + 1) % len(order)]


MOBILE_TAKEOVER_ACTIONS = frozenset(
    {"play", "play_streaming", "play_streaming_queue", "play_queue", "play_album", "play_radio"}
)
MOBILE_SILENCE_SERVER_ACTIONS = MOBILE_TAKEOVER_ACTIONS | frozenset({"pause", "stop"})
# 모바일 세션 소유권을 갱신하는 전송 명령
MOBILE_OWNER_ACTIONS = MOBILE_TAKEOVER_ACTIONS | frozenset(
    {"next", "prev", "pause", "toggle", "seek", "play"}
)
# 서버(스피커) 출력이 존을 가져가면 모바일 소유권 해제
SERVER_CLEARS_MOBILE_OWNER = MOBILE_TAKEOVER_ACTIONS | frozenset({"next", "prev", "play", "toggle"})


def _client_id_from_cmd(cmd: dict[str, Any]) -> str | None:
    raw = str(cmd.get("client_id") or "").strip()
    if not raw:
        return None
    return raw[:80]


def _apply_mobile_owner(cmd: dict[str, Any], *, mpd_play: bool, action: str | None) -> None:
    """레거시 no-op. 모바일은 MOBILE_SESSIONS로 기기별 독립 — 전역 owner 독점 금지."""
    # 과거 단일 owner 필드는 브로드캐스트에 남아 타 기기를 죽일 수 있어 항상 비운다.
    if STATE.mobile_owner_client_id is not None:
        STATE.mobile_owner_client_id = None
    return


def _copy_mobile_context(state: PlayerState, context: Any) -> None:
    if not isinstance(context, dict):
        return
    state.play_context = {
        key: str(context.get(key) or "")[:limit]
        for key, limit in (
            ("weather", 32),
            ("period", 32),
            ("mood", 64),
            ("location_label", 128),
        )
        if str(context.get(key) or "").strip()
    }


async def _mobile_play_track(
    state: PlayerState,
    track_id: int,
    *,
    queue: list[int] | None = None,
    context: Any = None,
) -> bool:
    if not db_pool:
        return False
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM tracks WHERE track_id = $1", track_id)
    if not row:
        return False
    if queue is not None:
        state.queue = queue
    elif not state.queue or track_id not in state.queue:
        state.queue = await build_album_queue(track_id)
    state.source = "library"
    state.track_id = track_id
    state.radio_station_id = None
    state.streaming_provider = None
    state.stream_id = None
    state.stream_queue = []
    state.title = row["title"] or ""
    state.artist = row["artist"] or ""
    state.album = row["album"] or ""
    state.genre = (row.get("genre") or "") if "genre" in row.keys() else ""
    composer = (row.get("composer") or "").strip() if "composer" in row.keys() else ""
    if not composer and state.genre and (
        "classical" in state.genre.lower() or "클래식" in state.genre
    ):
        composer = state.artist
    state.composer = composer
    file_path = str(row.get("file_path") or "")
    state.filename = Path(file_path).name if file_path else ""
    state.format = str(row.get("format") or "")
    state.play_count = int(row.get("play_count") or 0) + 1
    state.duration = int(row["duration_sec"] or 0)
    state.position = 0
    state.quality = track_quality(row)
    state.playback = {
        "mode": "mobile",
        "source_format": state.format.lower(),
        "file_path": file_path,
        "dsp_active": False,
    }
    state.mpd_active = False
    state.server_audio_active = False
    state.playing = True
    _copy_mobile_context(state, context)
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE tracks SET play_count = play_count + 1, last_played = now() WHERE track_id = $1",
            track_id,
        )
        try:
            await conn.execute(
                """INSERT INTO play_history
                     (track_id, weather, period, mood, location_label)
                   VALUES ($1, $2, $3, $4, $5)""",
                track_id,
                state.play_context.get("weather"),
                state.play_context.get("period"),
                state.play_context.get("mood"),
                state.play_context.get("location_label"),
            )
        except Exception as exc:
            print(f"[mobile play_history] insert skipped: {exc}")
    return True


def _mobile_play_stream(
    state: PlayerState,
    provider: str,
    stream_id: str,
    *,
    meta: dict[str, Any] | None = None,
    queue: list[dict[str, Any]] | None = None,
) -> None:
    info = meta or {}
    state.source = provider  # type: ignore[assignment]
    state.streaming_provider = provider  # type: ignore[assignment]
    state.stream_id = stream_id
    state.stream_queue = list(queue or state.stream_queue or [info])
    state.track_id = None
    state.radio_station_id = None
    state.title = str(info.get("title") or "")
    state.artist = str(info.get("artist") or "")
    state.album = str(info.get("album") or "")
    state.genre = ""
    state.composer = ""
    state.filename = ""
    state.format = ""
    state.duration = int(info.get("duration_sec") or 0)
    state.position = 0
    state.quality = str(info.get("quality") or "")
    state.playing = True
    state.mpd_active = False
    state.server_audio_active = False


async def _mobile_next(state: PlayerState, direction: int) -> None:
    if state.source in ("spotify", "tidal"):
        queue = state.stream_queue
        ids = [str(item.get("stream_id") or "") for item in queue]
        if not queue or not state.stream_id:
            return
        index = ids.index(state.stream_id) if state.stream_id in ids else 0
        target = index + direction
        if target < 0:
            target = 0
        elif target >= len(queue):
            if state.repeat == "all":
                target = 0
            else:
                state.playing = False
                return
        item = queue[target]
        provider = str(item.get("source") or item.get("provider") or state.source)
        stream_id = str(item.get("stream_id") or "")
        if provider in ("spotify", "tidal") and stream_id:
            _mobile_play_stream(state, provider, stream_id, meta=item, queue=queue)
        return
    if state.source != "library" or not state.queue:
        return
    if state.track_id not in state.queue:
        target_id = state.queue[0]
    else:
        index = state.queue.index(state.track_id)
        if state.shuffle and direction > 0 and len(state.queue) > 1:
            candidates = [t for t in state.queue if t != state.track_id]
            if candidates:
                target_id = random.choice(candidates)
                await _mobile_play_track(state, target_id, queue=state.queue)
                return
        target = index + direction
        if direction > 0 and state.repeat == "one":
            target = index
        if target < 0:
            target = 0
        elif target >= len(state.queue):
            if state.repeat == "all":
                target = 0
            else:
                state.playing = False
                return
        target_id = state.queue[target]
    await _mobile_play_track(state, target_id, queue=state.queue)


async def handle_mobile_command(client_id: str, cmd: dict[str, Any]) -> dict[str, Any]:
    """모바일 존 명령. 전역 STATE·MPD·다른 모바일 존을 절대 변경하지 않는다."""
    state = _mobile_session(client_id)
    action = str(cmd.get("cmd") or "")

    if action == "play":
        track_id = cmd.get("track_id")
        if track_id:
            await _mobile_play_track(state, int(track_id), context=cmd.get("context"))
        else:
            state.playing = bool(state.track_id or state.radio_station_id or state.stream_id)
    elif action == "get_state":
        return _mobile_payload(client_id, state)
    elif action == "play_queue":
        ids = [int(value) for value in (cmd.get("track_ids") or []) if int(value) > 0]
        if ids:
            index = max(0, min(int(cmd.get("index", 0)), len(ids) - 1))
            await _mobile_play_track(
                state, ids[index], queue=ids, context=cmd.get("context")
            )
    elif action == "play_album":
        album = str(cmd.get("album") or "")
        artist = str(cmd.get("artist") or "")
        if album and db_pool:
            async with db_pool.acquire() as conn:
                if artist:
                    rows = await conn.fetch(
                        "SELECT track_id FROM tracks WHERE album = $1 AND artist = $2 ORDER BY title",
                        album,
                        artist,
                    )
                else:
                    rows = await conn.fetch(
                        "SELECT track_id FROM tracks WHERE album = $1 ORDER BY title",
                        album,
                    )
            ids = [int(row["track_id"]) for row in rows]
            if ids:
                await _mobile_play_track(
                    state, ids[0], queue=ids, context=cmd.get("context")
                )
    elif action in ("play_streaming", "play_streaming_queue"):
        if action == "play_streaming_queue":
            items = cmd.get("items") or []
            if not isinstance(items, list) or not items:
                return _mobile_payload(client_id, state)
            index = max(0, min(int(cmd.get("index", 0)), len(items) - 1))
            item = items[index]
            queue = items
        else:
            item = cmd.get("meta") if isinstance(cmd.get("meta"), dict) else {}
            queue = cmd.get("queue") if isinstance(cmd.get("queue"), list) else None
        provider = str(
            item.get("source") or item.get("provider") or cmd.get("provider") or ""
        ).lower()
        stream_id = str(item.get("stream_id") or cmd.get("stream_id") or "")
        if provider in ("spotify", "tidal") and stream_id:
            _mobile_play_stream(state, provider, stream_id, meta=item, queue=queue)
    elif action == "play_radio":
        station_id = str(cmd.get("station_id") or "").strip()
        station = radio_station_by_id(station_id)
        if station:
            state.source = "radio"
            state.radio_station_id = station_id
            state.track_id = None
            state.streaming_provider = None
            state.stream_id = None
            state.stream_queue = []
            state.title = station["name"]
            state.artist = station.get("org") or station.get("desc") or ""
            state.album = "LIVE"
            state.genre = ""
            state.composer = ""
            state.filename = ""
            state.format = ""
            state.duration = 0
            state.position = 0
            state.quality = "RADIO"
            state.playing = True
            state.mpd_active = False
            state.server_audio_active = False
    elif action in ("stop", "stop_radio"):
        state.playing = False
        if action == "stop_radio":
            state.source = "idle"
            state.radio_station_id = None
    elif action == "pause":
        state.playing = False
    elif action == "toggle":
        state.playing = not state.playing
    elif action == "next":
        await _mobile_next(state, 1)
    elif action == "prev":
        await _mobile_next(state, -1)
    elif action == "seek":
        state.position = max(0, min(int(cmd.get("position", 0)), state.duration or 0))
    elif action == "volume":
        state.volume = max(0, min(100, int(cmd.get("value", 70))))
    elif action == "shuffle":
        value = cmd.get("value")
        state.shuffle = bool(value) if value is not None else not state.shuffle
    elif action == "repeat":
        value = cmd.get("value")
        if value == "toggle" or value is None:
            state.repeat = cycle_repeat(state.repeat)
        elif value in ("none", "one", "all"):
            state.repeat = value  # type: ignore[assignment]
    elif action == "set_queue":
        state.queue = list(
            dict.fromkeys(
                int(value)
                for value in (cmd.get("track_ids") or [])
                if int(value) > 0
            )
        )
    elif action == "add_to_queue":
        track_id = int(cmd.get("track_id") or 0)
        if track_id > 0 and track_id not in state.queue:
            state.queue.append(track_id)

    return _mobile_payload(client_id, state)


async def handle_command(cmd: dict[str, Any]) -> None:
    action = cmd.get("cmd")
    mpd_play = mpd_enabled_for_cmd(cmd)
    print(f"[DIAG] handle_command action={action} mpd_play={mpd_play} track_id={cmd.get('track_id')} station_id={cmd.get('station_id')} output={cmd.get('output')} client_id={cmd.get('client_id')} prev_src={STATE.source} prev_tid={STATE.track_id} prev_title={STATE.title}")
    _apply_mobile_owner(cmd, mpd_play=mpd_play, action=str(action) if action else None)
    # mobile 출력: 재생 상태만 서버가 관리하고 MPD/CamillaDSP는 사용하지 않는다.
    if not mpd_play:
        if action in MOBILE_SILENCE_SERVER_ACTIONS and (
            STATE.server_audio_active or STATE.mpd_active
        ):
            await silence_server_playback()
        STATE.mpd_active = False

    if action == "play":
        tid = cmd.get("track_id")
        if tid:
            print(f"[DIAG] cmd_play_track START tid={tid} mpd_play={mpd_play}")
            await cmd_play_track(
                int(tid),
                mpd_play=mpd_play,
                context=cmd.get("context") if isinstance(cmd.get("context"), dict) else None,
            )
            print(f"[DIAG] cmd_play_track DONE STATE.track_id={STATE.track_id} STATE.title={STATE.title} STATE.playing={STATE.playing} STATE.source={STATE.source}")
        else:
            STATE.playing = True
            if mpd_play:
                if STATE.source == "spotify":
                    from api import streaming_playback

                    await streaming_playback.spotify_player_action("play")
                elif STATE.source == "library" and STATE.track_id and db_pool:
                    async with db_pool.acquire() as conn:
                        row = await conn.fetchrow(
                            "SELECT file_path FROM tracks WHERE track_id = $1",
                            STATE.track_id,
                        )
                    if row:
                        mpd_play_file(row["file_path"])
                    else:
                        mpd_cmd("play")
                elif STATE.source == "radio" and STATE.radio_station_id:
                    station = radio_station_by_id(STATE.radio_station_id)
                    if station:
                        try:
                            stream_url = await resolve_radio_stream_url(station)
                            mpd_play_url(stream_url)
                        except Exception:
                            mpd_cmd("play")
                    else:
                        mpd_cmd("play")
                else:
                    mpd_cmd("play")
                STATE.mpd_active = True
                STATE.server_audio_active = True

    elif action == "play_streaming":
        provider = str(cmd.get("provider") or "").lower()
        stream_id = str(cmd.get("stream_id") or "")
        if provider not in ("spotify", "tidal") or not stream_id:
            return
        queue = cmd.get("queue")
        meta = cmd.get("meta") or {}
        qlist = queue if isinstance(queue, list) else None
        await cmd_play_streaming(
            provider,  # type: ignore[arg-type]
            stream_id,
            meta=meta if isinstance(meta, dict) else {},
            queue=qlist,
            mpd_play=mpd_play,
        )

    elif action == "play_streaming_queue":
        items = cmd.get("items") or []
        if not isinstance(items, list) or not items:
            return
        idx = max(0, min(int(cmd.get("index", 0)), len(items) - 1))
        item = items[idx]
        provider = str(item.get("source") or item.get("provider") or "").lower()
        stream_id = str(item.get("stream_id") or "")
        if provider not in ("spotify", "tidal") or not stream_id:
            return
        await cmd_play_streaming(
            provider,  # type: ignore[arg-type]
            stream_id,
            meta=item,
            queue=items,
            mpd_play=mpd_play,
        )

    elif action == "play_queue":
        ids = [int(x) for x in (cmd.get("track_ids") or [])]
        if not ids:
            return
        idx = max(0, min(int(cmd.get("index", 0)), len(ids) - 1))
        await cmd_play_track(
            ids[idx],
            queue=ids,
            mpd_play=mpd_play,
            context=cmd.get("context") if isinstance(cmd.get("context"), dict) else None,
        )

    elif action == "play_album":
        album = cmd.get("album")
        artist = cmd.get("artist")
        if not album or not db_pool:
            return
        async with db_pool.acquire() as conn:
            if artist:
                rows = await conn.fetch(
                    """SELECT track_id FROM tracks
                       WHERE album = $1 AND artist = $2 ORDER BY title""",
                    album,
                    artist,
                )
            else:
                rows = await conn.fetch(
                    "SELECT track_id FROM tracks WHERE album = $1 ORDER BY title",
                    album,
                )
        ids = [r["track_id"] for r in rows]
        if ids:
            await cmd_play_track(
                ids[0],
                queue=ids,
                mpd_play=mpd_play,
                context=cmd.get("context") if isinstance(cmd.get("context"), dict) else None,
            )

    elif action == "stop":
        STATE.playing = False
        STATE.mpd_active = False
        STATE.server_audio_active = False
        src = STATE.source
        if mpd_play:
            if calibration_playback_active():
                print("[spatial] stop ignored during calibration sweep/tone")
            elif src == "spotify":
                from api import streaming_playback

                await streaming_playback.spotify_player_action("pause")
            elif src in ("library", "radio", "tidal"):
                stop_server_audio_output()
        if src == "radio":
            STATE.source = "idle"
            STATE.radio_station_id = None
            STATE.title = ""
            STATE.artist = ""
            STATE.album = ""
            STATE.quality = ""
        elif src in ("spotify", "tidal"):
            STATE.source = "idle"
            STATE.streaming_provider = None
            STATE.stream_id = None
            STATE.stream_queue = []

    elif action == "pause":
        STATE.playing = False
        if mpd_play:
            if calibration_playback_active():
                print("[spatial] pause ignored during calibration sweep/tone")
            elif STATE.source == "spotify":
                from api import streaming_playback

                await streaming_playback.spotify_player_action("pause")
            elif STATE.source in ("library", "tidal", "radio"):
                from api.dsd_playback import stop_external_dsd_player

                stop_external_dsd_player()
                if STATE.mpd_active:
                    mpd_cmd("pause")

    elif action == "toggle":
        STATE.playing = not STATE.playing
        if mpd_play:
            if STATE.source == "spotify":
                from api import streaming_playback

                await streaming_playback.spotify_player_action("play" if STATE.playing else "pause")
            else:
                if STATE.playing:
                    # 공간음향 스윕/톤이 큐에 남으면 mpc play 가 부밍음을 재개함 → 라이브러리 곡 재로드
                    if mpd_is_calibration_current() and STATE.source == "library" and STATE.track_id and db_pool:
                        async with db_pool.acquire() as conn:
                            row = await conn.fetchrow(
                                "SELECT file_path FROM tracks WHERE track_id = $1",
                                STATE.track_id,
                            )
                        if row:
                            mpd_play_file(row["file_path"])
                        else:
                            mpd_clear_queue()
                            mpd_cmd("play")
                    else:
                        if mpd_is_calibration_current():
                            mpd_clear_queue()
                        mpd_cmd("play")
                    STATE.mpd_active = True
                    STATE.server_audio_active = True
                else:
                    from api.dsd_playback import stop_external_dsd_player

                    stop_external_dsd_player()
                    if STATE.mpd_active:
                        mpd_cmd("pause")

    elif action == "next":
        if STATE.source in ("spotify", "tidal") and STATE.stream_queue:
            await cmd_next_streaming(mpd_play=mpd_play)
            await broadcast_state()
            return
        if STATE.source == "spotify" and mpd_play:
            from api import streaming_playback

            await streaming_playback.spotify_player_action("next")
            await broadcast_state()
            return
        await cmd_next(mpd_play=mpd_play)

    elif action == "prev":
        if STATE.source in ("spotify", "tidal") and STATE.stream_queue:
            await cmd_prev_streaming(mpd_play=mpd_play)
            await broadcast_state()
            return
        if STATE.source == "spotify" and mpd_play:
            from api import streaming_playback

            await streaming_playback.spotify_player_action("prev")
            await broadcast_state()
            return
        await cmd_prev(mpd_play=mpd_play)

    elif action == "seek":
        pos = max(0, min(int(cmd.get("position", 0)), STATE.duration or 0))
        STATE.position = pos
        if mpd_play and STATE.source in ("library", "tidal"):
            mpd_cmd(f"seek {pos}")

    elif action == "volume":
        vol = max(0, min(100, int(cmd.get("value", 70))))
        STATE.volume = vol
        # 모바일 출력 볼륨은 PWA Audio()가 담당 — DSP/MPD 볼륨은 건드리지 않음
        # mpc CLI 는 절대값 설정에 `volume <n>` 을 사용한다(`setvol` 은 프로토콜 전용).
        if mpd_play:
            mpd_set_volume(vol)

    elif action == "shuffle":
        val = cmd.get("value")
        STATE.shuffle = bool(val) if val is not None else not STATE.shuffle
        mpd_cmd(f"random {'1' if STATE.shuffle else '0'}")

    elif action == "repeat":
        val = cmd.get("value")
        if val == "toggle" or val is None:
            STATE.repeat = cycle_repeat(STATE.repeat)
        elif val in ("none", "one", "all"):
            STATE.repeat = val  # type: ignore[assignment]
        mpd_sync_repeat_from_state()

    elif action == "add_to_queue":
        tid = int(cmd.get("track_id", 0))
        if tid and tid not in STATE.queue:
            STATE.queue.append(tid)

    elif action == "set_queue":
        raw_ids = cmd.get("track_ids") or []
        if not isinstance(raw_ids, list):
            return
        # 라이브러리 체크 상태가 재생목록의 SSOT다. 순서는 유지하고 중복·잘못된 ID는 제거한다.
        ids: list[int] = []
        for raw_id in raw_ids:
            try:
                tid = int(raw_id)
            except (TypeError, ValueError):
                continue
            if tid > 0 and tid not in ids:
                ids.append(tid)
        STATE.queue = ids

    elif action == "play_radio":
        sid = str(cmd.get("station_id") or "").strip()
        station = radio_station_by_id(sid)
        if not station:
            return
        try:
            stream_url = await resolve_radio_stream_url(station)
        except Exception as exc:
            print(f"[radio] resolve failed: {exc}")
            return
        STATE.source = "radio"
        STATE.radio_station_id = sid
        STATE.track_id = None
        STATE.streaming_provider = None
        STATE.stream_id = None
        STATE.stream_queue = []
        STATE.title = station["name"]
        STATE.artist = station.get("org") or station.get("desc") or ""
        STATE.album = "LIVE"
        clear_library_meta_fields()
        if mpd_play:
            mpd_set_volume(STATE.volume)
        STATE.duration = 0
        STATE.position = 0
        STATE.quality = "RADIO"
        STATE.mpd_active = mpd_play
        STATE.server_audio_active = mpd_play
        if mpd_play:
            STATE._transition = True
            try:
                mpd_play_url(stream_url)
                STATE.playing = True
            finally:
                STATE._transition = False
        else:
            STATE.playing = True
        # 실제 음원 코덱/샘플레이트 분석 → quality 갱신 (모바일 출력에도 표시되도록 항상 실행)
        asyncio.create_task(probe_and_update_radio_quality(stream_url, sid))

    elif action == "stop_radio":
        STATE.source = "idle"
        STATE.radio_station_id = None
        STATE.playing = False
        STATE.mpd_active = False
        STATE.server_audio_active = False
        if mpd_play:
            mpd_cmd("stop")

    elif action and str(action).startswith("spatial_"):
        from api import spatial_session

        await spatial_session.handle_command(cmd)
        return

    await broadcast_state()


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    from api import spatial_session

    if auth_enabled():
        expected = load_device_token()
        if token_from_ws(ws) != expected:
            await ws.close(code=4401, reason="device_token required")
            return

    ws_client_id = str(ws.query_params.get("client_id") or "").strip()[:80]
    await manager.connect(ws)
    print(f"[DIAG] WS connect total_connections={len(manager.connections)}")
    await refresh_library_total()
    await ws.send_text(json.dumps(STATE.to_payload(), ensure_ascii=False))
    if ws_client_id:
        await ws.send_text(
            json.dumps(_mobile_payload(ws_client_id), ensure_ascii=False)
        )
    await ws.send_text(json.dumps(spatial_session.STATE.to_payload(), ensure_ascii=False))
    try:
        while True:
            raw = await ws.receive_text()
            try:
                data = json.loads(raw)
                command_client_id = ws_client_id or _client_id_from_cmd(data)
                if (
                    str(data.get("output") or "server").lower() == "mobile"
                    and command_client_id
                ):
                    payload = await handle_mobile_command(command_client_id, data)
                    await ws.send_text(json.dumps(payload, ensure_ascii=False))
                else:
                    await handle_command(data)
            except WebSocketDisconnect:
                raise
            except Exception as exc:
                # 단건 명령 실패로 WS 전체를 끊지 않는다 (정지/재생 먹통 방지).
                print(f"[DIAG] handle_command error: {exc}")
                try:
                    await ws.send_text(
                        json.dumps(
                            {"event": "error", "message": str(exc)[:200]},
                            ensure_ascii=False,
                        )
                    )
                except Exception:
                    pass
    except WebSocketDisconnect:
        manager.disconnect(ws)
        print(f"[DIAG] WS disconnect total_connections={len(manager.connections)}")


@app.get("/api/state")
async def get_state():
    await sync_state_from_mpd()
    return asdict(STATE)


@app.get("/api/playback/now")
async def playback_now():
    """모바일 출력용 — 현재 재생 메타 + 스트림 URL (library · radio 공통)."""
    if STATE.source == "library" and STATE.track_id:
        return {
            "source": "library",
            "playing": STATE.playing,
            "track_id": STATE.track_id,
            "title": STATE.title,
            "artist": STATE.artist,
            "album": STATE.album,
            "duration": STATE.duration,
            "stream_url": f"/api/tracks/{STATE.track_id}/stream",
        }
    if STATE.source == "radio" and STATE.radio_station_id:
        station = radio_station_by_id(STATE.radio_station_id)
        if not station:
            raise HTTPException(status_code=404, detail="방송국 없음")
        try:
            stream_url = await resolve_radio_stream_url(station)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {
            "source": "radio",
            "playing": STATE.playing,
            "station_id": STATE.radio_station_id,
            "name": station["name"],
            "org": station.get("org"),
            "stream_url": stream_url,
        }
    if STATE.source in ("spotify", "tidal") and STATE.stream_id:
        return {
            "source": STATE.source,
            "playing": STATE.playing,
            "stream_id": STATE.stream_id,
            "title": STATE.title,
            "artist": STATE.artist,
            "album": STATE.album,
            "duration": STATE.duration,
            "quality": STATE.quality,
        }
    return {"source": "idle", "playing": False}


@app.get("/health")
async def health():
    """설치 터널 sibling(wget --timeout≈8)과 관제 폴링용 — 이벤트루프를 막지 말 것.

    mpc/ALSA probe 는 동기·수 초이므로 to_thread 로 돌린다.
    """

    def _probe_mpd() -> bool:
        try:
            out = subprocess.run(
                ["mpc", "status"],
                timeout=2,
                capture_output=True,
                text=True,
                check=False,
            )
            return out.returncode == 0 and bool(out.stdout.strip())
        except Exception:
            return False

    def _probe_dac() -> dict:
        # DAC 상태 — 실제 ALSA 장치 우선, capability JSON은 부가 정보
        try:
            from api.dac_capability import load_dac_capability
            from api.alsa_device import resolve_direct_alsa_device, card_name_from_device

            cap = load_dac_capability()
            alsa_dev = resolve_direct_alsa_device()
            card = card_name_from_device(alsa_dev)
            live_connected = bool(alsa_dev) and alsa_dev != "default" and "CARD=" in str(alsa_dev)
            return {
                "connected": live_connected,
                "alsa_device": alsa_dev,
                "card_name": card or None,
                "product_label": cap.get("product_label") or cap.get("label") or None,
                "usb_vendor": cap.get("usb_vendor") or None,
                "usb_product": cap.get("usb_product") or None,
                "pcm_max_sample_rate": cap.get("pcm_max_sample_rate"),
                "pcm_max_bit_depth": cap.get("pcm_max_bit_depth"),
                "source": cap.get("source") or "unknown",
                "notes": cap.get("notes") or None,
            }
        except Exception as exc:
            return {"connected": False, "error": str(exc)}

    mpd_ok, dac_info = await asyncio.gather(
        asyncio.to_thread(_probe_mpd),
        asyncio.to_thread(_probe_dac),
    )

    return {
        "status": "ok",
        "mpd": mpd_ok,
        "connections": len(manager.connections),
        "dac": dac_info,
    }


@app.get("/api/system/status")
async def system_status():
    """리모컨·관제 — CPU/RAM/SSD/온도 (Wi-Fi 직접 연결용)"""
    from api.host_metrics import system_status_payload

    uptime_sec = None
    try:
        with open("/proc/uptime", encoding="utf-8") as f:
            uptime_sec = int(float(f.read().split()[0]))
    except OSError:
        uptime_sec = None
    return system_status_payload(uptime_sec=uptime_sec)


@app.get("/api/tracks")
async def get_tracks(
    page: int = 1,
    per_page: int = Query(50, le=200),
    sort: str = "title",
):
    allowed = {"title", "artist", "album", "added_at"}
    sort_col = sort if sort in allowed else "title"
    offset = (max(1, page) - 1) * per_page
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            f"""SELECT track_id, title, artist, album, genre, composer,
                       duration_sec, bit_depth, sample_rate, format,
                       file_path, play_count, quality, license
                FROM tracks ORDER BY {sort_col} LIMIT $1 OFFSET $2""",
            per_page,
            offset,
        )
        total = await conn.fetchval("SELECT COUNT(*) FROM tracks")
    return {
        "tracks": [track_list_row(r) for r in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


def allowed_library_media_path(file_path: str) -> Path:
    path = Path(file_path).resolve()
    roots = [
        Path(os.getenv("WHICK_MUSIC_DIR", "/var/lib/whick/library/music")).resolve(),
        Path("/var/lib/whick/library").resolve(),
    ]
    ps = str(path)
    if ps.startswith("/media/") or ps.startswith("/run/media/"):
        if not path.is_file():
            raise HTTPException(status_code=404, detail="파일 없음")
        return path
    if not any(ps.startswith(str(root) + os.sep) or ps == str(root) for root in roots):
        raise HTTPException(status_code=404, detail="파일 없음")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="파일 없음")
    return path


_TRACK_MEDIA = {
    ".flac": "audio/flac",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".opus": "audio/opus",
    ".wav": "audio/wav",
    ".aiff": "audio/aiff",
    ".aif": "audio/aiff",
    ".alac": "audio/alac",
    ".ape": "audio/ape",
    ".wv": "audio/wv",
    ".wma": "audio/wma",
    ".dsf": "audio/dsf",
    ".dff": "audio/dff",
}


@app.get("/api/tracks/{track_id}/stream")
async def stream_track(track_id: int, request: Request):
    if not db_pool:
        raise HTTPException(status_code=503, detail="DB unavailable")
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT file_path FROM tracks WHERE track_id = $1", track_id)
    if not row:
        raise HTTPException(status_code=404, detail="트랙 없음")
    path = allowed_library_media_path(row["file_path"])
    media = _TRACK_MEDIA.get(path.suffix.lower(), "application/octet-stream")
    from api.media_stream import media_file_response

    return media_file_response(request, path, media)


@app.get("/api/guest/stream/{track_id}")
async def guest_stream_track(
    track_id: int, request: Request, gt: str = Query(..., min_length=8)
):
    """게스트 추천곡 — gt 토큰·허용 목록 검증 후 파일 스트리밍 (device_token 불필요)."""
    if not db_pool:
        raise HTTPException(status_code=503, detail="DB unavailable")
    from api.guest_share_store import verify_guest_token
    from api.media_stream import media_file_response

    if not await verify_guest_token(db_pool, gt, track_id):
        raise HTTPException(status_code=403, detail="게스트 토큰이 유효하지 않거나 이 곡에 대한 권한이 없습니다")
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT file_path FROM tracks WHERE track_id = $1", track_id)
    if not row:
        raise HTTPException(status_code=404, detail="트랙 없음")
    path = allowed_library_media_path(row["file_path"])
    media = _TRACK_MEDIA.get(path.suffix.lower(), "application/octet-stream")
    # inline + Range(206) — attachment/전체파일만 주면 모바일 HTML5 오디오가 재생 실패함
    return media_file_response(request, path, media)


@app.post("/api/guest/shares")
async def create_guest_share(body: dict[str, Any] = Body(...)):
    """소유자 — 공유 토큰 등록 (device_token 필요)."""
    if not db_pool:
        raise HTTPException(status_code=503, detail="DB unavailable")
    from api.guest_share_store import create_share
    from datetime import datetime, timezone

    gt = str(body.get("guest_token") or body.get("gt") or "").strip()
    title = str(body.get("title") or "")
    raw_ids = body.get("track_ids") or body.get("trackIds") or []
    try:
        track_ids = [int(x) for x in raw_ids]
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="track_ids 형식 오류")

    expires_at = None
    exp_ms = body.get("expires_at") or body.get("expiresAt")
    if exp_ms is not None:
        try:
            ms = int(exp_ms)
            expires_at = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="expires_at 형식 오류")

    expires_in = body.get("expires_in") or body.get("expiresIn")
    try:
        result = await create_share(
            db_pool,
            guest_token=gt,
            title=title,
            track_ids=track_ids,
            expires_at=expires_at,
            expires_in_sec=int(expires_in) if expires_in is not None else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return result


@app.get("/api/guest/shares/resolve")
async def resolve_guest_share(gt: str = Query(..., min_length=8)):
    """게스트 — 토큰으로 공유 메타·허용 트랙 목록 (device_token 불필요)."""
    if not db_pool:
        raise HTTPException(status_code=503, detail="DB unavailable")
    from api.guest_share_store import resolve_share

    data = await resolve_share(db_pool, gt)
    if not data:
        raise HTTPException(status_code=404, detail="공유 링크가 만료되었거나 존재하지 않습니다")
    return data


@app.delete("/api/guest/shares")
async def revoke_guest_share(gt: str = Query(..., min_length=8)):
    """소유자 — 공유 중단."""
    if not db_pool:
        raise HTTPException(status_code=503, detail="DB unavailable")
    from api.guest_share_store import revoke_share

    if not await revoke_share(db_pool, gt):
        raise HTTPException(status_code=404, detail="공유를 찾을 수 없습니다")
    return {"ok": True}


GUEST_PLAYER_HTML = r"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>Whick · 음악 공유</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#111;color:#eee;font-family:-apple-system,'Noto Sans KR','Malgun Gothic',sans-serif;display:flex;justify-content:center;align-items:center;min-height:100dvh;padding:16px}
#root{max-width:420px;width:100%}
.hd{display:none!important}
.guest-p{text-align:center;padding:40px 0}
.guest-p .icon{font-size:56px;margin-bottom:16px}
.guest-p .msg{font-size:14px;color:#999;line-height:1.6}
.guest-art{font-size:64px;text-align:center;margin-bottom:12px}
.guest-t{font-size:16px;font-weight:600;text-align:center;margin-bottom:4px}
.guest-a{font-size:13px;color:#999;text-align:center;margin-bottom:8px}
.guest-bar{display:flex;align-items:center;gap:12px;margin:12px 0;padding:0 4px}
.guest-bar-time{font-size:11px;color:#777;font-variant-numeric:tabular-nums;min-width:36px}
.guest-bar-tr{flex:1;height:4px;background:#333;border-radius:2px;cursor:pointer;position:relative}
.guest-bar-f{height:100%;background:linear-gradient(90deg,#4af,#66f);border-radius:2px;width:0%;transition:width .2s}
.guest-ctrl{display:flex;justify-content:center;align-items:center;gap:24px;margin:16px 0 24px}
.guest-cb{width:48px;height:48px;border-radius:50%;border:1px solid #444;background:transparent;color:#eee;font-size:18px;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:all .15s}
.guest-cb:active{background:#333}
.guest-cb--main{width:64px;height:64px;font-size:24px;background:linear-gradient(135deg,#4af,#66f);border-color:transparent}
.guest-list-h{font-size:12px;color:#777;padding:8px 0 4px;border-top:1px solid #222;margin-top:8px}
.guest-row{display:flex;align-items:center;gap:10px;padding:8px 4px;border-bottom:1px solid #1a1a1a;font-size:13px;cursor:pointer;transition:background .15s}
.guest-row:active{background:#1a1a1a}
.guest-row.on{color:#4af}
.guest-row-num{min-width:20px;color:#555;font-size:11px}
.guest-row-t{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.guest-row-a{color:#777;font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:120px}
.guest-row-d{color:#555;font-size:11px;min-width:32px;text-align:right}
.guest-foot{text-align:center;font-size:10px;color:#444;padding:16px 0 8px;line-height:1.5}
.guest-load{text-align:center;padding:60px 0;font-size:14px;color:#777}
.guest-load .sp{display:inline-block;width:24px;height:24px;border:2px solid #444;border-top-color:#4af;border-radius:50%;animation:spin .8s linear infinite;margin-bottom:12px}
@keyframes spin{to{transform:rotate(360deg)}}
.vol-wrap{display:flex;align-items:center;gap:8px;justify-content:center;margin-bottom:12px}
.vol-wrap button{background:none;border:none;color:#999;font-size:16px;cursor:pointer;padding:4px}
.vol-tr{width:100px;height:3px;background:#333;border-radius:2px;cursor:pointer;position:relative}
.vol-f{height:100%;background:#666;border-radius:2px;width:70%}
.vol-pct{font-size:11px;color:#777;min-width:28px}
</style>
</head>
<body>
<div id="root">
  <div id="guest-load" class="guest-load"><div class="sp"></div><br>음악 불러오는 중...</div>
  <div id="guest-player" class="hd">
    <div class="guest-art" id="g-art">🎵</div>
    <div class="guest-t" id="g-t">—</div>
    <div class="guest-a" id="g-a">—</div>
    <div class="guest-bar">
      <span class="guest-bar-time" id="g-ct">0:00</span>
      <div class="guest-bar-tr" id="g-bar-tr"><div class="guest-bar-f" id="g-bar-f"></div></div>
      <span class="guest-bar-time" id="g-dt">0:00</span>
    </div>
    <div class="vol-wrap">
      <button id="g-vol-mute" onclick="toggleMute()">🔊</button>
      <div class="vol-tr" id="g-vol-tr"><div class="vol-f" id="g-vol-f"></div></div>
      <span class="vol-pct" id="g-vol-pct">70%</span>
    </div>
    <div class="guest-ctrl">
      <button class="guest-cb" onclick="gPrev()">⏮</button>
      <button class="guest-cb guest-cb--main" id="g-pp" onclick="gToggle()">▶</button>
      <button class="guest-cb" onclick="gNext()">⏭</button>
    </div>
    <div class="guest-list-h" id="g-list-h"></div>
    <div id="g-list"></div>
    <div class="guest-foot">🔗 터널링 · 24시간 임시 링크<br>음원은 고객 뮤직서버에서 직접 전송</div>
  </div>
  <div id="guest-err" class="guest-p hd">
    <div class="icon">🔗</div>
    <div class="msg" id="g-err-msg"></div>
  </div>
</div>
<audio id="g-audio" preload="none" playsinline webkit-playsinline></audio>
<script>
(function(){
  var params = new URLSearchParams(location.search);
  var gt = params.get('gt');
  if(!gt || gt.length<8){
    document.getElementById('guest-load').classList.add('hd');
    document.getElementById('guest-err').classList.remove('hd');
    document.getElementById('g-err-msg').textContent = '유효하지 않은 링크입니다.';
    return;
  }
  var tracks = [], idx = 0, playing = false, timer = null;
  var audio = document.getElementById('g-audio');
  var vol = parseInt(localStorage.getItem('whick_guest_volume')) || 70;
  var muted = localStorage.getItem('whick_guest_muted')==='1';

  function qs(id){return document.getElementById(id);}

  function fmt(s){if(!s||s<=0)return '0:00';var m=Math.floor(s/60);return m+':'+(s%60<10?'0':'')+Math.floor(s%60);}

  function loadList(){
    fetch('/api/guest/shares/resolve?gt='+encodeURIComponent(gt))
      .then(function(r){if(!r.ok)throw new Error(r.status);return r.json()})
      .then(function(d){
        qs('guest-load').classList.add('hd');
        if(!d.tracks||!d.tracks.length){showErr('이 링크에 재생할 곡이 없습니다.');return;}
        tracks = d.tracks;
        var p = qs('guest-player'); p.classList.remove('hd');
        qs('g-list-h').textContent = d.title+' · '+tracks.length+'곡';
        qs('g-list').innerHTML = tracks.map(function(t,i){return '<div class="guest-row" data-i="'+i+'" onclick="gPlay('+i+',true)"><span class="guest-row-num">'+(i+1)+'</span><span class="guest-row-t">'+esc(t.title)+'</span><span class="guest-row-a">'+esc(t.artist)+'</span><span class="guest-row-d">'+fmt(t.duration_sec)+'</span></div>';}).join('');
        gPlay(0, true);
      })['catch'](function(e){
        qs('guest-load').classList.add('hd');
        showErr('음악을 불러올 수 없습니다.<br>링크가 만료되었거나 서버에 문제가 있습니다.');
      });
  }

  function esc(s){return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}

  function showErr(m){qs('guest-err').classList.remove('hd');qs('g-err-msg').innerHTML=m;}

  function gPlay(i, wantPlay){
    if(i<0||i>=tracks.length)return;
    idx=i;var t=tracks[i];
    qs('g-art').textContent='🎵';
    qs('g-t').textContent=t.title;
    qs('g-a').textContent=t.artist+(t.album?' · '+t.album:'');
    qs('g-dt').textContent=fmt(t.duration_sec);
    qs('g-ct').textContent='0:00';
    qs('g-bar-f').style.width='0%';
    document.querySelectorAll('.guest-row').forEach(function(r,ri){r.classList.toggle('on',ri===i);});
    gApplyVol();
    audio.src='/api/guest/stream/'+t.track_id+'?gt='+encodeURIComponent(gt);
    audio.load();
    if(wantPlay || playing) audio.play()['catch'](function(){});
  }
  function gToggle(){
    if(!audio.src){gPlay(idx, true);return;}
    if(audio.paused){audio.play()['catch'](function(){});}
    else audio.pause();
  }
  function gNext(){gPlay((idx+1)%tracks.length, true);}
  function gPrev(){gPlay((idx-1+tracks.length)%tracks.length, true);}

  audio.addEventListener('play',function(){playing=true;qs('g-pp').textContent='⏸';});
  audio.addEventListener('pause',function(){playing=false;qs('g-pp').textContent='▶';});
  audio.addEventListener('ended',gNext);
  audio.addEventListener('timeupdate',function(){
    if(!audio.duration)return;
    qs('g-ct').textContent=fmt(audio.currentTime);
    qs('g-bar-f').style.width=(audio.currentTime/audio.duration*100)+'%';
  });

  qs('g-bar-tr').addEventListener('click',function(e){
    if(!audio.duration)return;
    var r=this.getBoundingClientRect();
    audio.currentTime=Math.max(0,Math.min(1,(e.clientX-r.left)/r.width))*audio.duration;
  });

  function gApplyVol(){
    var v=muted?0:vol;
    audio.volume=v/100;
    qs('g-vol-f').style.width=v+'%';
    qs('g-vol-pct').textContent=v+'%';
    qs('g-vol-mute').textContent=muted?'🔇':'🔊';
  }
  function toggleMute(){muted=!muted;localStorage.setItem('whick_guest_muted',muted?'1':'0');gApplyVol();}
  qs('g-vol-tr').addEventListener('click',function(e){
    var r=this.getBoundingClientRect();
    vol=Math.round(Math.max(0,Math.min(1,(e.clientX-r.left)/r.width))*100);
    muted=false;
    localStorage.setItem('whick_guest_volume',String(vol));
    localStorage.setItem('whick_guest_muted','0');
    gApplyVol();
  });

  // HTML onclick은 전역 함수만 찾으므로 IIFE 내부 컨트롤을 명시적으로 공개한다.
  window.gPlay = gPlay;
  window.gToggle = gToggle;
  window.gNext = gNext;
  window.gPrev = gPrev;
  window.toggleMute = toggleMute;

  gApplyVol();
  loadList();
})();
</script>
</body>
</html>"""


@app.get("/")
async def root(gt: str | None = Query(default=None)):
    """LAN 게스트 리모컨 UI. ?gt= 있으면 지인 공유 미니플레이어."""
    token = (gt or "").strip()
    if len(token) >= 8:
        return HTMLResponse(GUEST_PLAYER_HTML)
    index = REMOTE_UI_ROOT / "index.html"
    if index.is_file():
        return FileResponse(index, media_type="text/html; charset=utf-8")
    return HTMLResponse(
        "<!DOCTYPE html><html lang=ko><body style='background:#111;color:#eee;font-family:sans-serif;"
        "display:flex;justify-content:center;align-items:center;min-height:100dvh'>"
        "<p>리모컨 UI가 이 펌웨어에 포함되지 않았습니다. 업데이트를 적용해 주세요.</p></body></html>",
        status_code=200,
    )


@app.get("/index.html")
async def remote_ui_index():
    index = REMOTE_UI_ROOT / "index.html"
    if not index.is_file():
        raise HTTPException(status_code=404, detail="remote_ui_missing")
    return FileResponse(index, media_type="text/html; charset=utf-8")


@app.get("/api/artists")
async def get_artists():
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT artist,
                      COUNT(*)::int AS track_count,
                      COUNT(DISTINCT album)::int AS album_count
               FROM tracks GROUP BY artist ORDER BY artist"""
        )
    return {"artists": [dict(r) for r in rows]}


@app.get("/api/albums")
async def get_albums():
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT album, artist,
                      COUNT(*)::int AS track_count,
                      MAX(bit_depth) AS max_bit_depth,
                      MAX(sample_rate) AS max_sample_rate,
                      MAX(format) AS format
               FROM tracks GROUP BY album, artist ORDER BY album"""
        )
    return {"albums": [dict(r) for r in rows]}


@app.get("/api/artists/{artist}/tracks")
async def get_artist_tracks(artist: str):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT track_id, title, artist, album, genre, composer,
                      duration_sec, bit_depth, sample_rate, format,
                      file_path, play_count, quality, license
               FROM tracks WHERE artist = $1 ORDER BY album, title""",
            artist,
        )
    return {"tracks": [track_list_row(r) for r in rows]}


@app.get("/api/albums/{album}/tracks")
async def get_album_tracks(album: str):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT track_id, title, artist, album, genre, composer,
                      duration_sec, bit_depth, sample_rate, format,
                      file_path, play_count, quality, license
               FROM tracks WHERE album = $1 ORDER BY title""",
            album,
        )
    return {"tracks": [track_list_row(r) for r in rows]}


def _composer_display_expr() -> str:
    """메타 패널과 동일한 작곡가 표시 규칙 — 빈 composer면 클래식 장르에서 artist 사용."""
    return """COALESCE(
                NULLIF(TRIM(composer), ''),
                CASE
                  WHEN COALESCE(genre, '') ILIKE '%classic%'
                    OR COALESCE(genre, '') ILIKE '%클래식%'
                  THEN NULLIF(TRIM(artist), '')
                  ELSE NULL
                END,
                '미분류'
              )"""


@app.get("/api/composers")
async def get_composers():
    expr = _composer_display_expr()
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            f"""SELECT {expr} AS composer,
                       COUNT(*)::int AS track_count
                FROM tracks
                GROUP BY 1
                ORDER BY 1"""
        )
    return {"composers": [dict(r) for r in rows]}


@app.get("/api/composers/{composer}/tracks")
async def get_composer_tracks(composer: str):
    expr = _composer_display_expr()
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            f"""SELECT track_id, title, artist, album, genre, composer,
                       duration_sec, bit_depth, sample_rate, format,
                       file_path, play_count, quality, license
                FROM tracks
                WHERE {expr} = $1
                ORDER BY album, title""",
            composer,
        )
    return {"tracks": [track_list_row(r) for r in rows]}


@app.get("/api/genres")
async def get_genres():
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT COALESCE(NULLIF(TRIM(genre), ''), '미분류') AS genre,
                      COUNT(*)::int AS track_count
               FROM tracks
               GROUP BY 1
               ORDER BY 1"""
        )
    return {"genres": [dict(r) for r in rows]}


@app.get("/api/genres/{genre}/tracks")
async def get_genre_tracks(genre: str):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT track_id, title, artist, album, genre, composer,
                      duration_sec, bit_depth, sample_rate, format,
                      file_path, play_count, quality, license
               FROM tracks
               WHERE COALESCE(NULLIF(TRIM(genre), ''), '미분류') = $1
               ORDER BY album, title""",
            genre,
        )
    return {"tracks": [track_list_row(r) for r in rows]}


@app.get("/api/search")
async def search(q: str = Query(..., min_length=1)):
    # DB 별칭·오타 확장(AI 없음). 자연어·고도 확장은 /api/ai-search.
    from api.search_expand import expand_query_aliases

    keywords = expand_query_aliases(q) or [q]
    patterns = [f"%{kw}%" for kw in keywords[:12]]
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT track_id, title, artist, album, genre, composer,
                      duration_sec, bit_depth, sample_rate, format,
                      file_path, play_count, quality, license
               FROM tracks
               WHERE title ILIKE ANY($1::text[])
                  OR artist ILIKE ANY($1::text[])
                  OR album ILIKE ANY($1::text[])
                  OR COALESCE(composer,'') ILIKE ANY($1::text[])
                  OR COALESCE(genre,'') ILIKE ANY($1::text[])
                  OR COALESCE(search_keywords,'') ILIKE ANY($1::text[])
               ORDER BY title LIMIT 50""",
            patterns,
        )
        if not rows:
            # pg_trgm 유사도 폴백 (확장 없으면 빈 결과)
            try:
                rows = await conn.fetch(
                    """SELECT track_id, title, artist, album, genre, composer,
                              duration_sec, bit_depth, sample_rate, format,
                              file_path, play_count, quality, license
                       FROM tracks
                       WHERE similarity(lower(title), lower($1)) > 0.25
                          OR similarity(lower(COALESCE(composer,'')), lower($1)) > 0.25
                          OR similarity(lower(COALESCE(search_keywords,'')), lower($1)) > 0.2
                       ORDER BY GREATEST(
                         similarity(lower(title), lower($1)),
                         similarity(lower(COALESCE(composer,'')), lower($1))
                       ) DESC
                       LIMIT 30""",
                    q,
                )
            except Exception:
                rows = []
    return {"results": [track_list_row(r) for r in rows], "query": q, "keywords": keywords}


@app.get("/api/spatial/state")
async def spatial_state():
    from api import spatial_session

    return asdict(spatial_session.STATE)


SPATIAL_MAX_SAMPLES_B64 = int(os.getenv("WHICK_SPATIAL_MAX_SAMPLES_B64", "2800000"))


@app.post("/api/spatial/analyze")
async def spatial_analyze(body: dict[str, Any] = Body(...)):
    from api import room_analyze

    samples_b64 = str(body.get("samples_b64") or "")
    sample_rate = int(body.get("sample_rate") or 48000)
    if not samples_b64:
        raise HTTPException(status_code=400, detail="samples_b64 required")
    if len(samples_b64) > SPATIAL_MAX_SAMPLES_B64:
        raise HTTPException(status_code=413, detail="recording too large")
    samples = room_analyze.decode_samples_b64(samples_b64)
    if len(samples) < 2048:
        raise HTTPException(status_code=400, detail="recording too short")
    if len(samples) > 500_000:
        raise HTTPException(status_code=413, detail="sample count exceeds limit")
    result = room_analyze.analyze_room_recording(
        samples,
        sample_rate,
        str(body.get("level") or "smartphone"),
        device_profile_id=str(body.get("device_profile_id") or "") or None,
        room_mode_only=body.get("room_mode_only", True) is not False,
    )
    return {"ok": True, **result}


@app.post("/api/spatial/average")
async def spatial_average(body: dict[str, Any] = Body(...)):
    from api import room_analyze

    runs = body.get("runs") or []
    if not isinstance(runs, list) or not runs:
        raise HTTPException(status_code=400, detail="runs required")
    point_count = int(body.get("point_count") or len(runs))
    try:
        result = room_analyze.average_room_measurements(runs, point_count=point_count)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, **result}


@app.get("/api/dashboard")
async def get_dashboard():
    from api.ollama_client import ollama_status

    async with db_pool.acquire() as conn:
        total = int(await conn.fetchval("SELECT COUNT(*) FROM tracks") or 0)
        album_count = int(await conn.fetchval("SELECT COUNT(DISTINCT album) FROM tracks") or 0)
        artist_count = int(await conn.fetchval("SELECT COUNT(DISTINCT artist) FROM tracks") or 0)
        recent_rows = await conn.fetch(
            """
            SELECT t.track_id, t.title, t.artist, t.album, t.duration_sec,
                   t.bit_depth, t.sample_rate, t.format, h.played_at
            FROM play_history h
            JOIN tracks t ON t.track_id = h.track_id
            ORDER BY h.played_at DESC
            LIMIT 8
            """
        )
    from api.playlist_store import list_playlists

    playlists = await list_playlists(db_pool)
    ai = await ollama_status()
    state = asdict(STATE)
    return {
        "library": {
            "tracks": total,
            "albums": album_count,
            "artists": artist_count,
        },
        "recent": [dict(r) for r in recent_rows],
        "playlists": playlists,
        "now_playing": {
            "source": state.get("source"),
            "playing": state.get("playing"),
            "title": state.get("title"),
            "artist": state.get("artist"),
            "album": state.get("album"),
            "quality": state.get("quality"),
            "track_id": state.get("track_id"),
        },
        "ai": ai,
        "external_providers_enabled": EXTERNAL_PROVIDERS_ENABLED,
    }


@app.get("/api/playlists")
async def get_playlists():
    from api.playlist_store import list_playlists

    return {"playlists": await list_playlists(db_pool)}


@app.post("/api/playlists")
async def create_playlist(body: dict[str, Any] = Body(...)):
    from api.playlist_store import create_playlist

    pl = await create_playlist(db_pool, str(body.get("name") or ""))
    return {"ok": True, "playlist": pl}


@app.get("/api/playlists/{playlist_id}/tracks")
async def get_playlist_tracks(playlist_id: int):
    from api.playlist_store import get_playlist_tracks

    return {"tracks": await get_playlist_tracks(db_pool, playlist_id)}


@app.post("/api/playlists/{playlist_id}/tracks")
async def add_playlist_track(playlist_id: int, body: dict[str, Any] = Body(...)):
    from api.playlist_store import add_track

    track_id = int(body.get("track_id") or 0)
    if not track_id:
        raise HTTPException(status_code=400, detail="track_id 필요")
    await add_track(db_pool, playlist_id, track_id)
    return {"ok": True, "playlist_id": playlist_id, "track_id": track_id}


@app.delete("/api/playlists/{playlist_id}/tracks/{track_id}")
async def remove_playlist_track(playlist_id: int, track_id: int):
    from api.playlist_store import remove_track

    if not await remove_track(db_pool, playlist_id, track_id):
        raise HTTPException(status_code=404, detail="트랙 없음")
    return {"ok": True, "playlist_id": playlist_id, "track_id": track_id}


@app.delete("/api/playlists/{playlist_id}")
async def delete_playlist(playlist_id: int):
    from api.playlist_store import delete_playlist

    if not await delete_playlist(db_pool, playlist_id):
        raise HTTPException(status_code=404, detail="플레이리스트 없음")
    return {"ok": True, "playlist_id": playlist_id}


@app.get("/api/ai-search")
async def ai_search(
    q: str = Query(..., min_length=1),
    local: bool = Query(True),
    spotify: bool = Query(True),
    tidal: bool = Query(True),
):
    from api.ollama_client import (
        _has_hangul,
        extract_search_keywords,
        match_library_title,
        ollama_status,
    )
    from api.search_expand import (
        expand_query_aliases,
        is_strong_db_hit,
        looks_like_natural_language,
    )

    _GENERIC_SEARCH_KW = {
        "music", "song", "songs", "track", "audio", "classical", "opera",
        "jazz", "pop", "rock", "음악", "클래식", "오페라", "재즈", "팝", "록",
        "orchestra", "오케스트라", "instrumental",
        "overture", "symphony", "concerto", "sonata", "prelude", "cave",
        "서곡", "교향곡", "협주곡", "소나타",
    }
    _WORK_HINTS = ("동굴", "서곡", "교향", "협주", "소나타", "모음곡")

    async def _fetch_local(keyword_list: list[str]) -> list:
        if not local or not keyword_list:
            return []
        patterns = [f"%{kw}%" for kw in keyword_list[:12]]
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT track_id, title, artist, album, genre, composer,
                          duration_sec, bit_depth, sample_rate, format,
                          file_path, play_count, quality, license
                   FROM tracks
                   WHERE title ILIKE ANY($1::text[])
                      OR artist ILIKE ANY($1::text[])
                      OR album ILIKE ANY($1::text[])
                      OR COALESCE(genre,'') ILIKE ANY($1::text[])
                      OR COALESCE(composer,'') ILIKE ANY($1::text[])
                      OR COALESCE(search_keywords,'') ILIKE ANY($1::text[])
                   ORDER BY bit_depth DESC NULLS LAST, sample_rate DESC NULLS LAST
                   LIMIT 30""",
                patterns,
            )
            if rows:
                return rows
            try:
                return await conn.fetch(
                    """SELECT track_id, title, artist, album, genre, composer,
                              duration_sec, bit_depth, sample_rate, format,
                              file_path, play_count, quality, license
                       FROM tracks
                       WHERE similarity(lower(title), lower($1)) > 0.25
                          OR similarity(lower(COALESCE(composer,'')), lower($1)) > 0.25
                          OR similarity(lower(COALESCE(search_keywords,'')), lower($1)) > 0.2
                       ORDER BY GREATEST(
                         similarity(lower(title), lower($1)),
                         similarity(lower(COALESCE(composer,'')), lower($1))
                       ) DESC
                       LIMIT 30""",
                    q,
                )
            except Exception:
                return []

    def _filter_keywords(kws: list[str]) -> list[str]:
        _seen: set[str] = set()
        _uniq: list[str] = []
        for k in kws:
            if k.casefold() in _GENERIC_SEARCH_KW or len(k) < 2:
                continue
            ck = k.casefold()
            if ck in _seen:
                continue
            _seen.add(ck)
            _uniq.append(k)
        return _uniq[:8] or [q.strip()]

    keywords = expand_query_aliases(q) or [q.strip()]
    rows = await _fetch_local(keywords)
    ai: dict[str, Any] = {
        "skipped": True,
        "reason": "db_first",
        "model": "gemma4:e2b",
    }
    extracted: dict[str, Any] = {"keywords": keywords, "genre": "", "mood": "", "era": ""}

    if is_strong_db_hit(len(rows), q, keywords):
        pass  # skip AI — use first DB results
    else:
        ai = {"skipped": False, "reason": "db_miss_or_nl", "model": "gemma4:e2b"}
        catalog_names: list[str] = []
        catalog_titles: list[str] = []
        async with db_pool.acquire() as conn:
            name_rows = await conn.fetch(
                """
                SELECT DISTINCT trim(name) AS name FROM (
                  SELECT composer AS name FROM tracks
                   WHERE COALESCE(trim(composer),'') <> ''
                  UNION ALL
                  SELECT artist FROM tracks
                   WHERE COALESCE(trim(artist),'') <> ''
                ) s
                WHERE length(trim(name)) >= 2
                ORDER BY name
                LIMIT 60
                """
            )
            catalog_names = [r["name"] for r in name_rows]
            for full in list(catalog_names):
                parts = [p for p in full.replace(",", " ").split() if len(p) >= 3]
                if parts:
                    catalog_names.append(parts[-1])
            title_rows = await conn.fetch(
                """
                SELECT DISTINCT trim(title) AS title FROM tracks
                 WHERE COALESCE(trim(title),'') <> ''
                 ORDER BY title
                 LIMIT 80
                """
            )
            catalog_titles = [r["title"] for r in title_rows]

        need_ai = len(rows) == 0 or looks_like_natural_language(q)
        if need_ai:
            extracted, ai_status = await extract_search_keywords(
                q, catalog_names=catalog_names, catalog_titles=catalog_titles
            )
            ai = {**ai_status, "skipped": False, "reason": "extract_keywords"}
            ai_kws = [
                str(k).strip()
                for k in (extracted.get("keywords") or [])
                if str(k).strip()
            ]
            keywords = _filter_keywords(list(keywords) + ai_kws)

        q_stripped = q.strip()
        words = q_stripped.split()
        work_hint = any(h in q_stripped for h in _WORK_HINTS)
        allow_title_match = _has_hangul(q) and (
            looks_like_natural_language(q)
            or work_hint
            or len(words) >= 2
        )
        if allow_title_match and catalog_titles:
            matched, ai_t = await match_library_title(q, catalog_titles)
            if ai_t.get("ok"):
                ai = {**ai, **{k: v for k, v in ai_t.items() if k in ("model", "url", "ok")}}
            if matched:
                add = [matched]
                if '"' in matched:
                    inners = [p.strip() for p in matched.split('"') if len(p.strip()) >= 4]
                    add = inners + [matched]
                keywords = []
                _seen_m: set[str] = set()
                for a in add:
                    if a.casefold() not in _seen_m:
                        _seen_m.add(a.casefold())
                        keywords.append(a)
                extracted = {**extracted, "keywords": keywords, "matched_title": matched}
            else:
                keywords = _filter_keywords(keywords)
        else:
            keywords = _filter_keywords(keywords)

        rows = await _fetch_local(keywords)

    local_results = [{**track_list_row(r), "source": "library"} for r in rows]
    streaming_tracks: list[dict[str, Any]] = []
    streaming_meta: dict[str, Any] = {"spotify": [], "tidal": []}

    if EXTERNAL_PROVIDERS_ENABLED and (spotify or tidal):
        from api import streaming_playback

        providers = []
        if spotify:
            providers.append("spotify")
        if tidal:
            providers.append("tidal")
        fed = await streaming_playback.federated_search(q, providers)
        streaming_meta["spotify"] = fed.get("spotify") or []
        streaming_meta["tidal"] = fed.get("tidal") or []
        streaming_tracks = fed.get("tracks") or []

    merged = local_results + streaming_tracks
    explain = extracted.get("mood") or extracted.get("genre") or q
    parts = [f"로컬 {len(local_results)}"]
    if streaming_meta["spotify"]:
        parts.append(f"Spotify {len(streaming_meta['spotify'])}")
    if streaming_meta["tidal"]:
        parts.append(f"Tidal {len(streaming_meta['tidal'])}")
    return {
        "results": merged,
        "local_results": local_results,
        "streaming": streaming_meta,
        "query": q,
        "extracted": extracted,
        "ai_explain": f"'{explain}' — {' · '.join(parts)}",
        "ai": ai,
    }


@app.post("/api/ai-chat")
async def ai_chat(body: dict[str, Any] = Body(default={})):
    """Whick AI 채팅 — 일반 대화 + 필요 시 라이브러리 검색/추천 도구."""
    return await _ai_chat_impl(body)


@app.get("/api/ai-chat")
async def ai_chat_get(
    q: str = Query(..., min_length=1),
    message: str | None = Query(None),
    user_name: str | None = Query(None),
):
    """토큰 없는 읽기 경로(미들웨어 GET 허용) — 단발 질문용."""
    return await _ai_chat_impl(
        {
            "message": (message or q).strip(),
            "history": [],
            "user_name": (user_name or "").strip(),
        }
    )


async def _ai_chat_impl(body: dict[str, Any]):
    """Whick AI 채팅 — 일반 대화 + 필요 시 라이브러리 검색/추천 도구."""
    from api.ollama_client import (
        _is_bare_recommend_request,
        _has_hangul,
        _looks_like_music_request,
        _polite_music_reply,
        _unclear_music_reply,
        ai_assistant_turn,
        extract_recommend_track_ids,
        extract_search_keywords,
        match_library_title,
        match_catalog_in_message,
    )
    from api.taste_profile import build_taste_profile, fetch_recommend_candidates, profile_summary
    from api.weather_context import get_weather_context

    message = str(body.get("message") or body.get("q") or "").strip()
    chat_lang = str(body.get("lang") or "ko")
    if not message:
        raise HTTPException(status_code=400, detail="message required")
    raw_hist = body.get("history") or []
    history: list[dict[str, Any]] = []
    if isinstance(raw_hist, list):
        for turn in raw_hist[-8:]:
            if not isinstance(turn, dict):
                continue
            role = str(turn.get("role") or "").strip()
            content = str(turn.get("content") or "").strip()
            if role in {"user", "assistant"} and content:
                history.append({"role": role, "content": content[:500]})

    wx = get_weather_context()
    weather_summary = (
        f"{wx.get('locationLabel') or wx.get('city') or ''} · "
        f"{wx.get('period') or ''} · {wx.get('wEmoji') or ''}{wx.get('weather') or ''}"
        + (f" · {wx.get('temp')}℃" if wx.get("temp") is not None else "")
    ).strip(" ·")

    catalog_names: list[str] = []
    catalog_titles: list[str] = []
    library_count = 0
    async with db_pool.acquire() as conn:
        library_count = int(await conn.fetchval("SELECT COUNT(*) FROM tracks") or 0)
        name_rows = await conn.fetch(
            """
            SELECT DISTINCT trim(name) AS name FROM (
              SELECT composer AS name FROM tracks
               WHERE COALESCE(trim(composer),'') <> ''
              UNION ALL
              SELECT artist FROM tracks
               WHERE COALESCE(trim(artist),'') <> ''
            ) s
            WHERE length(trim(name)) >= 2
            ORDER BY name
            LIMIT 60
            """
        )
        catalog_names = [r["name"] for r in name_rows]
        for full in list(catalog_names):
            parts = [p for p in full.replace(",", " ").split() if len(p) >= 3]
            if parts:
                catalog_names.append(parts[-1])
        title_rows = await conn.fetch(
            """
            SELECT DISTINCT trim(title) AS title FROM tracks
             WHERE COALESCE(trim(title),'') <> ''
             ORDER BY title
             LIMIT 80
            """
        )
        catalog_titles = [r["title"] for r in title_rows]

    # 짧은 키워드(예: 동굴) — 별칭 DB 히트면 올라마 intent 호출 없이 즉시 반환
    from api.search_expand import (
        expand_query_aliases,
        is_strong_db_hit,
        looks_like_natural_language,
    )

    if (
        len(message) <= 40
        and not looks_like_natural_language(message)
        and not any(k in message for k in ("날씨", "누구", "이름", "안녕", "고마", "감사", "추천"))
    ):
        expand_kws = expand_query_aliases(message) or [message]
        async with db_pool.acquire() as conn:
            early_rows = await conn.fetch(
                """SELECT track_id, title, artist, album, genre, composer,
                          duration_sec, bit_depth, sample_rate, format,
                          file_path, play_count, quality, license
                   FROM tracks
                   WHERE title ILIKE ANY($1::text[])
                      OR artist ILIKE ANY($1::text[])
                      OR album ILIKE ANY($1::text[])
                      OR COALESCE(genre,'') ILIKE ANY($1::text[])
                      OR COALESCE(composer,'') ILIKE ANY($1::text[])
                      OR COALESCE(search_keywords,'') ILIKE ANY($1::text[])
                   ORDER BY bit_depth DESC NULLS LAST, sample_rate DESC NULLS LAST
                   LIMIT 20""",
                [f"%{kw}%" for kw in expand_kws[:12]],
            )
        if is_strong_db_hit(len(early_rows), message, expand_kws):
            local_results = [{**track_list_row(r), "source": "library"} for r in early_rows]
            reply = _polite_music_reply(len(local_results))
            return {
                "reply": reply,
                "intent": "search",
                "autoplay": False,
                "tracks": local_results,
                "local_results": local_results,
                "results": local_results,
                "query": message,
                "search_query": message,
                "extracted": {"keywords": expand_kws, "mode": "db_first"},
                "tools_used": ["library", "search"],
                "weather": {
                    "summary": weather_summary,
                    "city": wx.get("city"),
                    "weather": wx.get("weather"),
                    "temp": wx.get("temp"),
                    "period": wx.get("period"),
                },
                "ai": {"skipped": True, "reason": "db_first", "model": "gemma4:e2b"},
                "ai_explain": reply,
            }

    decided, ai = await ai_assistant_turn(
        message,
        history=history,
        weather_summary=weather_summary,
        catalog_names=catalog_names,
        library_count=library_count,
        user_name=str(body.get("user_name") or body.get("userName") or "").strip(),
    )
    intent = str(decided.get("intent") or "chat")
    reply = str(decided.get("reply") or "").strip()
    search_query = str(decided.get("search_query") or "").strip()
    want_recommend = bool(decided.get("recommend")) or intent == "recommend"
    want_play = bool(decided.get("play")) or intent == "play"
    tools_used: list[str] = []
    local_results: list[dict[str, Any]] = []
    extracted: dict[str, Any] = {}

    catalog_hit = match_catalog_in_message(message, catalog_names)
    if catalog_hit:
        search_query = search_query or catalog_hit
        if intent in {"recommend", "chat", "clarify"}:
            intent = "play" if want_play else "search"
        want_recommend = False

    # 짧은 한글 작품/이름만 말한 경우 (예: 핑갈, 핑갈의 동굴) — chat으로 빠지지 않게 검색
    if (
        intent == "chat"
        and _has_hangul(message)
        and len(message.strip()) <= 40
        and not any(k in message for k in ("날씨", "누구", "이름", "안녕", "고마", "감사"))
    ):
        intent = "search"
        search_query = search_query or message.strip()
        want_recommend = False

    # 분위기만 있고 검색어로 못 옮긴 경우 — 곡 목록 없이 재질문
    if intent == "clarify":
        return {
            "reply": reply or _unclear_music_reply(),
            "intent": "clarify",
            "autoplay": False,
            "tracks": [],
            "local_results": [],
            "results": [],
            "query": message,
            "search_query": "",
            "extracted": {"keywords": [], "mode": "clarify"},
            "tools_used": [],
            "weather": {
                "summary": weather_summary,
                "city": wx.get("city"),
                "weather": wx.get("weather"),
                "temp": wx.get("temp"),
                "period": wx.get("period"),
            },
            "ai": ai,
            "ai_explain": reply or _unclear_music_reply(),
        }

    music_req = (
        intent in {"search", "recommend", "play"}
        or bool(search_query)
        or _looks_like_music_request(message)
    )
    if music_req:
        tools_used.append("library")
        # 맹목 취향추천 금지: '추천만' 요청일 때만 recommend 경로
        use_recommend = (
            want_recommend
            and not search_query
            and not catalog_hit
            and _is_bare_recommend_request(message)
        )
        if use_recommend:
            async with db_pool.acquire() as conn:
                profile = await build_taste_profile(conn)
                candidates = await fetch_recommend_candidates(conn, profile, limit=50)
            ctx = profile_summary(
                profile,
                live_context={
                    "weather": str(wx.get("weather") or ""),
                    "period": str(wx.get("period") or ""),
                    "location_label": str(wx.get("locationLabel") or ""),
                },
                lang=chat_lang,
            )
            ctx = f"{ctx}\n상황 요청: {message}".strip()
            rec, ai_rec = await extract_recommend_track_ids(
                candidates, limit=8, context=ctx, lang=chat_lang
            )
            if ai_rec.get("ok"):
                ai = {**ai, **{k: v for k, v in ai_rec.items() if k in ("model", "url", "ok")}}
            id_set = {str(t["track_id"]) for t in candidates}
            track_ids = [tid for tid in (rec.get("track_ids") or []) if tid in id_set]
            by_id = {str(t["track_id"]): t for t in candidates}
            # 후보를 무작위로 채우지 않음 — AI가 고른 것만
            local_results = [
                {**track_list_row(by_id[tid]), "source": "library"}
                for tid in track_ids
                if tid in by_id
            ]
            extracted = {"keywords": [], "mode": "recommend", "reasons": rec.get("reasons") or {}}
            tools_used.append("recommend")
            if local_results:
                reply = _polite_music_reply(len(local_results))
            else:
                reply = _unclear_music_reply()
                intent = "clarify"
        else:
            q = search_query or message
            from api.search_expand import (
                expand_query_aliases,
                is_strong_db_hit,
                looks_like_natural_language,
            )

            # 1차: 별칭·오타 확장 DB 검색 — 충분하면 올라마 키워드 추출 생략
            expand_kws = expand_query_aliases(q) or [str(q).strip()]
            async with db_pool.acquire() as conn:
                db_rows = await conn.fetch(
                    """SELECT track_id, title, artist, album, genre, composer,
                              duration_sec, bit_depth, sample_rate, format,
                              file_path, play_count, quality, license
                       FROM tracks
                       WHERE title ILIKE ANY($1::text[])
                          OR artist ILIKE ANY($1::text[])
                          OR album ILIKE ANY($1::text[])
                          OR COALESCE(genre,'') ILIKE ANY($1::text[])
                          OR COALESCE(composer,'') ILIKE ANY($1::text[])
                          OR COALESCE(search_keywords,'') ILIKE ANY($1::text[])
                       ORDER BY bit_depth DESC NULLS LAST, sample_rate DESC NULLS LAST
                       LIMIT 20""",
                    [f"%{kw}%" for kw in expand_kws[:12]],
                )
            if is_strong_db_hit(len(db_rows), q, expand_kws) and not looks_like_natural_language(
                message
            ):
                local_results = [{**track_list_row(r), "source": "library"} for r in db_rows]
                extracted = {"keywords": expand_kws, "mode": "db_first"}
                tools_used.append("search")
                reply = _polite_music_reply(len(local_results))
                ai = {**ai, "skipped": True, "reason": "db_first"}
            else:
                extracted, ai_kw = await extract_search_keywords(
                    q, catalog_names=catalog_names, catalog_titles=catalog_titles
                )
                if ai_kw.get("ok"):
                    ai = {**ai, **{k: v for k, v in ai_kw.items() if k in ("model", "url", "ok")}}
                keywords = [
                    str(k).strip() for k in (extracted.get("keywords") or []) if str(k).strip()
                ]
                # 사용자가 말하지 않은 catalog 작곡가명이 keywords에 섞이면 제거
                msg_cf = message.casefold()
                catalog_cf = {str(n).strip().casefold() for n in catalog_names if str(n).strip()}
                filtered_kw: list[str] = []
                for k in keywords:
                    kl = k.casefold()
                    looks_catalog = any(
                        kl == c or kl in c or c in kl for c in catalog_cf if len(c) >= 4
                    )
                    mentioned = kl in msg_cf or k in message
                    if catalog_hit and (
                        catalog_hit.casefold() in kl or kl in catalog_hit.casefold()
                    ):
                        filtered_kw.append(k)
                    elif looks_catalog and not mentioned:
                        continue
                    else:
                        filtered_kw.append(k)
                keywords = filtered_kw
                if catalog_hit and catalog_hit not in keywords:
                    keywords.insert(0, catalog_hit)
                if q and q not in keywords and (catalog_hit or len(q) <= 40):
                    # 긴 분위기 문장 전체를 ILIKE하지 않음
                    if len(q) <= 40:
                        keywords.insert(0, q)
                # expand 키워드도 합쳐 한글 작품어(동굴 등)가 빠지지 않게
                for ek in expand_kws:
                    if ek not in keywords:
                        keywords.append(ek)
                _GENERIC = {
                    "music", "song", "songs", "track", "audio",
                    "노래", "곡", "하나", "골라", "추천", "재생", "틀어", "음악",
                    "overture", "symphony", "concerto", "sonata", "prelude", "cave",
                    "서곡", "교향곡", "협주곡", "소나타",
                }
                keywords = [
                    k for k in keywords if k.casefold() not in _GENERIC and len(k) >= 2
                ][:8]
                # 한글 작품명 → 라이브러리 제목 매칭 우선 (extract 환각·서곡 나열 무시)
                if _has_hangul(q) and catalog_titles:
                    matched, ai_t = await match_library_title(q, catalog_titles)
                    if ai_t.get("ok"):
                        ai = {**ai, **{k: v for k, v in ai_t.items() if k in ("model", "url", "ok")}}
                    if matched:
                        keywords = [matched]
                        if '"' in matched:
                            inners = [p.strip() for p in matched.split('"') if len(p.strip()) >= 4]
                            keywords = inners + [matched]
                        keywords = keywords[:4]
                        extracted = {**extracted, "keywords": keywords, "matched_title": matched}

                if not keywords:
                    reply = _unclear_music_reply()
                    intent = "clarify"
                    extracted = {"keywords": [], "mode": "clarify"}
                    tools_used.append("clarify")
                else:
                    async with db_pool.acquire() as conn:
                        rows = await conn.fetch(
                            """SELECT track_id, title, artist, album, genre, composer,
                                      duration_sec, bit_depth, sample_rate, format,
                                      file_path, play_count, quality, license
                               FROM tracks
                               WHERE title ILIKE ANY($1::text[])
                                  OR artist ILIKE ANY($1::text[])
                                  OR album ILIKE ANY($1::text[])
                                  OR COALESCE(genre,'') ILIKE ANY($1::text[])
                                  OR COALESCE(composer,'') ILIKE ANY($1::text[])
                                  OR COALESCE(search_keywords,'') ILIKE ANY($1::text[])
                               ORDER BY bit_depth DESC NULLS LAST, sample_rate DESC NULLS LAST
                               LIMIT 20""",
                            [f"%{kw}%" for kw in keywords],
                        )
                    local_results = [{**track_list_row(r), "source": "library"} for r in rows]
                    extracted = {**extracted, "keywords": keywords}
                    tools_used.append("search")
                    if local_results:
                        reply = _polite_music_reply(len(local_results))
                    elif catalog_hit or (search_query and len(search_query) <= 40):
                        reply = _polite_music_reply(0)
                    else:
                        reply = _unclear_music_reply()
                        intent = "clarify"

    if intent == "chat" and not reply:
        reply = "네, 말씀해 주세요. 음악·날씨·일상 대화 모두 도와드리겠습니다."

    return {
        "reply": reply,
        "intent": intent,
        "autoplay": bool(want_play and local_results),
        "tracks": local_results,
        "local_results": local_results,
        "results": local_results,
        "query": message,
        "search_query": search_query,
        "extracted": extracted,
        "tools_used": tools_used,
        "weather": {
            "summary": weather_summary,
            "city": wx.get("city"),
            "weather": wx.get("weather"),
            "temp": wx.get("temp"),
            "period": wx.get("period"),
        },
        "ai": ai,
        "ai_explain": reply,
    }


@app.get("/api/weather/context")
async def weather_context(
    lat: float | None = Query(None),
    lon: float | None = Query(None),
):
    from api.weather_context import get_weather_context

    return get_weather_context(lat=lat, lon=lon)


@app.get("/api/ai-recommend")
async def ai_recommend(
    limit: int = Query(8, ge=1, le=20),
    include_streaming: bool = Query(True),
    spotify: bool = Query(True),
    tidal: bool = Query(True),
    weather: str | None = Query(None),
    period: str | None = Query(None),
    mood: str | None = Query(None),
    location_label: str | None = Query(None),
    lang: str | None = Query(None),
):
    from api.ollama_client import extract_recommend_track_ids, ollama_status
    from api.taste_profile import (
        build_taste_profile,
        fetch_recommend_candidates,
        profile_summary,
        streaming_search_query,
    )

    # ko가 아닌 모든 언어는 영어 표기 (파파 지시 2026-08-17 — i18n 정책과 동일)
    is_en = lang is not None and lang != "ko"

    live_ctx = {
        key: str(val).strip()
        for key, val in (
            ("weather", weather),
            ("period", period),
            ("mood", mood),
            ("location_label", location_label),
        )
        if val and str(val).strip()
    }

    async with db_pool.acquire() as conn:
        profile = await build_taste_profile(conn)
        candidates = await fetch_recommend_candidates(conn, profile, limit=50)

    if not candidates:
        return {
            "tracks": [],
            "track_ids": [],
            "reasons": {},
            "explain": ("Your library is empty." if is_en else "라이브러리에 곡이 없습니다."),
            "taste_profile": profile,
            "streaming_links": [],
            "ai": await ollama_status(),
            "weather_context": live_ctx or None,
        }

    ctx = profile_summary(profile, live_context=live_ctx or None, lang=lang)
    extracted, ai = await extract_recommend_track_ids(candidates, limit=limit, context=ctx, lang=lang)
    id_set = {str(t["track_id"]) for t in candidates}
    track_ids = [tid for tid in (extracted.get("track_ids") or []) if tid in id_set]
    by_id = {str(t["track_id"]): t for t in candidates}
    reasons = extracted.get("reasons") or {}

    if not track_ids:
        unplayed = [t for t in candidates if int(t.get("play_count") or 0) == 0]
        pool = unplayed or candidates
        track_ids = [str(t["track_id"]) for t in pool[:limit]]
        for tid in track_ids:
            t = by_id.get(tid) or {}
            if int(t.get("play_count") or 0) == 0:
                reasons[tid] = ("Unplayed · matches your taste" if is_en else "아직 듣지 않은 곡 · 취향과 유사")
            else:
                reasons[tid] = ("Matches your frequently played style" if is_en else "자주 듣는 스타일과 맞는 곡")

    results = []
    for tid in track_ids:
        t = by_id.get(tid)
        if not t:
            continue
        results.append(
            {
                **t,
                "source": "library",
                "recommend_reason": reasons.get(tid, ""),
                "unplayed": int(t.get("play_count") or 0) == 0,
            }
        )

    streaming_links: list[dict[str, Any]] = []
    if include_streaming and EXTERNAL_PROVIDERS_ENABLED and (spotify or tidal):
        from api import streaming_playback

        q = streaming_search_query(profile)
        providers = []
        if spotify:
            providers.append("spotify")
        if tidal:
            providers.append("tidal")
        fed = await streaming_playback.federated_search(q, providers)
        for tr in (fed.get("tracks") or [])[:6]:
            streaming_links.append(
                {
                    "source": tr.get("source"),
                    "title": tr.get("title"),
                    "artist": tr.get("artist"),
                    "album": tr.get("album"),
                    "stream_id": tr.get("stream_id"),
                    "uri": tr.get("uri"),
                    "quality": tr.get("quality"),
                    "duration_sec": tr.get("duration_sec"),
                }
            )

    explain = extracted.get("explain") or (
        (f"Personal taste ({ctx}) · {len(results)} local tracks" if is_en else f"개인 취향({ctx}) · 로컬 {len(results)}곡")
        + (f" · {len(streaming_links)} streaming tracks" if (streaming_links and is_en) else (f" · 스트리밍 {len(streaming_links)}곡" if streaming_links else ""))
    )

    return {
        "tracks": results,
        "track_ids": track_ids,
        "reasons": reasons,
        "explain": explain,
        "algorithm": "personal_taste",
        "taste_profile": {
            "has_data": profile.get("has_data"),
            "summary": ctx,
            "top_artists": profile.get("top_artists", [])[:5],
            "top_genres": profile.get("top_genres", [])[:4],
            "top_weather": profile.get("top_weather", [])[:3],
            "top_periods": profile.get("top_periods", [])[:3],
        },
        "streaming_links": streaming_links,
        "weather_context": live_ctx or None,
        "ai": ai,
    }


@app.get("/api/favorites")
async def get_favorites():
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT t.track_id, t.title, t.artist, t.album, t.genre, t.composer,
                      t.duration_sec, t.bit_depth, t.sample_rate, t.format,
                      t.file_path, t.play_count, t.quality, t.license
               FROM favorites f JOIN tracks t ON t.track_id = f.track_id
               ORDER BY f.added_at DESC"""
        )
    return {"tracks": [track_list_row(r) for r in rows]}


@app.post("/api/favorites/{track_id}")
async def add_favorite(track_id: int):
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO favorites (track_id) VALUES ($1) ON CONFLICT (track_id) DO NOTHING",
            track_id,
        )
    return {"ok": True, "track_id": track_id}


@app.delete("/api/favorites/{track_id}")
async def remove_favorite(track_id: int):
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM favorites WHERE track_id = $1", track_id)
    return {"ok": True, "track_id": track_id}


@app.get("/api/history")
async def get_history(limit: int = Query(50, le=100)):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT t.track_id, t.title, t.artist, t.album, t.genre, t.composer,
                      t.duration_sec, t.bit_depth, t.sample_rate, t.format,
                      t.file_path, t.play_count, t.quality, t.license,
                      h.played_at
               FROM play_history h
               JOIN tracks t ON t.track_id = h.track_id
               ORDER BY h.played_at DESC
               LIMIT $1""",
            limit,
        )
    out = []
    for r in rows:
        item = track_list_row(r)
        item["played_at"] = r["played_at"].isoformat() if r.get("played_at") else None
        out.append(item)
    return {"tracks": out}


@app.get("/api/library/status")
async def library_status():
    from api.library_scanner import load_audit_settings, scan_paths_from_env

    paths = scan_paths_from_env()
    async with db_pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM tracks") or 0
    return {
        "external_providers_enabled": EXTERNAL_PROVIDERS_ENABLED,
        "device_auth_required": auth_enabled(),
        "radio_enabled": True,
        "room_correction_enabled": True,
        "scan_paths": [str(p) for p in paths],
        "total_tracks": total,
        "library_total": STATE.library_total,
        "audit_settings": load_audit_settings(),
    }


@app.get("/api/library/audit-settings")
async def library_audit_settings_get():
    from api.library_scanner import audit_settings_schema, load_audit_settings

    return {
        "ok": True,
        **audit_settings_schema(),
        **load_audit_settings(),
    }


@app.post("/api/library/audit-settings")
async def library_audit_settings_save(body: dict[str, Any] = Body(...)):
    from api.library_scanner import audit_settings_schema, save_audit_settings

    settings = save_audit_settings(body)
    return {
        "ok": True,
        **audit_settings_schema(),
        **settings,
    }


@app.get("/api/library/loudness-settings")
async def library_loudness_settings_get():
    from api.loudness_normalize import load_settings, status

    return {"ok": True, **(await status(db_pool)), "settings": load_settings()}


@app.post("/api/library/loudness-settings")
async def library_loudness_settings_save(body: dict[str, Any] = Body(...)):
    from api.loudness_normalize import kick, save_settings, status

    settings = save_settings(body)
    kick()
    return {"ok": True, **(await status(db_pool)), "settings": settings}


@app.get("/api/library/loudness-status")
async def library_loudness_status():
    from api.loudness_normalize import status

    return {"ok": True, **(await status(db_pool))}


@app.get("/api/library/scan")
async def library_scan_get():
    """라이브러리 스캔 (GET — 리모컨에서 직접 호출)."""
    return await library_scan()


@app.post("/api/library/scan")
async def library_scan():
    from api.library_scanner import load_audit_settings, scan_library, scan_paths_from_env

    result = await scan_library(db_pool, scan_paths_from_env())
    mpd_cmd("update")
    await refresh_library_total()
    try:
        from api.loudness_normalize import kick

        kick()
    except Exception:
        pass
    tiers = dict(result.classified_tiers or {})
    audited = int(result.audited or 0)
    rejected = int(result.audit_rejected or 0)
    return {
        "ok": True,
        **asdict(result),
        "audit_settings": load_audit_settings(),
        "auditor": {
            "robot": "robot-auditor",
            "audited": audited,
            "passed": int(result.audit_passed or 0),
            "rejected": rejected,
            "reasons": dict(result.audit_reasons or {}),
            "tiers": tiers,
        },
        "classifier": {
            "robot": "robot-classifier",
            "classified": int(result.classified or 0),
            "tiers": tiers,
            "formats": dict(result.classified_formats or {}),
        },
    }


@app.api_route("/api/library/reset", methods=["GET", "POST"])
async def library_reset():
    """라이브러리 초기화 — DB 메타만 삭제. 음원 파일은 유지. 자동 재스캔하지 않음.
    (이전엔 DELETE 직후 scan을 호출해 곡이 바로 다시 등록되던 버그가 있었음)
    favorites·play_history·playlist_tracks FK 때문에 자식 테이블을 먼저 비운다."""
    deleted = 0
    if db_pool:
        async with db_pool.acquire() as conn:
            before = int(await conn.fetchval("SELECT COUNT(*) FROM tracks") or 0)
            await conn.execute("DELETE FROM favorites")
            await conn.execute("DELETE FROM play_history")
            await conn.execute("DELETE FROM playlist_tracks")
            await conn.execute("DELETE FROM tracks")
            deleted = before
    try:
        mpd_cmd("clear")
        mpd_cmd("update")
    except Exception as exc:
        print(f"[library] reset mpc clear/update skip: {exc}")
    await refresh_library_total()
    return {
        "ok": True,
        "deleted": deleted,
        "total_tracks": 0,
        "upserted": 0,
        "message": "라이브러리 메타데이터가 삭제되었습니다. 다시 스캔해 주세요.",
    }


async def broadcast_usb_prompt(payload: dict[str, Any]) -> None:
    await manager.broadcast({"event": "usb_library_prompt", **payload})


async def broadcast_external_review(payload: dict[str, Any]) -> None:
    await manager.broadcast({"event": "external_library_review", **payload})


async def usb_library_watcher() -> None:
    """외장 스토리지 감지 — 탐색기에서 추가/복사 선택. 자동 복사는 기본 off."""
    interval = max(10, int(os.getenv("WHICK_USB_WATCH_INTERVAL_SEC", "20")))
    # 기본 0: 자동 copy import 하지 않음 (라이브러리 추가 vs 복사는 UI에서)
    auto_mode = os.getenv("WHICK_EXTERNAL_AUTO_MODE", "0") == "1"
    last_key = ""
    while True:
        try:
            from api.external_storage_watch import (
                get_pending_review,
                get_usb_pending,
                process_external_library,
            )

            review = get_pending_review()
            if review:
                key = f"review:{review.get('mount_point')}:{len(review.get('rejected') or [])}"
                if key != last_key:
                    last_key = key
                    await broadcast_external_review(review)
            else:
                pending = get_usb_pending()
                if pending and pending.get("mode") == "detected" and auto_mode:
                    mount = pending.get("mount_point")
                    if mount:
                        incoming = Path(os.getenv("WHICK_LIBRARY_INCOMING", "/var/lib/whick/library/incoming"))
                        music = Path(os.getenv("WHICK_MUSIC_DIR", "/var/lib/whick/library/music"))
                        result = await asyncio.to_thread(
                            process_external_library,
                            str(mount),
                            mode="auto",
                            incoming=incoming,
                            music_root=music,
                        )
                        from api.library_scanner import scan_library, scan_paths_from_env

                        await scan_library(db_pool, scan_paths_from_env())
                        mpd_cmd("update")
                        await refresh_library_total()
                        if result.get("pending_review"):
                            await broadcast_external_review(result["pending_review"])
                        else:
                            await broadcast_usb_prompt(
                                {
                                    "mount_point": mount,
                                    "message": f"자동 검수 완료 — {result.get('imported', {}).get('moved', 0)}곡 추가",
                                    "mode": "auto_done",
                                },
                            )
                        last_key = f"auto:{mount}"
                elif pending:
                    key = f"{pending.get('mount_point')}:{pending.get('audio_files')}:{pending.get('mode')}"
                    if key != last_key:
                        last_key = key
                        await broadcast_usb_prompt(pending)
                else:
                    last_key = ""
        except Exception as exc:
            print(f"[external-watch] {exc}")
        await asyncio.sleep(interval)


def _alsa_card_fingerprint(aplay_l: str) -> str:
    """카드·장치 정체만 지문화. Subdevices: 0/1↔1/1(재생 점유)은 무시.
    재생 중 점유 변화로 MPD를 재시작해 1초 끊김이 나던 오탐을 막는다."""
    lines = []
    for raw in (aplay_l or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        low = line.lower()
        if low.startswith("subdevices:") or low.startswith("subdevice #"):
            continue
        if line.startswith("card ") or "list of playback hardware devices" in low:
            lines.append(line)
    return "\n".join(lines)


def _alsa_usb_inventory_fingerprint(aplay_l: str = "") -> str:
    """aplay 카드 목록 + USB usbid — 이름 같은 다른 DAC 교체도 구분."""
    import re

    from api.asound import asound_root

    parts = [_alsa_card_fingerprint(aplay_l)]
    root = asound_root()
    cards = root / "cards"
    if cards.is_file():
        try:
            text = cards.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        for line in text.splitlines():
            m = re.match(r"\s*(\d+)\s+\[", line)
            if not m:
                continue
            idx = m.group(1)
            usbid_p = root / f"card{idx}" / "usbid"
            id_p = root / f"card{idx}" / "id"
            usb = "-"
            cid = "-"
            try:
                if usbid_p.is_file():
                    usb = usbid_p.read_text(encoding="utf-8", errors="replace").strip().lower() or "-"
            except OSError:
                pass
            try:
                if id_p.is_file():
                    cid = id_p.read_text(encoding="utf-8", errors="replace").strip() or "-"
            except OSError:
                pass
            parts.append(f"card{idx}:{cid}:{usb}")
    return "\n".join(parts)


def _usb_audio_inventory_hash() -> str:
    """lsusb 기반 USB 장치 인벤토리 해시 — 물리적 연결/해제 즉시 반영.
    MPD가 ALSA 장치를 붙잡고 있어 /proc/asound가 갱신되지 않아도,
    lsusb는 USB 버스에서 장치가 사라진 것을 바로 반영한다."""
    import hashlib
    import subprocess as _sp

    try:
        out = _sp.run(["lsusb"], capture_output=True, text=True, timeout=3)
        return hashlib.md5(out.stdout.strip().encode()).hexdigest()
    except Exception:
        return ""


def _has_usb_audio_in_aplay() -> bool:
    """aplay -l 출력에 USB Audio 장치가 있는지 확인."""
    import subprocess as _sp

    try:
        out = _sp.run(["aplay", "-l"], capture_output=True, text=True, timeout=5)
        text = (out.stdout or "").lower()
        return "usb audio" in text or "usb-audio" in text
    except Exception:
        return False


async def _hotplug_active_dsp_profile() -> dict | None:
    """핫플러그 시 활성 EQ/룸보정 유지."""
    try:
        from api.dsp_store import default_dsp_profile, get_profile

        if not db_pool:
            return default_dsp_profile()
        prof = await get_profile(db_pool)
        return prof.get("dsp") or default_dsp_profile()
    except Exception as exc:
        print(f"[dac-hotplug] profile load skipped: {exc}")
        return None


async def _reload_dsp_with_bit_fallback(dsp: dict | None, *, label: str) -> dict:
    """Camilla 재적용 실패 시 playback 포맷만 dump 목록 순으로 재시도.

    capture(Loopback) 포맷은 바꾸지 않는다. dump에 없는 S16을 만들지 않는다.
    """
    from api.alsa_device import list_playback_camilla_formats, playback_format_candidates
    from api.audio_pipeline import reload_profile
    from api.camilla_yaml import _alsa_capture_playback_devices, _alsa_playback_format
    from api.dac_capability import force_probed_alsa_format

    apply = await asyncio.to_thread(reload_profile, dsp, previous=None)
    if apply.get("ok") or dsp is None:
        return apply

    def _resolve_fallback_context() -> tuple[str, list[str], list[str], str]:
        # 장치/포맷 probe 는 aplay --dump-hw-params 등 블로킹 subprocess 이므로
        # 이벤트 루프를 막지 않도록 to_thread 로 돌린다.
        _, pb = _alsa_capture_playback_devices()
        listed = list_playback_camilla_formats(pb)
        candidates = playback_format_candidates(pb)
        current = _alsa_playback_format(pb)
        return pb, listed, candidates, current

    playback, listed, candidates, current = await asyncio.to_thread(_resolve_fallback_context)
    if not listed:
        print(
            f"[dac-hotplug] {label} dump empty for {playback}; "
            f"fallback candidates={candidates}"
        )
    if not candidates:
        err = f"no playback format candidates for {playback}"
        print(f"[dac-hotplug] {label} {err}")
        out = dict(apply)
        out["error"] = apply.get("error") or err
        return out

    tried: list[str] = []
    for fmt in candidates:
        if fmt == current:
            continue
        tried.append(fmt)
        await asyncio.to_thread(
            force_probed_alsa_format,
            fmt,
            reason=f"{label}: playback {current} 실패 → {fmt}",
        )
        apply = await asyncio.to_thread(reload_profile, dsp, previous=None)
        print(f"[dac-hotplug] {label} playback-fallback {current}->{fmt} ok={apply.get('ok')}")
        if apply.get("ok"):
            return apply
        current = fmt
    if not apply.get("ok"):
        err = (
            f"playback format fallback exhausted device={playback} "
            f"start={current!r} tried={tried or candidates}"
        )
        print(f"[dac-hotplug] {label} {err}")
        out = dict(apply)
        out["error"] = apply.get("error") or err
        return out
    return apply


async def _hotplug_probe_capability_bg() -> None:
    """능력 probe 후 clamp 재적용 — probe만 하고 yaml을 안 맞추면 잘못된 rate로 남을 수 있음."""
    try:
        from api.dac_detect import detect_dac_capability
        from api.playback_config import sync_dsp_pipe_env

        await asyncio.to_thread(lambda: detect_dac_capability(save=True, probe=True))
        print("[dac-hotplug] background capability probe done")
        dsp = await _hotplug_active_dsp_profile()
        if dsp is not None:
            sync_dsp_pipe_env(dsp)
            # previous=None → rate/장치 clamp 반영 시 structural 재바인딩 가능
            apply = await _reload_dsp_with_bit_fallback(dsp, label="post-probe")
            print(
                f"[dac-hotplug] post-probe reapply ok={apply.get('ok')} "
                f"method={(apply.get('apply') or {}).get('method')}"
            )
    except Exception as exc:
        print(f"[dac-hotplug] background probe error: {exc}")


def _dac_disconnect_stop() -> None:
    """DAC 분리 시 재생 정지 — STATE 갱신 + MPD 정지."""
    global STATE
    if not STATE.playing:
        return
    STATE.playing = False
    STATE.mpd_active = False
    STATE.server_audio_active = False
    if STATE.source in ("library", "radio", "tidal"):
        stop_server_audio_output()
    # Spotify는 STATE 갱신만으로 충분 — MPD가 없으니 재생 불가


async def _hotplug_rebind(fingerprint: str) -> None:
    """DAC 핫플러그 rebind: DAC 재감지 → MPD 재시작 → Camilla 재적용."""
    try:
        from api.dac_detect import detect_dac_capability
        from api.playback_router import reload_mpd_after_conf_change
        from api.camilla_loopback import invalidate_transport_cache
        from api.camilla_daemon import forget_stored_playback_device, restart_daemon
        from api.playback_config import sync_dsp_pipe_env

        invalidate_transport_cache()
        forget_stored_playback_device()
        await asyncio.to_thread(lambda: detect_dac_capability(save=True, probe=False))
        dsp = await _hotplug_active_dsp_profile()
        result = await asyncio.to_thread(reload_mpd_after_conf_change, dsp)
        if dsp is not None:
            sync_dsp_pipe_env(dsp)
            apply = await _reload_dsp_with_bit_fallback(dsp, label="rebind")
            if not apply.get("ok"):
                apply = await asyncio.to_thread(
                    lambda: restart_daemon(profile=dsp, pause_feeders=True)
                )
            method = ""
            if isinstance(apply, dict):
                method = str(
                    (apply.get("apply") or {}).get("method")
                    or apply.get("method")
                    or ""
                )
            print(
                f"[dac-hotplug] camilla rebind ok={apply.get('ok')} method={method}"
            )
        print(
            "[dac-hotplug] rebind done — "
            f"mpd={result.get('mpd', {}).get('ok')}, "
            f"route={result.get('route', {}).get('mode')}"
        )
        asyncio.create_task(_hotplug_probe_capability_bg())
    except Exception as exc:
        print(f"[dac-hotplug] rebind error: {exc}")


async def dac_hotplug_watcher() -> None:
    """USB DAC 핫플러그 — usbid 포함 지문 변경 시 즉시 MPD를 현재 카드로 재연결.
    DAC 분리 시 재생 정지 + 알림, 연결 시 알림 + 재연결."""
    import hashlib
    import subprocess as _sp

    last_hash = ""
    last_usb_hash = ""
    dac_connected = False  # 첫 poll에서 초기화
    fail_count = 0
    while True:
        try:
            out = _sp.run(["aplay", "-l"], capture_output=True, text=True, timeout=5)
            fingerprint = _alsa_usb_inventory_fingerprint(out.stdout or "")
            h = hashlib.md5(fingerprint.encode()).hexdigest()
            usb_hash = _usb_audio_inventory_hash()
            has_dac = _has_usb_audio_in_aplay()

            if not last_hash:
                # 초기 상태 기록
                last_hash = h
                if usb_hash:
                    last_usb_hash = usb_hash
                dac_connected = has_dac
                print(f"[dac-hotplug] init dac_connected={dac_connected}")
                await asyncio.sleep(2)
                continue

            # USB 물리계층 변경 감지 → MPD kill 필요
            if usb_hash and last_usb_hash and usb_hash != last_usb_hash:
                if h == last_hash:
                    # USB 변경됐는데 ALSA 지문 그대로 → MPD가 옛 장치 붙잡고 있음 → 강제 kill
                    print("[dac-hotplug] USB inventory change but ALSA fingerprint stale — force release MPD")
                    # MPD kill 전에 STATE 반영 — UI에 재생 중단 표시
                    if STATE.playing:
                        STATE.playing = False
                        STATE.mpd_active = False
                        STATE.server_audio_active = False
                    _sp.run(["mpd", "--kill"], capture_output=True, timeout=3)
                    await asyncio.sleep(1.5)
                    # 다음 poll cycle에서 ALSA fingerprint도 갱신되어 아래 분기에서 처리

            if usb_hash:
                last_usb_hash = usb_hash

            # DAC 상태 변화 감지
            if has_dac != dac_connected or h != last_hash:
                if has_dac and not dac_connected:
                    # DAC 연결됨 → 알림 + 재연결
                    print("[dac-hotplug] DAC connected — notify + rebind")
                    await manager.broadcast({
                        "event": "notify",
                        "title": "DAC 연결됨",
                        "message": "새로운 오디오 장치가 연결되었습니다. 재생을 다시 시작하려면 곡을 선택해 주세요.",
                    })
                    dac_connected = True
                    # rebind 진행
                    if h != last_hash:
                        await _hotplug_rebind(fingerprint)
                elif not has_dac and dac_connected:
                    # DAC 분리됨 → 재생 정지 + 알림
                    print("[dac-hotplug] DAC disconnected — stop playback + notify")
                    _dac_disconnect_stop()
                    await manager.broadcast({
                        "event": "notify",
                        "title": "DAC 연결 해제됨",
                        "message": "오디오 장치 연결이 끊어졌습니다. 장치를 다시 연결하면 재생할 수 있습니다.",
                    })
                    dac_connected = False
                elif has_dac and dac_connected and h != last_hash:
                    # DAC 교체 (다른 DAC로 전환)
                    print(f"[dac-hotplug] DAC changed — rebind\n{fingerprint}")
                    await _hotplug_rebind(fingerprint)

            last_hash = h
            fail_count = 0
        except Exception as exc:
            fail_count += 1
            if fail_count > 10:
                print(f"[dac-hotplug] persistent error: {exc}")
                fail_count = 0
        await asyncio.sleep(2)


async def camilla_watchdog() -> None:
    """camilladsp 상주 감시 — 예기치 않게 죽으면 자동 재시작.

    EPIPE(xrun) 등으로 camilladsp가 종료되면 defunct로 남아 소리가 끊기는데,
    핫플러그 watcher는 USB 연결 변화만 보고 프로세스 생존은 감시하지 않아
    방치됐다. 여기서 주기적으로 is_running()을 확인해 죽었으면 재시작한다.
    direct/bitperfect(suspend) 모드와 DAC 미연결 상태는 건드리지 않는다.
    """
    # 모듈 참조 유지 — _suspended_for_direct 는 suspend_for_direct_playback() 이
    # global 로 뒤집는 값이므로 from-import(값 스냅샷)하면 stale False 로 남는다.
    import api.camilla_daemon as camilla_daemon

    fail_streak = 0
    while True:
        try:
            await asyncio.sleep(10)
            if camilla_daemon.is_running():
                fail_streak = 0
                continue
            if camilla_daemon._suspended_for_direct:
                continue
            if not _has_usb_audio_in_aplay():
                continue
            fail_streak += 1
            if fail_streak > 6:
                print("[camilla-watchdog] repeated failures — backoff 60s")
                await asyncio.sleep(60)
                fail_streak = 0
                continue
            print("[camilla-watchdog] camilladsp not running — restart")
            r = await asyncio.to_thread(camilla_daemon.restart_daemon, pause_feeders=False)
            if not r.get("ok"):
                fail_streak += 1
        except Exception as exc:
            print(f"[camilla-watchdog] error: {exc}")
            await asyncio.sleep(5)


@app.get("/api/library/incoming-audit")
async def library_incoming_audit():
    """incoming Hi-res 검수 — robot-auditor와 동일 규칙 · 파일 변경 없음."""
    from api.library_scanner import audit_incoming_files

    incoming = Path(os.getenv("WHICK_LIBRARY_INCOMING", "/var/lib/whick/library/incoming"))
    result = await asyncio.to_thread(audit_incoming_files, incoming)
    return {"ok": True, **result}


@app.post("/api/library/import-incoming")
async def library_import_incoming(body: dict[str, Any] = Body(default={})):
    """검수 승인 파일만 라이브러리로 이동 — user_approved 필수."""
    if body.get("user_approved") is not True:
        raise HTTPException(
            status_code=403,
            detail="user_approved=true 필요 — 검수 결과 확인 후 사용자가 승인해야 import 됩니다",
        )
    from api.library_scanner import import_incoming_files, scan_library, scan_paths_from_env

    incoming = Path(os.getenv("WHICK_LIBRARY_INCOMING", "/var/lib/whick/library/incoming"))
    music = Path(os.getenv("WHICK_MUSIC_DIR", "/var/lib/whick/library/music"))
    approved_paths = body.get("approved_paths")
    if not isinstance(approved_paths, list) or not approved_paths:
        raise HTTPException(status_code=400, detail="approved_paths required (검수 승인 목록)")
    imported = await asyncio.to_thread(import_incoming_files, incoming, music, approved_paths)
    result = await scan_library(db_pool, scan_paths_from_env())
    mpd_cmd("update")
    await refresh_library_total()
    try:
        from api.loudness_normalize import kick

        kick()
    except Exception:
        pass
    return {"ok": True, "imported": imported, "scan": asdict(result)}


@app.post("/api/library/delete-incoming")
async def library_delete_incoming(body: dict[str, Any] = Body(default={})):
    """검수 탈락 파일 삭제 — user_approved + paths 필수."""
    if body.get("user_approved") is not True:
        raise HTTPException(
            status_code=403,
            detail="user_approved=true 필요 — 사용자가 삭제를 허락하지 않으면 진행하지 않습니다",
        )
    paths = body.get("paths")
    if not isinstance(paths, list) or not paths:
        raise HTTPException(status_code=400, detail="paths required")
    from api.library_scanner import delete_incoming_files

    incoming = Path(os.getenv("WHICK_LIBRARY_INCOMING", "/var/lib/whick/library/incoming"))
    deleted = await asyncio.to_thread(delete_incoming_files, incoming, paths)
    return {"ok": True, "deleted": deleted}


@app.post("/api/library/tracks/delete")
async def library_tracks_delete(body: dict[str, Any] = Body(default={})):
    """라이브러리 목록(바로가기)에서만 제거 — DB 메타만 삭제.
    실제 음원 파일 삭제는 /api/library/fs/delete (설정→파일 탐색기) 전용.
    body.delete_files 는 무시한다."""
    raw_ids = body.get("track_ids") if isinstance(body.get("track_ids"), list) else []
    track_ids: list[int] = []
    for x in raw_ids:
        try:
            n = int(x)
        except (TypeError, ValueError):
            continue
        if n > 0:
            track_ids.append(n)
    track_ids = sorted(set(track_ids))
    if not track_ids:
        raise HTTPException(status_code=400, detail="track_ids required")
    if not db_pool:
        raise HTTPException(status_code=503, detail="db unavailable")

    from api.library_scanner import delete_tracks_by_ids

    removed, _paths = await delete_tracks_by_ids(db_pool, track_ids)
    try:
        mpd_cmd("update")
    except Exception as exc:
        print(f"[library] tracks delete mpc update skip: {exc}")
    await refresh_library_total()
    return {
        "ok": True,
        "deleted": removed,
        "files_deleted": 0,
        "file_errors": [],
        "total_tracks": STATE.library_total,
        "message": "라이브러리 목록에서만 제거했습니다. 음원 파일은 유지됩니다.",
    }


@app.get("/api/library/usb-pending")
async def library_usb_pending():
    from api.external_storage_watch import get_pending_review, get_usb_pending

    pending = get_usb_pending()
    review = get_pending_review()
    return {"ok": True, "pending": pending, "review": review}


def _fs_http(exc: Exception):
    from api.library_fs import LibraryFsError

    if isinstance(exc, LibraryFsError):
        code = 400
        if exc.code in ("not_found", "not_a_dir"):
            code = 404
        elif exc.code == "no_space":
            code = 507
        raise HTTPException(status_code=code, detail=exc.message) from exc
    raise exc


@app.get("/api/library/fs/browse")
async def library_fs_browse(root: str = "music", path: str = ""):
    """탐색기 목록 — root=music|/media(ui), path=상대."""
    from api.library_fs import LibraryFsError, list_dir

    r = "media" if str(root).strip().lower() in ("media", "/media") else "music"
    try:
        return {"ok": True, **await asyncio.to_thread(list_dir, r, path)}
    except LibraryFsError as exc:
        _fs_http(exc)


@app.post("/api/library/fs/mkdir")
async def library_fs_mkdir(body: dict[str, Any] = Body(default={})):
    from api.library_fs import LibraryFsError, mkdir

    r = "media" if str(body.get("root") or "").strip().lower() in ("media", "/media") else "music"
    try:
        result = await asyncio.to_thread(mkdir, r, str(body.get("path") or ""), str(body.get("name") or ""))
        return {"ok": True, **result}
    except LibraryFsError as exc:
        _fs_http(exc)


@app.post("/api/library/fs/rename")
async def library_fs_rename(body: dict[str, Any] = Body(default={})):
    from api.library_fs import LibraryFsError, rename
    from api.library_scanner import remap_track_paths

    r = "media" if str(body.get("root") or "").strip().lower() in ("media", "/media") else "music"
    try:
        result = await asyncio.to_thread(
            rename, r, str(body.get("path") or ""), str(body.get("new_name") or "")
        )
        if db_pool and result.get("old_real") and result.get("new_real"):
            await remap_track_paths(db_pool, result["old_real"], result["new_real"])
        mpd_cmd("update")
        return {"ok": True, **result}
    except LibraryFsError as exc:
        _fs_http(exc)


@app.post("/api/library/fs/delete")
async def library_fs_delete(body: dict[str, Any] = Body(default={})):
    from api.library_fs import LibraryFsError, delete_paths, resolve_path
    from api.library_scanner import delete_tracks_under_prefixes

    r = "media" if str(body.get("root") or "").strip().lower() in ("media", "/media") else "music"
    paths = body.get("paths") if isinstance(body.get("paths"), list) else []
    if not paths:
        raise HTTPException(status_code=400, detail="paths required")
    prefixes: list[str] = []
    for p in paths:
        try:
            prefixes.append(str(await asyncio.to_thread(resolve_path, r, str(p))))
        except LibraryFsError:
            continue
    try:
        result = await asyncio.to_thread(delete_paths, r, [str(p) for p in paths])
        # 실제 삭제된 real path 우선 — 사전 resolve 실패·외장 /media↔/run/media 불일치 보완
        for real in result.get("deleted_real") or []:
            if real and real not in prefixes:
                prefixes.append(str(real))
        removed = 0
        if db_pool and prefixes:
            removed = await delete_tracks_under_prefixes(db_pool, prefixes)
        mpd_cmd("update")
        await refresh_library_total()
        return {"ok": True, **result, "tracks_removed": removed}
    except LibraryFsError as exc:
        _fs_http(exc)


@app.post("/api/library/fs/preflight")
async def library_fs_preflight(body: dict[str, Any] = Body(default={})):
    from api.library_fs import LibraryFsError, preflight_copy

    dest_root = "media" if str(body.get("dest_root") or "").strip().lower() in ("media", "/media") else "music"
    sources = body.get("sources") if isinstance(body.get("sources"), list) else []
    try:
        result = await asyncio.to_thread(
            preflight_copy, sources, dest_root, str(body.get("dest_path") or "")
        )
        return {"ok": True, **result}
    except LibraryFsError as exc:
        _fs_http(exc)


@app.post("/api/library/fs/copy")
async def library_fs_copy(request: Request, body: dict[str, Any] = Body(default={})):
    """복사 또는 이동(move=true). 이동 시 원본(외장 포함) 삭제."""
    from api.library_fs import LibraryFsError, collect_audio_under, copy_or_move
    from api.library_scanner import register_audio_files, remap_track_paths

    dest_root = "media" if str(body.get("dest_root") or "").strip().lower() in ("media", "/media") else "music"
    sources = body.get("sources") if isinstance(body.get("sources"), list) else []
    move = bool(body.get("move"))
    if move:
        verify_destructive(request)
    dest_path = str(body.get("dest_path") or "")
    if not sources:
        raise HTTPException(status_code=400, detail="sources required")

    try:
        result = await asyncio.to_thread(
            copy_or_move, sources, dest_root, dest_path, move=move
        )
    except LibraryFsError as exc:
        _fs_http(exc)
        return

    if db_pool:
        register_targets: list[Path] = []
        for res in result.get("results") or []:
            if res.get("error"):
                continue
            if move and res.get("from_real") and res.get("to_real"):
                await remap_track_paths(db_pool, res["from_real"], res["to_real"])
            to_real = res.get("to_real")
            if to_real:
                p = Path(to_real)
                if p.is_file() and p.suffix.lower() in (
                    ".flac", ".wav", ".mp3", ".aac", ".m4a", ".ogg", ".opus",
                    ".aiff", ".aif", ".alac", ".ape", ".wv", ".wma", ".dsf", ".dff",
                ):
                    register_targets.append(p)
                elif p.is_dir():
                    register_targets.extend(await asyncio.to_thread(collect_audio_under, dest_root, [
                        str(res.get("to") or "").replace("music/", "").replace("/media/", "").lstrip("/")
                        if str(res.get("to") or "") not in ("music", "/media") else ""
                    ]))
        # dedupe
        uniq = []
        seen = set()
        for f in register_targets:
            k = str(f.resolve())
            if k not in seen:
                seen.add(k)
                uniq.append(f)
        if uniq:
            await register_audio_files(db_pool, uniq, run_audit=True)

    mpd_cmd("update")
    await refresh_library_total()
    return {"ok": True, **result}


@app.post("/api/library/fs/register")
async def library_fs_register(body: dict[str, Any] = Body(default={})):
    """라이브러리에만 추가 — 파일 복사 없이 경로 등록."""
    from api.library_fs import LibraryFsError, collect_audio_under
    from api.library_scanner import register_audio_files

    r = "media" if str(body.get("root") or "").strip().lower() in ("media", "/media") else "music"
    paths = body.get("paths") if isinstance(body.get("paths"), list) else []
    if not paths:
        raise HTTPException(status_code=400, detail="paths required")
    try:
        files = await asyncio.to_thread(collect_audio_under, r, [str(p) for p in paths])
    except LibraryFsError as exc:
        _fs_http(exc)
        return
    if not files:
        raise HTTPException(status_code=400, detail="등록할 음원 없음")
    if not db_pool:
        raise HTTPException(status_code=503, detail="DB unavailable")
    result = await register_audio_files(db_pool, files, run_audit=bool(body.get("audit")))
    mpd_cmd("update")
    await refresh_library_total()
    try:
        from api.loudness_normalize import kick

        kick()
    except Exception:
        pass
    return result


@app.get("/api/library/external/scan")
async def library_external_scan(mount_point: str = ""):
    """수동 모드 — 외장 스토리지 곡 목록만 스캔."""
    from api.external_storage_watch import detect_external_mounts, scan_mount_file_list

    mount = str(mount_point or "").strip()
    if not mount:
        mounts = [asdict(m) for m in detect_external_mounts()]
        return {"ok": True, "mounts": mounts}
    allowed = {m.mount_point for m in detect_external_mounts()}
    if mount not in allowed:
        raise HTTPException(status_code=403, detail="허용되지 않은 외장 스토리지 경로")
    mp = Path(mount).resolve()
    if not mp.is_dir():
        raise HTTPException(status_code=404, detail="마운트 없음")
    result = await asyncio.to_thread(scan_mount_file_list, mp)
    return {"ok": True, **result}


@app.post("/api/library/external/process")
async def library_external_process(body: dict[str, Any] = Body(default={})):
    """자동/수동 외장 스토리지 검수·import. 탈락분은 import_rejected 로 고객 패스 가능."""
    from api.external_storage_watch import process_external_library
    from api.library_scanner import scan_library, scan_paths_from_env

    mount_point = str(body.get("mount_point") or "").strip()
    if not mount_point:
        raise HTTPException(status_code=400, detail="mount_point required")
    mode = str(body.get("mode") or "manual").strip().lower()
    if mode not in ("auto", "manual"):
        raise HTTPException(status_code=400, detail="mode must be auto or manual")
    paths = body.get("paths")
    if mode == "manual":
        if not isinstance(paths, list) or not paths:
            raise HTTPException(status_code=400, detail="manual mode requires paths[]")
    import_rejected = body.get("import_rejected") if isinstance(body.get("import_rejected"), list) else []
    auto_on_detect = os.getenv("WHICK_EXTERNAL_AUTO_MODE", "1") != "0"

    incoming = Path(os.getenv("WHICK_LIBRARY_INCOMING", "/var/lib/whick/library/incoming"))
    music = Path(os.getenv("WHICK_MUSIC_DIR", "/var/lib/whick/library/music"))

    # 탈락분만 고객 패스 추가 (재검수 없이 staging)
    if import_rejected and not paths:
        from api.external_storage_watch import stage_mount_files_to_incoming, import_staged_paths, mark_mount_processed, set_pending_review

        mp = Path(mount_point).resolve()
        _, staged = await asyncio.to_thread(stage_mount_files_to_incoming, mp, import_rejected, incoming)
        imported = await asyncio.to_thread(import_staged_paths, incoming, music, staged)
        set_pending_review(None)
        mark_mount_processed(mount_point)
        scan_result = await scan_library(db_pool, scan_paths_from_env())
        mpd_cmd("update")
        await refresh_library_total()
        return {"ok": True, "mode": "pass_rejected", "imported": imported, "scan": asdict(scan_result)}
    try:
        result = await asyncio.to_thread(
            process_external_library,
            mount_point,
            mode=mode,
            paths=paths if isinstance(paths, list) else None,
            import_rejected=import_rejected,
            incoming=incoming,
            music_root=music,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    scan_result = await scan_library(db_pool, scan_paths_from_env())
    mpd_cmd("update")
    await refresh_library_total()
    return {"ok": True, **result, "scan": asdict(scan_result)}


@app.post("/api/library/usb-import")
async def library_usb_import(body: dict[str, Any] = Body(default={})):
    from api.library_scanner import scan_library, scan_paths_from_env
    from api.external_storage_watch import process_external_library

    mount_point = str(body.get("mount_point") or "").strip()
    if not mount_point:
        raise HTTPException(status_code=400, detail="USB 마운트 없음")

    incoming = Path(os.getenv("WHICK_LIBRARY_INCOMING", "/var/lib/whick/library/incoming"))
    music = Path(os.getenv("WHICK_MUSIC_DIR", "/var/lib/whick/library/music"))
    try:
        result = await asyncio.to_thread(
            process_external_library,
            mount_point,
            mode=str(body.get("mode") or "auto"),
            paths=body.get("paths") if isinstance(body.get("paths"), list) else None,
            import_rejected=body.get("import_rejected") if isinstance(body.get("import_rejected"), list) else [],
            incoming=incoming,
            music_root=music,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    scan_result = await scan_library(db_pool, scan_paths_from_env())
    mpd_cmd("update")
    await refresh_library_total()
    return {"ok": True, **result, "scan": asdict(scan_result)}


@app.post("/api/library/usb-dismiss")
async def library_usb_dismiss(body: dict[str, Any] = Body(default={})):
    from api.external_storage_watch import dismiss_usb_prompt

    dismiss_usb_prompt(body.get("mount_point"))
    return {"ok": True}


@app.get("/api/radio")
async def get_radio():
    return {"stations": [radio_public_station(s) for s in RADIO_STATIONS]}


@app.get("/api/radio/{station_id}/stream")
async def radio_stream(station_id: str):
    station = radio_station_by_id(station_id)
    if not station:
        raise HTTPException(status_code=404, detail="방송국 없음")
    try:
        stream_url = await resolve_radio_stream_url(station)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "ok": True,
        "stream_url": stream_url,
        "name": station["name"],
        "org": station.get("org"),
        "station_id": station_id,
    }


@app.get("/api/radio/{station_id}/mobile-stream")
async def radio_mobile_stream(station_id: str):
    """라디오 HLS(m3u8)를 연속 MP3 스트림으로 프록시.
    안드로이드 크롬은 native HLS 재생을 지원하지 않아 m3u8 을 <audio> 로 직접 재생하면
    무음이 된다. 미니PC(항상 켜짐) 에서 ffmpeg 로 연속 스트림으로 변환해 same-origin 으로
    내보내면 모바일 출력에서도 정상 재생되고 CORS·스펙트럼 문제도 함께 해결된다."""
    station = radio_station_by_id(station_id)
    if not station:
        raise HTTPException(status_code=404, detail="방송국 없음")
    try:
        stream_url = await resolve_radio_stream_url(station)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    # 소스 코덱 판별 — AAC(국내 라디오 대부분)는 재인코딩 없이 ADTS 로 remux 하면
    # 인코딩 지터가 없어 끊김이 크게 준다. 안드로이드 크롬은 ADTS AAC 직접 재생 가능.
    codec = ""
    try:
        pr = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-select_streams", "a:0",
            "-show_entries", "stream=codec_name", "-of",
            "default=noprint_wrappers=1:nokey=1", stream_url,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(pr.communicate(), timeout=10)
        # HLS 는 변형 스트림이 여러 개라 "aac\naac" 처럼 여러 줄이 올 수 있음 → 첫 토큰만 사용
        toks = out.decode(errors="ignore").split()
        codec = toks[0].strip().lower() if toks else ""
    except Exception:
        codec = ""

    common = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-reconnect", "1", "-reconnect_streamed", "1",
        "-reconnect_on_network_error", "1", "-reconnect_delay_max", "5",
        "-rw_timeout", "15000000",
        "-i", stream_url, "-vn",
        # 패킷을 모아두지 않고 즉시 내보내 폰 <audio> 의 언더런(미세 끊김)을 줄인다.
        "-flush_packets", "1",
    ]
    if codec == "aac":
        args = common + ["-c:a", "copy", "-f", "adts", "pipe:1"]
        media_type = "audio/aac"
    else:
        args = common + ["-c:a", "libmp3lame", "-b:a", "192k", "-f", "mp3", "pipe:1"]
        media_type = "audio/mpeg"

    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )

    async def gen():
        try:
            while True:
                chunk = await proc.stdout.read(32768)
                if not chunk:
                    break
                yield chunk
        finally:
            if proc.returncode is None:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
            await proc.wait()

    return StreamingResponse(
        gen(),
        media_type=media_type,
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/radio/{station_id}/play")
async def play_radio(station_id: str, output: str = Query("server")):
    station = radio_station_by_id(station_id)
    if not station:
        raise HTTPException(status_code=404, detail="방송국 없음")
    out = str(output or "server").lower()
    await handle_command({"cmd": "play_radio", "station_id": station_id, "output": out})
    if STATE.source != "radio" or not STATE.playing:
        raise HTTPException(status_code=502, detail="라디오 재생 실패")
    return {
        "ok": True,
        "name": station["name"],
        "org": station.get("org"),
        "station_id": station_id,
        "playback": "mobile" if out == "mobile" else "server",
    }


@app.get("/api/dsp/presets")
async def dsp_presets():
    from api.dsp_store import EQ_BAND_DEFS, PRESET_CATALOG

    return {
        "bands": EQ_BAND_DEFS,
        "presets": [
            {k: p[k] for k in ("slug", "labelKo", "description") if k in p}
            for p in PRESET_CATALOG
        ],
    }


@app.get("/api/dsp/pipeline")
async def dsp_pipeline_status():
    from api.audio_pipeline import pipeline_status
    from api.dsp_store import get_profile

    prof = await get_profile(db_pool) if db_pool else {}
    return pipeline_status(prof.get("dsp"))


@app.get("/api/dsp/profile")
async def dsp_profile():
    from api.dsp_store import get_profile

    return await get_profile(db_pool)


@app.post("/api/dsp/profile")
async def dsp_profile_save(body: dict[str, Any] = Body(...)):
    from api.dsp_store import save_profile

    dsp = body.get("dsp") or body
    preset = body.get("presetSlug") or dsp.get("presetSlug")
    saved = await save_profile(db_pool, dsp, preset_slug=preset)
    await notify_audio_dsp_reload()
    return {"ok": True, **saved}


@app.post("/api/dsp/eq")
async def dsp_eq_save(body: dict[str, Any] = Body(...)):
    from api.dsp_store import save_user_eq

    gains = body.get("gains")
    balance = body.get("balanceDb") or body.get("balance_db")
    master_gain = body.get("masterGainDb")
    if master_gain is None:
        master_gain = body.get("master_gain_db")
    dsp_enabled = body.get("enabled") if "enabled" in body else body.get("dspEnabled")
    eq_enabled = body.get("eqEnabled") if "eqEnabled" in body else body.get("eq_enabled", True)
    saved = await save_user_eq(
        db_pool,
        eq_enabled=bool(eq_enabled),
        gains=gains if isinstance(gains, list) else None,
        balance_db=balance if isinstance(balance, dict) else None,
        master_gain_db=float(master_gain) if master_gain is not None else None,
        dsp_enabled=bool(dsp_enabled) if dsp_enabled is not None else None,
    )
    await notify_audio_dsp_reload()
    return {"ok": True, **saved}


@app.post("/api/dsp/preset/{preset_slug}")
async def dsp_apply_preset(preset_slug: str):
    from api.dsp_store import save_preset

    try:
        saved = await save_preset(db_pool, preset_slug)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await notify_audio_dsp_reload()
    return {"ok": True, **saved}


@app.post("/api/dsp/room-correction")
async def dsp_room_correction(body: dict[str, Any] = Body(...)):
    from api.dsp_store import save_room_correction

    peaking = body.get("peaking") or []
    if not isinstance(peaking, list) or not peaking:
        raise HTTPException(status_code=400, detail="peaking 배열 필요")
    saved = await save_room_correction(db_pool, peaking)
    await notify_audio_dsp_reload()
    return {"ok": True, **saved}


@app.post("/api/dsp/channel-setup")
async def dsp_channel_setup(body: dict[str, Any] = Body(...)):
    from api.dsp_store import save_channel_setup

    swap = body.get("swapChannels")
    if swap is None:
        swap = body.get("swap_channels")
    if swap is None:
        raise HTTPException(status_code=400, detail="swapChannels 필요")
    saved = await save_channel_setup(db_pool, swap_channels=bool(swap))
    await notify_audio_dsp_reload()
    return {"ok": True, **saved}


@app.post("/api/dsp/pipe-rate")
async def dsp_pipe_rate_save(body: dict[str, Any] = Body(...)):
    from api.dsp_store import save_dsp_pipe_rate

    rate = body.get("rateKhz")
    if rate is None:
        rate = body.get("dspPipeRateKhz")
    saved = await save_dsp_pipe_rate(db_pool, rate)
    await notify_audio_dsp_reload()
    return {"ok": True, "profile": saved}


@app.post("/api/dsp/dac-preprocess")
async def dsp_dac_preprocess(body: dict[str, Any] = Body(...)):
    from api.dsp_store import save_dac_preprocess

    enabled = body.get("enabled")
    if enabled is None:
        enabled = body.get("dacPreprocessEnabled", False)
    os_factor = body.get("dacOsFactor")
    if os_factor is None:
        os_factor = body.get("osFactor")
    os_auto = body.get("dacOsFactorAuto")
    if os_auto is None and body.get("osFactorMode") == "manual":
        os_auto = False
    if os_auto is None and body.get("osFactorMode") == "auto":
        os_auto = True
    if os_factor is not None:
        os_factor = 8 if int(os_factor) == 8 else 4
    saved = await save_dac_preprocess(
        db_pool,
        bool(enabled),
        os_factor=os_factor,
        os_factor_auto=os_auto,
    )
    await notify_audio_dsp_reload()
    return {"ok": True, **saved}


@app.get("/api/dac/capability")
async def dac_capability_get():
    from api.dac_capability import load_dac_capability

    return {"ok": True, "capability": load_dac_capability()}


@app.post("/api/dac/capability/detect")
async def dac_capability_detect():
    from api.dac_detect import detect_dac_capability
    from api.playback_router import reload_mpd_after_conf_change
    from api.dsp_store import get_profile, default_dsp_profile

    cap = detect_dac_capability(save=True)
    prof = await get_profile(db_pool) if db_pool else {}
    dsp = prof.get("dsp") or default_dsp_profile()
    reload = reload_mpd_after_conf_change(dsp)
    return {"ok": True, "capability": cap, "mpd_regenerated": True, **reload}


@app.post("/api/dac/capability")
async def dac_capability_save(body: dict[str, Any] = Body(...)):
    from api.dac_capability import save_dac_capability

    cap = body.get("capability") or body
    saved = save_dac_capability(cap)
    from api.playback_router import reload_mpd_after_conf_change
    from api.dsp_store import get_profile, default_dsp_profile

    prof = await get_profile(db_pool) if db_pool else {}
    dsp = prof.get("dsp") or default_dsp_profile()
    reload = reload_mpd_after_conf_change(dsp)
    return {"ok": True, "capability": saved, **reload}


@app.post("/api/spatial/test-tone")
async def spatial_test_tone(body: dict[str, Any] = Body(default={})):
    from api import spatial_session

    channel = str(body.get("channel") or "left").lower()
    if channel not in ("left", "right", "l", "r"):
        raise HTTPException(status_code=400, detail="channel은 left 또는 right")
    swap_override = body.get("swapChannels")
    if swap_override is None:
        swap_override = body.get("swap_channels")
    await spatial_session.play_test_tone(
        channel,
        swap_channels=bool(swap_override) if swap_override is not None else None,
    )
    return {"ok": True, "channel": "right" if channel.startswith("r") else "left"}


def _require_external_providers() -> None:
    if not EXTERNAL_PROVIDERS_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="외부 스트리밍(Spotify·Tidal)은 WHICK_PLAYER_EXTERNAL_PROVIDERS=1 필요",
        )


@app.get("/api/streaming/status")
async def streaming_status():
    _require_external_providers()
    from api import streaming_providers

    return streaming_providers.get_streaming_status()


@app.post("/api/streaming/spotify/connect/start")
async def streaming_spotify_start():
    _require_external_providers()
    from api import streaming_providers

    return await streaming_providers.spotify_connect_start()


@app.post("/api/streaming/spotify/connect/complete")
async def streaming_spotify_complete():
    _require_external_providers()
    from api import streaming_providers

    return streaming_providers.spotify_connect_complete()


@app.post("/api/streaming/spotify/disconnect")
async def streaming_spotify_disconnect():
    _require_external_providers()
    from api import streaming_providers

    return streaming_providers.spotify_disconnect()


@app.get("/api/streaming/spotify/oauth/status")
async def streaming_spotify_oauth_status():
    _require_external_providers()
    from api import streaming_spotify_oauth

    return {"ok": True, **streaming_spotify_oauth.oauth_status()}


@app.post("/api/streaming/spotify/oauth/start")
async def streaming_spotify_oauth_start():
    _require_external_providers()
    from api import streaming_spotify_oauth

    data = streaming_spotify_oauth.oauth_start()
    if not data.get("ok"):
        raise HTTPException(status_code=503, detail=data.get("error", "oauth unavailable"))
    return data


@app.get("/api/streaming/spotify/oauth/callback")
async def streaming_spotify_oauth_callback(
    code: str = Query(""),
    state: str = Query(""),
    error: str = Query(""),
):
    _require_external_providers()
    from api import streaming_spotify_oauth

    if error:
        return HTMLResponse(
            streaming_spotify_oauth.oauth_error_html(f"Spotify: {error}"),
            status_code=400,
        )
    if not code or not state:
        return HTMLResponse(
            streaming_spotify_oauth.oauth_error_html("code/state 누락"),
            status_code=400,
        )
    ok, message = await streaming_spotify_oauth.oauth_callback(code, state)
    if not ok:
        return HTMLResponse(streaming_spotify_oauth.oauth_error_html(message), status_code=400)
    return HTMLResponse(streaming_spotify_oauth.oauth_success_html(message))


@app.post("/api/streaming/tidal/connect/start")
async def streaming_tidal_start():
    _require_external_providers()
    from api import streaming_providers

    return await streaming_providers.tidal_connect_start()


@app.get("/api/streaming/tidal/connect/poll")
async def streaming_tidal_poll():
    _require_external_providers()
    from api import streaming_providers

    try:
        return await streaming_providers.tidal_connect_poll()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/streaming/tidal/disconnect")
async def streaming_tidal_disconnect():
    _require_external_providers()
    from api import streaming_providers

    return streaming_providers.tidal_disconnect()


@app.post("/api/streaming/tidal/lab-approve")
async def streaming_tidal_lab_approve():
    """E2E lab — Tidal device code 승인 시뮬레이션."""
    _require_external_providers()
    from api import streaming_providers

    return streaming_providers.tidal_lab_approve()


@app.get("/api/streaming/search")
async def streaming_search(
    q: str = Query(..., min_length=1),
    providers: str = Query("spotify,tidal"),
):
    _require_external_providers()
    from api import streaming_playback

    want = [p.strip() for p in providers.split(",") if p.strip()]
    data = await streaming_playback.federated_search(q, want)
    return {"ok": True, **data}


@app.get("/api/streaming/playback-url")
async def streaming_playback_url(
    provider: str = Query(...),
    stream_id: str = Query(...),
):
    _require_external_providers()
    from api import streaming_playback

    prov = provider.strip().lower()
    if prov not in ("spotify", "tidal") or not stream_id.strip():
        raise HTTPException(status_code=400, detail="provider · stream_id 필요")
    data = await streaming_playback.get_mobile_playback_url(prov, stream_id.strip())  # type: ignore[arg-type]
    if not data.get("ok"):
        raise HTTPException(status_code=404, detail=data.get("error") or "playback url unavailable")
    return data


@app.post("/api/streaming/play")
async def streaming_play(body: dict[str, Any] = Body(...)):
    _require_external_providers()
    provider = str(body.get("provider") or body.get("source") or "").lower()
    stream_id = str(body.get("stream_id") or "")
    if provider not in ("spotify", "tidal") or not stream_id:
        raise HTTPException(status_code=400, detail="provider · stream_id 필요")
    items = body.get("items") or body.get("queue")
    if isinstance(items, list) and items:
        await handle_command(
            {
                "cmd": "play_streaming_queue",
                "items": items,
                "index": body.get("index", 0),
            }
        )
    else:
        await handle_command(
            {
                "cmd": "play_streaming",
                "provider": provider,
                "stream_id": stream_id,
                "meta": body.get("meta") or body,
                "queue": items if isinstance(items, list) else None,
            }
        )
    await broadcast_state()
    return {"ok": True, "state": asdict(STATE)}


def _restart_dsp_pipe_only() -> None:
    """레거시 no-op — 상주 Camilla는 파이프 restart 없음."""
    print("[DSP] pipe restart skipped (camilla resident)")


_prev_dsp_profile: dict[str, Any] | None = None


async def notify_audio_dsp_reload() -> None:
    global _prev_dsp_profile
    from api.audio_pipeline import reload_profile
    from api.dsp_store import get_profile
    from api.playback_router import sync_playback_route

    if db_pool:
        try:
            prof = await get_profile(db_pool)
            dsp = prof.get("dsp") or {}
            from api.playback_config import sync_dsp_pipe_env

            sync_dsp_pipe_env(dsp)
            # reload_profile → camilla_ws._run_sync 경로가 동기 블록이므로
            # 이벤트루프에서 직접 호출하면 /health 포함 전 요청이 먹통이 된다.
            # (_reload_dsp_with_bit_fallback 등 다른 호출부는 이미 to_thread 사용)
            apply = await asyncio.to_thread(reload_profile, dsp, previous=_prev_dsp_profile)
            _prev_dsp_profile = dict(dsp)
            method = str((apply.get("apply") or {}).get("method") or "")
            # hot apply(필터만) = 파이프 유지. restart_* 만 라우트 재동기화
            if method not in ("patch_config", "set_config", "set_config_full", "reload", "start"):
                await asyncio.to_thread(sync_playback_route, dsp)
            print(f"[DSP] resident apply method={method or 'unknown'} ok={apply.get('ok')}")
        except Exception as exc:
            print(f"[DSP] profile reload skip: {exc}")
    audio_url = os.getenv("WHICK_AUDIO_URL", "http://audio:8787")
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            await client.post(f"{audio_url}/dsp/reload")
    except Exception as exc:
        print(f"[DSP] audio reload skip: {exc}")


def _cc_agent_credentials() -> tuple[str, str]:
    state_path = Path(os.getenv("WHICK_STATE_PATH", "/var/lib/whick/runtime-state.json"))
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"업데이트 인증정보를 읽을 수 없습니다: {exc}") from exc
    token = str(state.get("token") or os.getenv("WHICK_AGENT_TOKEN") or "").strip()
    if not token:
        raise HTTPException(status_code=503, detail="업데이트 인증정보가 없습니다")
    cc_base = os.getenv("WHICK_CC_API_URL", "https://admin.whick.org/api/v1").rstrip("/")
    return cc_base, token


async def _cc_agent_update_request(
    method: str, path: str, body: dict[str, Any] | None = None
) -> dict[str, Any]:
    cc_base, token = _cc_agent_credentials()
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.request(
                method,
                f"{cc_base}/agent{path}",
                headers={"Authorization": f"Bearer {token}"},
                json=body,
            )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"업데이트 서버 연결 실패: {exc}") from exc
    try:
        payload = response.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail="업데이트 서버 응답 오류") from exc
    if response.status_code >= 400 or payload.get("ok") is False:
        message = (payload.get("error") or {}).get("message") or f"업데이트 서버 오류 ({response.status_code})"
        raise HTTPException(status_code=502, detail=message)
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


async def _flush_local_update_result_if_any() -> None:
    """에이전트 heartbeat flush가 실패해도, 리모컨 status 폴링으로 완료 보고를 재시도.

    update-result.json → .flushing 으로 rename 해 agent/동시 폴링과 원자적으로 소유권을 나눔.
    """
    result_path = Path("/var/lib/whick/update-result.json")
    claim_path = Path("/var/lib/whick/update-result.flushing.json")
    try:
        result_path.rename(claim_path)
    except FileNotFoundError:
        return
    except OSError as exc:
        print(f"[update] deferred result claim skip: {exc}")
        return
    try:
        result = json.loads(claim_path.read_text(encoding="utf-8"))
    except Exception:
        try:
            if claim_path.is_file() and not result_path.is_file():
                claim_path.rename(result_path)
        except OSError:
            pass
        return
    update_id = result.get("update_id")
    if update_id is None or not isinstance(result.get("success"), bool):
        claim_path.unlink(missing_ok=True)
        return
    ok_flag = bool(result.get("success"))
    message = result.get("message") or ("업데이트 완료" if ok_flag else "업데이트 실패")
    try:
        await _cc_agent_update_request(
            "POST",
            f"/updates/{update_id}/report",
            {
                "success": ok_flag,
                "message": message,
                "error_code": result.get("error_code"),
                "detail": {
                    "target_version": result.get("target_version"),
                    "applied_version": result.get("target_version") if ok_flag else None,
                    "software_version": result.get("target_version") if ok_flag else None,
                    "command_id": result.get("command_id") or None,
                    "source": "player_update_status_flush",
                },
            },
        )
        claim_path.unlink(missing_ok=True)
        Path("/var/lib/whick/update-progress.json").unlink(missing_ok=True)
    except Exception as exc:
        print(f"[update] deferred result flush skip: {exc}")
        try:
            if claim_path.is_file() and not result_path.is_file():
                claim_path.rename(result_path)
        except OSError:
            pass


@app.get("/api/update/status")
async def update_status():
    """판매 리모컨용 최신버전·업데이트 진행 상태(+로컬 진행률)."""
    await _flush_local_update_result_if_any()
    data = await _cc_agent_update_request("GET", "/updates/available")
    busy = str(data.get("status") or "") in {
        "ai_queued",
        "ai_in_progress",
        "staff_approval_pending",
        "staff_in_progress",
    }
    # ai_queued는 아직 에이전트가 시작 안 했으므로 진행률 파일 의미 없음
    if busy and str(data.get("status") or "") == "ai_queued":
        data["progress_percent"] = None
        data["progress_phase"] = None
        data["progress_message"] = "업데이트를 준비하고 있습니다."
    elif busy:
        progress_path = Path("/var/lib/whick/update-progress.json")
        if progress_path.is_file():
            try:
                progress = json.loads(progress_path.read_text(encoding="utf-8"))
                pct = int(progress.get("percent") or 0)
                if pct < 0:
                    pct = 0
                if pct > 100:
                    pct = 100
                data["progress_percent"] = pct
                data["progress_phase"] = progress.get("phase") or None
                data["progress_message"] = progress.get("message") or None
            except Exception:
                pass
    elif not busy:
        data.setdefault("progress_percent", 100 if data.get("available") is False else None)
    return data


@app.post("/api/update/prepare")
async def update_prepare():
    """고객 동의 후 CC 업데이트 목록에 등록. 등록 성공 시에만 apply 가능."""
    # 1) 최신 버전 존재 확인
    status = await _cc_agent_update_request("GET", "/updates/available")
    available = status.get("available", False)
    if not available:
        raise HTTPException(status_code=404, detail="사용 가능한 업데이트가 없습니다")
    if not status.get("can_start"):
        raise HTTPException(status_code=404, detail="현재 기기에 적용 가능한 업데이트가 없습니다")
    # 2) CC에 업데이트 레코드 등록 (상태: ai_queued)
    try:
        result = await _cc_agent_update_request("POST", "/updates/request", {"confirm": True})
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"CC 업데이트 등록 실패: {exc}") from exc
    return {
        "ok": True,
        "version": result.get("target_version") or status.get("target_version"),
        "message": "업데이트가 CC에 등록되었습니다. 곧 적용이 시작됩니다.",
        "can_start": True,
        "registered": True,
    }


@app.post("/api/update/apply")
async def update_apply(body: dict[str, Any] = Body(...)):
    """CC 업데이트 등록 후 실제 큐 시작."""
    if body.get("confirm") is not True:
        raise HTTPException(status_code=400, detail="업데이트 동의가 필요합니다")
    # 이미 prepare에서 등록했으면 재등록 없이 진행 상태만 반환
    try:
        result = await _cc_agent_update_request("POST", "/updates/request", {"confirm": True})
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"업데이트 시작 실패: {exc}") from exc
    return {"ok": True, **result}


@app.post("/api/notify")
async def notify_broadcast(body: dict[str, Any] = Body(...)):
    """CC/Agent → 리모컨 알림 브로드캐스트 (동의요청·공지 등)."""
    event = str(body.get("event") or "notify")
    message = str(body.get("message") or body.get("text") or "")
    title = str(body.get("title") or "")
    data = body.get("data") or {}
    payload = {"event": event, "message": message}
    if title:
        payload["title"] = title
    if isinstance(data, dict) and data:
        payload["data"] = data
    if event == "consent_request":
        await _ops_consent_store_pending(payload)
    await manager.broadcast(payload)
    return {"ok": True, "sent": len(manager.connections)}


async def _ops_consent_store_pending(payload: dict[str, Any]) -> None:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    rid = data.get("consent_request_id")
    item_id = str(rid) if rid is not None else f"local-{int(datetime.now(timezone.utc).timestamp() * 1000)}"
    await db_pool.execute(
        """
        INSERT INTO ops_consent (id, title, message, purpose, command_type, agree_url, reject_url, status, received_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, 'pending', now())
        ON CONFLICT (id) DO UPDATE SET
            title = EXCLUDED.title, message = EXCLUDED.message,
            purpose = EXCLUDED.purpose, command_type = EXCLUDED.command_type,
            agree_url = EXCLUDED.agree_url, reject_url = EXCLUDED.reject_url,
            status = 'pending', received_at = now()
        """,
        item_id,
        str(payload.get("title") or "원격 조치 동의 요청"),
        str(payload.get("message") or ""),
        str(data.get("purpose") or ""),
        str(data.get("command_type") or ""),
        str(data.get("agree_url") or ""),
        str(data.get("reject_url") or ""),
    )
    # 최대 20건만 유지
    await db_pool.execute(
        "DELETE FROM ops_consent WHERE id NOT IN (SELECT id FROM ops_consent ORDER BY received_at DESC LIMIT 20)"
    )


@app.get("/api/ops-consent/pending")
async def ops_consent_pending():
    rows = await db_pool.fetch(
        "SELECT id, title, message, purpose, command_type, agree_url, reject_url, status, received_at FROM ops_consent WHERE status = 'pending' ORDER BY received_at DESC"
    )
    items = [dict(r) for r in rows]
    return {"ok": True, "items": items, "count": len(items)}


@app.post("/api/ops-consent/resolve")
async def ops_consent_resolve(body: dict[str, Any] = Body(...)):
    rid = str(body.get("id") or body.get("consent_request_id") or "").strip()
    status = str(body.get("status") or "resolved").strip() or "resolved"
    if not rid:
        raise HTTPException(status_code=400, detail="id required")
    result = await db_pool.execute(
        "UPDATE ops_consent SET status = $1 WHERE id = $2", status, rid
    )
    return {"ok": True}
