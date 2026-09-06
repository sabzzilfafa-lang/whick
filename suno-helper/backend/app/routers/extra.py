"""추가 API: 설정, 검색, A/B, 큐, 백업, 취향곡 분석, 프리셋."""

import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import (
    Album,
    FavoriteTrack,
    GenerationVariant,
    MusicProfile,
    QueueJob,
    Song,
)
from app.schemas import (
    AnalyzeResult,
    FavoriteTrackCreate,
    FavoriteTrackResponse,
    FavoriteTrackUpdate,
    GenerationVariantResponse,
    MusicProfileResponse,
    PresetResponse,
    PromptBuilderGenerateRequest,
    PromptBuilderGenerateResponse,
    PromptBuilderTemplateResponse,
    QueueJobResponse,
    SearchResult,
    SettingsResponse,
    SettingsUpdate,
)
from app.services.ai_client import AIClient
from app.services.analyze import analyze_favorite_track
from app.services.backup_service import export_backup, import_backup
from app.services.presets import get_preset, list_categories, list_presets, preset_to_profile_data
from app.services.settings_service import (
    get_ai_config,
    get_client_for_task,
    get_public_settings,
    list_provider_models,
    list_providers,
    update_settings,
)

router = APIRouter()


# --- Settings ---


@router.get("/settings", response_model=SettingsResponse)
async def get_settings(db: AsyncSession = Depends(get_db)):
    data = await get_public_settings(db)
    return SettingsResponse(**data)


@router.patch("/settings", response_model=SettingsResponse)
async def patch_settings(data: SettingsUpdate, db: AsyncSession = Depends(get_db)):
    updates = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
    result = await update_settings(db, updates)
    return SettingsResponse(**result)


@router.get("/providers")
async def get_ai_providers():
    return list_providers()


@router.get("/providers/{provider}/models")
async def get_provider_models(provider: str, db: AsyncSession = Depends(get_db)):
    if provider not in {p["id"] for p in list_providers()}:
        raise HTTPException(404, "제공업체를 찾을 수 없습니다")
    try:
        models = await list_provider_models(db, provider)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"provider": provider, "models": models}


@router.post("/settings/test-api")
async def test_api_key_legacy(db: AsyncSession = Depends(get_db)):
    """하위 호환: OpenRouter 테스트."""
    return await test_provider_api("openrouter", db)


@router.post("/settings/test-api/{provider}")
async def test_provider_api(provider: str, db: AsyncSession = Depends(get_db)):
    config = await get_ai_config(db)
    api_key = config["api_keys"].get(provider, "")
    if not api_key:
        raise HTTPException(400, f"{provider} API 키가 설정되지 않았습니다")

    client = AIClient(provider, api_key)
    try:
        result = await client.test_connection()
        models = await client.list_models()
        return {"ok": True, "provider": provider, **result, "model_count": len(models)}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, f"연결 실패: {e}")



@router.get("/search", response_model=list[SearchResult])
async def search(q: str, db: AsyncSession = Depends(get_db)):
    if not q or len(q) < 1:
        return []

    pattern = f"%{q}%"
    results: list[SearchResult] = []

    albums = await db.execute(
        select(Album).where(
            or_(Album.title.ilike(pattern), Album.concept.ilike(pattern), Album.mood.ilike(pattern))
        ).limit(20)
    )
    for a in albums.scalars():
        results.append(SearchResult(type="album", id=a.id, title=a.title, subtitle=a.mood))

    songs = await db.execute(
        select(Song).where(
            or_(
                Song.title.ilike(pattern),
                Song.lyrics.ilike(pattern),
                Song.suno_prompt.ilike(pattern),
                Song.tags.ilike(pattern),
                Song.theme.ilike(pattern),
            )
        ).limit(30)
    )
    for s in songs.scalars():
        results.append(
            SearchResult(type="song", id=s.id, title=s.title, subtitle=s.theme, album_id=s.album_id)
        )

    return results


# --- A/B Variants ---


@router.get("/songs/{song_id}/variants", response_model=list[GenerationVariantResponse])
async def list_variants(
    song_id: int, task_type: Optional[str] = None, db: AsyncSession = Depends(get_db)
):
    q = select(GenerationVariant).where(GenerationVariant.song_id == song_id)
    if task_type:
        q = q.where(GenerationVariant.task_type == task_type)
    q = q.order_by(GenerationVariant.created_at.desc()).limit(20)
    result = await db.execute(q)
    return result.scalars().all()


