"""앨범 배치 생성 큐 — 트랙 목록·테마만 생성 (가사/악기/프롬프트는 곡 페이지에서)."""

import asyncio
import json
import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import async_session
from app.models import Album, MusicProfile, QueueJob, Song
from app.services.ai_client import AIClient
from app.services.openrouter import suggest_track_themes
from app.services.settings_service import get_ai_config

logger = logging.getLogger(__name__)

STALE_JOB_MINUTES = 30
RUNNING_STALE_MINUTES = 3
_active_album_jobs: set[int] = set()


def _model_to_dict(obj) -> dict:
    if obj is None:
        return {}
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


async def _update_job(job_id: int, **kwargs):
    async with async_session() as db:
        job = await db.get(QueueJob, job_id)
        if not job:
            return
        if job.status == "cancelled" and kwargs.get("status") != "cancelled":
            return
        for k, v in kwargs.items():
            setattr(job, k, v)
        job.updated_at = datetime.utcnow()
        await db.commit()


def _job_touched_at(job: QueueJob) -> datetime:
    return job.updated_at or job.created_at or datetime.utcnow()


def is_stale_job(job: QueueJob) -> bool:
    if job.status not in ("pending", "running"):
        return False
    stale_before = datetime.utcnow() - timedelta(minutes=STALE_JOB_MINUTES)
    return _job_touched_at(job) < stale_before


def mark_stale_job_failed(job: QueueJob) -> bool:
    if not is_stale_job(job):
        return False
    job.status = "failed"
    job.message = "작업 시간 초과 (서버 재시작 또는 중단됨)"
    job.updated_at = datetime.utcnow()
    return True


def enqueue_album_job(job_id: int) -> None:
    if job_id in _active_album_jobs:
        return

    async def _run():
        _active_album_jobs.add(job_id)
        try:
            await process_album_job(job_id)
        except Exception:
            logger.exception("앨범 트랙 작업 실패 (job %s)", job_id)
            await _update_job(
                job_id,
                status="failed",
                message="작업 중 오류가 발생했습니다",
            )
        finally:
            _active_album_jobs.discard(job_id)

    asyncio.create_task(_run())


async def resume_pending_album_jobs() -> None:
    async with async_session() as db:
        result = await db.execute(
            select(QueueJob).where(
                QueueJob.job_type == "album_tracks",
                QueueJob.status.in_(("pending", "running")),
            )
        )
        jobs = list(result.scalars().all())
        for job in jobs:
            if is_stale_job(job):
                mark_stale_job_failed(job)
            elif job.status == "running":
                job.status = "pending"
                job.message = "서버 재시작 후 재시도..."
        await db.commit()

    for job in jobs:
        if job.status == "pending":
            enqueue_album_job(job.id)


async def find_active_album_job(db, album_id: int) -> QueueJob | None:
    result = await db.execute(
        select(QueueJob).where(
            QueueJob.job_type == "album_tracks",
            QueueJob.status.in_(("pending", "running")),
        )
    )
    for job in result.scalars():
        payload = json.loads(job.payload_json or "{}")
        if payload.get("album_id") == album_id:
            return job
    return None


def is_stuck_running_job(job: QueueJob) -> bool:
    if job.status != "running":
        return False
    if job.id in _active_album_jobs:
        return False
    threshold = datetime.utcnow() - timedelta(minutes=RUNNING_STALE_MINUTES)
    return _job_touched_at(job) < threshold


def recover_stuck_job(job: QueueJob) -> bool:
    """running인데 워커가 없으면 pending으로 되돌림. album_tracks 전용."""
    if job.job_type != "album_tracks":
        return False
    if job.status == "running" and job.id not in _active_album_jobs:
        job.status = "pending"
        job.message = "작업이 멈춰서 다시 시도합니다..."
        job.updated_at = datetime.utcnow()
        return True
    if is_stuck_running_job(job):
        job.status = "pending"
        job.message = "응답 지연 — 다시 시도합니다..."
        job.updated_at = datetime.utcnow()
        return True
    return False


def maybe_enqueue_album_job(job: QueueJob) -> None:
    if job.job_type != "album_tracks":
        return
    if is_stale_job(job):
        return
    if job.status == "running":
        if job.id in _active_album_jobs:
            return
        recover_stuck_job(job)
    if job.status != "pending":
        return
    enqueue_album_job(job.id)


