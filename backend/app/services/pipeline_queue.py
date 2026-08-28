"""파이프라인 백그라운드 작업."""

import asyncio
import json
from datetime import datetime
from pathlib import Path

from app.database import async_session
from app.models import QueueJob, Song
from app.services.pipeline_service import run_full_pipeline
from app.services.queue_service import _update_job
from app.services.workflow_service import (
    get_pipeline_config,
    get_work_root,
    WORKFLOW_STAGES,
)


async def process_pipeline_job(job_id: int):
    await _update_job(job_id, status="running", message="파이프라인 시작...")

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
        output_dir = out_parent / f"{project_path.name}_output"
        output_dir.mkdir(parents=True, exist_ok=True)

    try:
        await _update_job(job_id, message="리마스터 및 영상 생성 중...", progress=1, total=3)
        meta = await asyncio.to_thread(run_full_pipeline, project_path, output_dir, config)

        await _update_job(job_id, message="출력 폴더 정리 중...", progress=2, total=3)
        final_dir = out_parent / project_path.name
        if final_dir.exists():
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            final_dir = out_parent / f"{project_path.name}_{stamp}"
        final_dir.mkdir(parents=True, exist_ok=True)

        video = Path(meta["video_output"])
        if video.exists():
            dest_video = final_dir / video.name
            video.replace(dest_video)
            meta["video_output"] = str(dest_video)

        for key in ("audio_remastered", "ass_path"):
            p = Path(meta.get(key, ""))
            if p.exists():
                p.replace(final_dir / p.name)

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
            progress=3,
            total=3,
            message="완료",
            result_json=json.dumps(result, ensure_ascii=False),
        )
    except Exception as e:
        await _update_job(job_id, status="failed", message=str(e)[:300])


async def enqueue_pipeline_job(project_path: str, target_stage: str = "review", song_id: int | None = None) -> int:
    async with async_session() as db:
        job = QueueJob(
            job_type="pipeline",
            status="pending",
            payload_json=json.dumps({
                "project_path": project_path,
                "target_stage": target_stage,
                "song_id": song_id,
            }),
        )
        db.add(job)
        await db.flush()
        await db.refresh(job)
        job_id = job.id
        await db.commit()

    asyncio.create_task(process_pipeline_job(job_id))
    return job_id