@router.post("/songs/{song_id}/variants/{variant_id}/apply")
async def apply_variant(song_id: int, variant_id: int, db: AsyncSession = Depends(get_db)):
    song = await db.get(Song, song_id)
    variant = await db.get(GenerationVariant, variant_id)
    if not song or not variant or variant.song_id != song_id:
        raise HTTPException(404, "찾을 수 없습니다")

    field_map = {"lyrics": "lyrics", "prompt": "suno_prompt", "instruments": "instrument_settings"}
    attr = field_map.get(variant.task_type)
    if attr:
        setattr(song, attr, variant.content)
    await db.flush()
    return {"ok": True}


from app.services.queue_service import (
    mark_stale_job_failed,
    maybe_enqueue_album_job,
    recover_stuck_job,
)
from app.services.pipeline_queue import (
    cancel_pipeline_job,
    recover_stuck_pipeline_job,
)


def _refresh_stale_job(job: QueueJob) -> bool:
    if mark_stale_job_failed(job):
        return True
    if job.job_type in ("pipeline", "playlist"):
        return recover_stuck_pipeline_job(job)
    if recover_stuck_job(job):
        maybe_enqueue_album_job(job)
        return True
    maybe_enqueue_album_job(job)
    return False


@router.get("/queue", response_model=list[QueueJobResponse])
async def list_queue(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(QueueJob).order_by(QueueJob.created_at.desc()).limit(20)
    )
    jobs = result.scalars().all()
    changed = False
    for job in jobs:
        if _refresh_stale_job(job):
            changed = True
    if changed:
        await db.flush()
    return jobs


@router.get("/queue/{job_id}", response_model=QueueJobResponse)
async def get_queue_job(job_id: int, db: AsyncSession = Depends(get_db)):
    job = await db.get(QueueJob, job_id)
    if not job:
        raise HTTPException(404, "작업을 찾을 수 없습니다")
    if _refresh_stale_job(job):
        await db.flush()
    return job


@router.post("/queue/{job_id}/cancel", response_model=QueueJobResponse)
async def cancel_queue_job(job_id: int, db: AsyncSession = Depends(get_db)):
    job = await db.get(QueueJob, job_id)
    if not job:
        raise HTTPException(404, "작업을 찾을 수 없습니다")
    if job.job_type in ("pipeline", "playlist"):
        await cancel_pipeline_job(job, db)
        return job
    if job.status in ("pending", "running"):
        job.status = "cancelled"
        job.message = "사용자가 목록에서 닫음"
        await db.flush()
    return job


# --- Presets ---


@router.get("/presets", response_model=list[PresetResponse])
async def get_presets(category: Optional[str] = None):
    from app.services.presets import list_presets_by_category

    presets = list_presets_by_category(category) if category else list_presets()
    return [PresetResponse(**p) for p in presets]


@router.get("/presets/categories")
async def get_preset_categories():
    return list_categories()


@router.post("/presets/{preset_id}/load", response_model=MusicProfileResponse)
async def load_preset(preset_id: str, db: AsyncSession = Depends(get_db)):
    """기본 프리셋을 불러와 현재 스타일로 활성화."""
    from app.services.presets import get_preset, preset_to_profile_data
    from app.services.profile_service import activate_profile

    preset = get_preset(preset_id)
    if not preset:
        raise HTTPException(404, "프리셋을 찾을 수 없습니다")

    result = await db.execute(
        select(MusicProfile).where(MusicProfile.name == preset["name"])
    )
    profile = result.scalar_one_or_none()
    if not profile:
        profile = MusicProfile(**preset_to_profile_data(preset))
        db.add(profile)
        await db.flush()
        await db.refresh(profile)

    return await activate_profile(db, profile.id)


@router.post("/presets/{preset_id}/apply", response_model=dict)
async def apply_preset(preset_id: str, db: AsyncSession = Depends(get_db)):
    """하위 호환: 프리셋 불러오기."""
    profile = await load_preset(preset_id, db)
    return {"profile_id": profile.id, "name": profile.name}


# --- Prompt Builder ---


def _profile_dict(profile: MusicProfile) -> dict:
    return {
        "id": profile.id,
        "name": profile.name,
        "description": profile.description,
        "genre": profile.genre,
        "mood": profile.mood,
        "tempo_bpm": profile.tempo_bpm,
        "key_signature": profile.key_signature,
        "vocal_style": profile.vocal_style,
        "instruments": profile.instruments,
        "production_style": profile.production_style,
        "reference_artists": profile.reference_artists,
        "extra_notes": profile.extra_notes,
        "emoji": profile.emoji,
    }


