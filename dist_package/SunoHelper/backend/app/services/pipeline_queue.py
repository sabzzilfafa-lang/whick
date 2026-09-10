"""파이프라인 백그라운드 작업 (단곡 / 합본 플레이리스트)."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

from app.database import async_session
from app.models import QueueJob, Song
from app.services.pipeline_service import run_full_pipeline
from app.services.queue_service import _update_job
from app.services.workflow_service import (
    WORKFLOW_STAGES,
    discard_review_work_dir,
    get_pipeline_config,
    get_work_root,
    publish_review_output,
    REVIEW_WIP_PREFIX,
    sanitize_review_folder_name,
)

_active_pipeline_jobs: set[int] = set()


def _rewrite_output_paths(meta: dict, final_dir: Path) -> dict:
    out = dict(meta)
    for key in ("video_output", "audio_remastered", "ass_path", "thumbnail"):
        val = out.get(key)
        if not val:
            continue
        dest = final_dir / Path(str(val)).name
        if dest.exists():
            out[key] = str(dest)
    return out


def is_pipeline_job_active(job_id: int) -> bool:
    return job_id in _active_pipeline_jobs


def recover_stuck_pipeline_job(job: QueueJob) -> bool:
    """워커가 없는 running 인코딩은 중단된 작업으로 닫음."""
    if job.job_type not in ("pipeline", "playlist"):
        return False
    if job.status != "running":
        return False
    if job.id in _active_pipeline_jobs:
        return False
    job.status = "cancelled"
    job.message = "인코딩이 중단되어 목록에서 닫았습니다"
    job.updated_at = datetime.utcnow()
    return True


def maybe_enqueue_pipeline_job(job: QueueJob) -> None:
    if job.job_type not in ("pipeline", "playlist"):
        return
    if job.id in _active_pipeline_jobs:
        return
    if job.status != "pending":
        return
    if job.job_type == "playlist":
        asyncio.create_task(_run_playlist_wrapper(job.id))
    else:
        asyncio.create_task(_run_pipeline_wrapper(job.id))


async def cancel_pipeline_job(job: QueueJob, db) -> QueueJob:
    """상단 배너에서 끄기 — 인코딩을 목록에서 내림."""
    payload: dict = {}
    try:
        payload = json.loads(job.payload_json or "{}")
    except json.JSONDecodeError:
        payload = {}
    if job.status not in ("completed", "failed", "cancelled"):
        job.status = "cancelled"
        job.message = "사용자가 목록에서 닫음"
        job.updated_at = datetime.utcnow()
        await db.flush()

    out_dir = payload.get("output_dir")
    if out_dir:
        discard_review_work_dir(Path(out_dir))
        return job
    project_path = payload.get("project_path")
    target_stage = payload.get("target_stage") or "review"
    if project_path:
        root = await get_work_root(db)
        stage_folder = next(
            (s["folder"] for s in WORKFLOW_STAGES if s["id"] == target_stage),
            "02_검수대기",
        )
        discard_review_work_dir(
            root / stage_folder / f"{REVIEW_WIP_PREFIX}{Path(project_path).name}"
        )
    return job


async def _run_pipeline_wrapper(job_id: int) -> None:
    if job_id in _active_pipeline_jobs:
        return
    _active_pipeline_jobs.add(job_id)
    try:
        await process_pipeline_job(job_id)
    finally:
        _active_pipeline_jobs.discard(job_id)


async def _run_playlist_wrapper(job_id: int) -> None:
    if job_id in _active_pipeline_jobs:
        return
    _active_pipeline_jobs.add(job_id)
    try:
        await process_playlist_job(job_id)
    finally:
        _active_pipeline_jobs.discard(job_id)


async def process_pipeline_job(job_id: int):
    await _update_job(job_id, status="running", message="파이프라인 시작...", progress=0, total=5)

    async with async_session() as db:
        job = await db.get(QueueJob, job_id)
        if not job:
            return
        payload = json.loads(job.payload_json or "{}")
        project_path = Path(payload["project_path"])
        target_stage = payload.get("target_stage", "review")
        song_id = payload.get("song_id")

        config = await get_pipeline_config(db)
        root = await get_work_root(db)

        stage_folder = next(s["folder"] for s in WORKFLOW_STAGES if s["id"] == target_stage)
        out_parent = root / stage_folder
        output_dir = out_parent / f"{REVIEW_WIP_PREFIX}{project_path.name}"
        discard_review_work_dir(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

    progress_notes: list[str] = []

    def _thread_progress(msg: str):
        progress_notes.append(msg)

    stop_hb = asyncio.Event()

    async def _heartbeat():
        ticks = 0
        while not stop_hb.is_set():
            try:
                await asyncio.wait_for(stop_hb.wait(), timeout=12.0)
                break
            except asyncio.TimeoutError:
                ticks += 1
                note = progress_notes[-1] if progress_notes else "처리 중"
                await _update_job(
                    job_id,
                    status="running",
                    message=f"{note}… {ticks * 12}초",
                    progress=min(4, 1 + ticks // 2),
                    total=5,
                )

    try:
        await _update_job(job_id, message="리마스터·가사싱크·영상 생성 중...", progress=1, total=5)
        hb_task = asyncio.create_task(_heartbeat())
        try:
            meta = await asyncio.to_thread(
                run_full_pipeline,
                project_path,
                output_dir,
                config,
                _thread_progress,
            )
        finally:
            stop_hb.set()
            await hb_task

        await _update_job(job_id, message="출력 폴더 정리 중...", progress=4, total=5)
        final_dir = publish_review_output(output_dir, out_parent, project_path.name)
        meta = _rewrite_output_paths(meta, final_dir)
        video = Path(str(meta.get("video_output") or ""))
        if video.is_file():
            from app.services.workflow_service import remember_pipeline_output

            remember_pipeline_output(project_path, video, {"output_dir": str(final_dir)})
        result = {"output_dir": str(final_dir), **meta}

        if song_id:
            async with async_session() as db2:
                song = await db2.get(Song, song_id)
                if song:
                    remastered = meta.get("audio_remastered")
                    if remastered:
                        song.audio_path = remastered
                    await db2.commit()

        await _update_job(
            job_id,
            status="completed",
            progress=5,
            total=5,
            message="완료",
            result_json=json.dumps(result, ensure_ascii=False),
        )
    except Exception as e:
        stop_hb.set()
        discard_review_work_dir(output_dir)
        # 사전 점검 실패 목록(줄바꿈 다수)이 잘리지 않도록 합본과 동일하게 600자
        await _update_job(job_id, status="failed", message=str(e)[:600])


async def process_playlist_job(job_id: int):
    from app.services.playlist_pipeline_service import run_playlist_pipeline

    await _update_job(
        job_id,
        status="running",
        message="합본 영상 시작...",
        progress=0,
        total=5,
    )

    async with async_session() as db:
        job = await db.get(QueueJob, job_id)
        if not job:
            return
        payload = json.loads(job.payload_json or "{}")
        project_paths = [Path(p) for p in payload.get("project_paths") or []]
        title = payload.get("title") or ""
        subtitle = payload.get("subtitle") or ""
        out_dir = Path(payload["output_dir"])
        config = await get_pipeline_config(db)

    if len(project_paths) < 2:
        discard_review_work_dir(out_dir)
        await _update_job(job_id, status="failed", message="프로젝트가 2개 미만입니다")
        return

    try:
        n = len(project_paths)

        def _progress(msg: str, step: int):
            # thread에서 호출되므로 별도 업데이트는 run 전후에만; 중간은 message로
            pass

        await _update_job(
            job_id,
            message=f"합본 생성 중 ({n}곡) — Whisper 가사 싱크·EQ·인코딩…",
            progress=1,
            total=5,
        )

        stop_hb = asyncio.Event()

        async def _heartbeat():
            ticks = 0
            while not stop_hb.is_set():
                try:
                    await asyncio.wait_for(stop_hb.wait(), timeout=20.0)
                    break
                except asyncio.TimeoutError:
                    ticks += 1
                    await _update_job(
                        job_id,
                        message=f"합본 생성 중 ({n}곡)… {ticks * 20}초 경과",
                        progress=min(4, 1 + ticks // 3),
                        total=5,
                    )

        hb_task = asyncio.create_task(_heartbeat())
        try:
            meta = await asyncio.to_thread(
                run_playlist_pipeline,
                project_paths,
                out_dir,
                title=title or None,
                subtitle=subtitle,
                config=config,
            )
        finally:
            stop_hb.set()
            await hb_task

        final_name = sanitize_review_folder_name(str(meta.get("title") or title or "Playlist"))
        final_dir = publish_review_output(out_dir, out_dir.parent, final_name)
        meta = _rewrite_output_paths(meta, final_dir)
        if project_paths:
            from app.services.workflow_service import remember_pipeline_output

            video = Path(str(meta.get("video_output") or ""))
            if video.is_file():
                remember_pipeline_output(
                    project_paths[0],
                    video,
                    {"output_dir": str(final_dir), "track_count": meta.get("track_count")},
                )

        await _update_job(
            job_id,
            status="completed",
            progress=5,
            total=5,
            message=f"{meta.get('track_count')}곡 합본 완료",
            result_json=json.dumps(
                {
                    "output_dir": str(final_dir),
                    "video_output": meta.get("video_output"),
                    "thumbnail": meta.get("thumbnail"),
                    "title": meta.get("title"),
                    "track_count": meta.get("track_count"),
                    "lyric_cues": meta.get("lyric_cues"),
                },
                ensure_ascii=False,
            ),
        )
    except Exception as e:
        discard_review_work_dir(out_dir)
        # 사전 점검 실패 목록(줄바꿈 다수)이 잘리지 않도록 600자
        await _update_job(job_id, status="failed", message=str(e)[:600])


async def enqueue_pipeline_job(
    project_path: str, target_stage: str = "review", song_id: int | None = None
) -> int:
    async with async_session() as db:
        job = QueueJob(
            job_type="pipeline",
            status="pending",
            payload_json=json.dumps(
                {
                    "project_path": project_path,
                    "target_stage": target_stage,
                    "song_id": song_id,
                }
            ),
        )
        db.add(job)
        await db.flush()
        await db.refresh(job)
        job_id = job.id
        await db.commit()

    asyncio.create_task(_run_pipeline_wrapper(job_id))
    return job_id


async def enqueue_playlist_job(
    project_paths: list[str],
    output_dir: str,
    *,
    title: str = "",
    subtitle: str = "",
    target_stage: str = "review",
) -> int:
    async with async_session() as db:
        job = QueueJob(
            job_type="playlist",
            status="pending",
            total=5,
            progress=0,
            message="합본 대기 중...",
            payload_json=json.dumps(
                {
                    "project_paths": project_paths,
                    "output_dir": output_dir,
                    "title": title,
                    "subtitle": subtitle,
                    "target_stage": target_stage,
                },
                ensure_ascii=False,
            ),
        )
        db.add(job)
        await db.flush()
        await db.refresh(job)
        job_id = job.id
        await db.commit()

    asyncio.create_task(_run_playlist_wrapper(job_id))
    return job_id


async def resume_pending_pipeline_jobs() -> None:
    """서버 재시작 시 남은 인코딩은 다시 돌리지 않고 목록에서 닫음."""
    from sqlalchemy import select

    async with async_session() as db:
        result = await db.execute(
            select(QueueJob).where(
                QueueJob.job_type.in_(("pipeline", "playlist")),
                QueueJob.status.in_(("pending", "running")),
            )
        )
        jobs = list(result.scalars().all())
        for job in jobs:
            if job.id in _active_pipeline_jobs:
                continue
            payload = {}
            try:
                payload = json.loads(job.payload_json or "{}")
            except json.JSONDecodeError:
                payload = {}
            job.status = "cancelled"
            job.message = "서버 재시작으로 인코딩이 중단되었습니다"
            job.updated_at = datetime.utcnow()
            out_dir = payload.get("output_dir")
            if out_dir:
                discard_review_work_dir(Path(out_dir))
        await db.commit()