async def _load_lyrics_client() -> tuple[AIClient, str, float]:
    async with async_session() as db:
        config = await get_ai_config(db)
    task_cfg = config["tasks"]["lyrics"]
    provider = task_cfg["provider"]
    api_key = config["api_keys"].get(provider, "")
    return (
        AIClient(provider, api_key),
        task_cfg["model"],
        task_cfg["temperature"],
    )


async def _load_album_context(album_id: int) -> tuple[dict, dict, int, str | None, int] | None:
    async with async_session() as db:
        album = await db.get(Album, album_id)
        if not album:
            return None

        profile = None
        if album.music_profile_id:
            profile = await db.get(MusicProfile, album.music_profile_id)

        return (
            _model_to_dict(album),
            _model_to_dict(profile),
            album.id,
            album.mood,
            album.track_count,
        )


async def process_album_job(job_id: int):
    await _update_job(job_id, status="running", message="시작 중...")

    async with async_session() as db:
        job = await db.get(QueueJob, job_id)
        if not job:
            return
        payload = json.loads(job.payload_json or "{}")

    album_id = payload.get("album_id")
    track_themes = payload.get("track_themes")

    if not album_id:
        await _update_job(job_id, status="failed", message="앨범 ID 없음")
        return

    async with async_session() as db:
        album = await db.scalar(
            select(Album).options(selectinload(Album.songs)).where(Album.id == album_id)
        )
    if not album:
        await _update_job(job_id, status="failed", message="앨범 없음")
        return

    existing_count = len(album.songs)
    if existing_count >= album.track_count:
        await _update_job(
            job_id,
            status="completed",
            progress=existing_count,
            total=album.track_count,
            message=f"{existing_count}곡 이미 등록됨 — 곡별로 가사·악기·프롬프트를 생성하세요",
            result_json=json.dumps({"song_ids": [s.id for s in album.songs]}),
        )
        return

    album_ctx = await _load_album_context(album_id)
    if not album_ctx:
        await _update_job(job_id, status="failed", message="앨범 없음")
        return

    album_dict, profile_dict, album_pk, album_mood, track_count = album_ctx

    themes = track_themes
    if not themes:
        try:
            lyrics_client, lyrics_model, lyrics_temp = await _load_lyrics_client()
            await _update_job(job_id, message="트랙 테마 생성 중...")
            themes = await asyncio.wait_for(
                suggest_track_themes(
                    lyrics_client,
                    album_dict,
                    profile_dict,
                    track_count,
                    model=lyrics_model,
                    temperature=lyrics_temp,
                ),
                timeout=90.0,
            )
        except asyncio.TimeoutError:
            logger.warning("트랙 테마 생성 시간 초과 (job %s)", job_id)
            await _update_job(job_id, message="테마 생성 지연 — 기본 테마로 등록합니다...")
            themes = None
        except Exception as e:
            logger.exception("트랙 테마 생성 실패 (job %s)", job_id)
            await _update_job(
                job_id,
                status="failed",
                message=f"테마 생성 실패: {str(e)[:120]}",
            )
            return

    if not themes:
        themes = [f"Track {i + 1}" for i in range(track_count)]
    elif len(themes) < track_count:
        themes = list(themes) + [
            f"Track {i + 1}" for i in range(len(themes), track_count)
        ]

    total = track_count
    await _update_job(job_id, total=total, progress=existing_count, message="트랙 등록 중...")

    created_ids: list[int] = [s.id for s in album.songs]
    failed = 0
    themes_slice = themes[:total]
    for i in range(existing_count, total):
        theme = themes_slice[i] if i < len(themes_slice) else f"Track {i + 1}"
        await _update_job(
            job_id,
            progress=i,
            message=f"Track {i + 1}/{total} 등록 중...",
        )

        try:
            async with async_session() as db:
                song = Song(
                    album_id=album_pk,
                    track_number=i + 1,
                    title=f"Track {i + 1}",
                    theme=theme,
                    mood=album_mood,
                )
                db.add(song)
                await db.flush()
                created_ids.append(song.id)
                await db.commit()
        except Exception:
            logger.exception("트랙 등록 실패 (job %s, track %s)", job_id, i + 1)
            failed += 1

    status = "completed" if created_ids else "failed"
    if failed and created_ids:
        message = f"{len(created_ids)}곡 등록 완료 ({failed}곡 실패)"
    elif created_ids:
        message = f"{len(created_ids)}곡 등록 완료 — 곡별로 가사·악기·프롬프트를 생성하세요"
    else:
        message = "트랙 등록에 실패했습니다"

    await _update_job(
        job_id,
        status=status,
        progress=total,
        message=message,
        result_json=json.dumps({"song_ids": created_ids}),
    )