@router.get("/presets/{preset_id}/builder", response_model=PromptBuilderTemplateResponse)
async def get_preset_builder_template(preset_id: str):
    from app.services.prompt_builder import build_template_from_preset

    preset = get_preset(preset_id)
    if not preset:
        raise HTTPException(404, "프리셋을 찾을 수 없습니다")
    return PromptBuilderTemplateResponse(**build_template_from_preset(preset))


@router.get("/profiles/{profile_id}/builder", response_model=PromptBuilderTemplateResponse)
async def get_profile_builder_template(profile_id: int, db: AsyncSession = Depends(get_db)):
    from app.services.prompt_builder import build_template_from_profile

    profile = await db.get(MusicProfile, profile_id)
    if not profile:
        raise HTTPException(404, "프로필을 찾을 수 없습니다")
    return PromptBuilderTemplateResponse(**build_template_from_profile(_profile_dict(profile)))


@router.get("/prompt-builder/active", response_model=Optional[PromptBuilderTemplateResponse])
async def get_active_builder_template(db: AsyncSession = Depends(get_db)):
    from app.services.profile_service import get_active_profile
    from app.services.prompt_builder import build_template_from_profile

    profile = await get_active_profile(db)
    if not profile:
        return None
    return PromptBuilderTemplateResponse(**build_template_from_profile(_profile_dict(profile)))


@router.post("/prompt-builder/generate", response_model=PromptBuilderGenerateResponse)
async def generate_builder_prompt(
    req: PromptBuilderGenerateRequest, db: AsyncSession = Depends(get_db)
):
    from app.services.instrument_details import get_instrument_details, profile_to_musical_traits
    from app.services.prompt_builder import (
        build_draft_prompt_english,
        generate_prompt_english,
    )

    traits: dict = {}
    instruments: list[dict] = []
    song_dict = None

    if req.preset_id:
        preset = get_preset(req.preset_id)
        if not preset:
            raise HTTPException(404, "프리셋을 찾을 수 없습니다")
        traits = profile_to_musical_traits(preset)
        instruments = get_instrument_details(preset)
    elif req.profile_id:
        profile = await db.get(MusicProfile, req.profile_id)
        if not profile:
            raise HTTPException(404, "프로필을 찾을 수 없습니다")
        traits = profile_to_musical_traits(_profile_dict(profile))
        instruments = get_instrument_details({"id": "", "instruments": profile.instruments or ""})
    else:
        from app.services.profile_service import get_active_profile

        profile = await get_active_profile(db)
        if not profile:
            raise HTTPException(400, "프리셋 또는 프로필을 선택하세요")
        traits = profile_to_musical_traits(_profile_dict(profile))
        instruments = get_instrument_details({"id": "", "instruments": profile.instruments or ""})

    if req.musical_traits:
        traits.update(req.musical_traits.model_dump(exclude_none=True))
    if req.instruments:
        instruments = [i.model_dump(exclude_none=True) for i in req.instruments]

    if req.song_id:
        song = await db.get(Song, req.song_id)
        if song:
            song_dict = {"title": song.title, "theme": song.theme, "mood": song.mood}

    draft = build_draft_prompt_english(traits, instruments, req.user_additions or "")
    model_used = None
    prompt_english = draft

    if req.use_ai:
        try:
            client, model, temp, provider = await get_client_for_task(db, "prompt")
            prompt_english = await generate_prompt_english(
                client,
                traits,
                instruments,
                req.user_additions or "",
                song_dict,
                model,
                temp,
            )
            model_used = f"{provider}:{model}"
        except ValueError as e:
            raise HTTPException(400, str(e))
        except Exception as e:
            raise HTTPException(502, f"AI 생성 실패: {e}")

    return PromptBuilderGenerateResponse(
        prompt_english=prompt_english,
        draft_prompt_english=draft,
        model_used=model_used,
    )


# --- Backup ---


@router.get("/backup/export")
async def backup_export():
    path = export_backup()
    return FileResponse(
        path,
        filename=path.name,
        media_type="application/zip",
    )


@router.post("/backup/import")
async def backup_import(file: UploadFile = File(...)):
    import tempfile

    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)
    result = import_backup(tmp_path)
    tmp_path.unlink(missing_ok=True)
    return result


# --- Favorite Tracks ---


@router.get("/favorite-tracks", response_model=list[FavoriteTrackResponse])
async def list_favorite_tracks(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(FavoriteTrack).order_by(FavoriteTrack.updated_at.desc())
    )
    return result.scalars().all()


@router.post("/favorite-tracks", response_model=FavoriteTrackResponse)
async def create_favorite_track(
    data: FavoriteTrackCreate, db: AsyncSession = Depends(get_db)
):
    track = FavoriteTrack(**data.model_dump())
    db.add(track)
    await db.flush()
    await db.refresh(track)
    return track


@router.get("/favorite-tracks/{track_id}", response_model=FavoriteTrackResponse)
async def get_favorite_track(track_id: int, db: AsyncSession = Depends(get_db)):
    track = await db.get(FavoriteTrack, track_id)
    if not track:
        raise HTTPException(404, "곡을 찾을 수 없습니다")
    return track


@router.patch("/favorite-tracks/{track_id}", response_model=FavoriteTrackResponse)
async def update_favorite_track(
    track_id: int, data: FavoriteTrackUpdate, db: AsyncSession = Depends(get_db)
):
    track = await db.get(FavoriteTrack, track_id)
    if not track:
        raise HTTPException(404, "곡을 찾을 수 없습니다")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(track, k, v)
    await db.flush()
    await db.refresh(track)
    return track


@router.delete("/favorite-tracks/{track_id}")
async def delete_favorite_track(track_id: int, db: AsyncSession = Depends(get_db)):
    track = await db.get(FavoriteTrack, track_id)
    if not track:
        raise HTTPException(404, "곡을 찾을 수 없습니다")
    await db.delete(track)
    return {"ok": True}


@router.post("/favorite-tracks/{track_id}/analyze", response_model=AnalyzeResult)
async def analyze_track(track_id: int, db: AsyncSession = Depends(get_db)):
    track = await db.get(FavoriteTrack, track_id)
    if not track:
        raise HTTPException(404, "곡을 찾을 수 없습니다")

    config = await get_ai_config(db)
    client, model, temp, _ = await get_client_for_task(db, "analyze")

    try:
        analysis = await analyze_favorite_track(
            client,
            track.title,
            track.artist,
            track.lyrics,
            track.notes,
            model,
            temp,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"분석 실패: {e}")

    track.analysis_json = json.dumps(analysis, ensure_ascii=False)
    track.suno_prompt = analysis.get("suno_prompt", "")
    await db.flush()

    return AnalyzeResult(
        analysis=analysis,
        suno_prompt=analysis.get("suno_prompt", ""),
    )


@router.post("/favorite-tracks/{track_id}/create-profile")
async def create_profile_from_track(track_id: int, db: AsyncSession = Depends(get_db)):
    track = await db.get(FavoriteTrack, track_id)
    if not track or not track.analysis_json:
        raise HTTPException(400, "먼저 곡을 분석해주세요")

    analysis = json.loads(track.analysis_json)
    profile = MusicProfile(
        name=f"{track.title} 스타일",
        description=analysis.get("summary", ""),
        genre=analysis.get("genre"),
        mood=analysis.get("mood"),
        tempo_bpm=analysis.get("tempo_bpm"),
        key_signature=analysis.get("key_signature"),
        vocal_style=analysis.get("vocal_style"),
        instruments=analysis.get("instruments"),
        production_style=analysis.get("production_style"),
        extra_notes=track.suno_prompt,
    )
    db.add(profile)
    await db.flush()
    return {"profile_id": profile.id}


@router.post("/favorite-tracks/{track_id}/upload-audio")
async def upload_favorite_audio(
    track_id: int, file: UploadFile = File(...), db: AsyncSession = Depends(get_db)
):
    track = await db.get(FavoriteTrack, track_id)
    if not track:
        raise HTTPException(404, "곡을 찾을 수 없습니다")

    upload_dir = settings.data_dir / "uploads" / "favorites"
    upload_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(file.filename or "audio.mp3").suffix or ".mp3"
    filepath = upload_dir / f"fav_{track_id}{ext}"
    content = await file.read()
    with open(filepath, "wb") as f:
        f.write(content)
    track.audio_path = str(filepath)
    await db.flush()
    return {"audio_path": str(filepath)}
