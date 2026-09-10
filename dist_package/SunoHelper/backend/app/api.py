import json
from typing import Optional

from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.services.workflow_service import (
    get_work_root,
    remove_pipeline_project_if_unused,
)
from app.models import Album, GenerationLog, GenerationVariant, MusicProfile, QueueJob, Song
from app.schemas import (
    AlbumCreate,
    AlbumDetailResponse,
    AlbumResponse,
    AlbumUpdate,
    GenerateABRequest,
    GenerateAlbumLyricsRequest,
    GenerateAlbumTracksRequest,
    GenerateInstrumentsRequest,
    GenerateLyricsRequest,
    GeneratePromptRequest,
    GenerateSimilarSongRequest,
    GenerationResponse,
    GenerationVariantResponse,
    MusicProfileCreate,
    MusicProfileResponse,
    MusicProfileUpdate,
    OpenRouterModel,
    QueueJobResponse,
    SongCreate,
    SongInstrumentSettings,
    SongPresetApplyRequest,
    SongResponse,
    SongUpdate,
)
from app.services.song_lyrics import lyrics_ko_text, primary_lyrics, set_lyrics
from app.services.openrouter import (
    generate_instruments,
    generate_album_lyrics_batch,
    generate_lyrics,
    generate_lyrics_ko_with_title,
    repair_merged_album_lyrics,
    _lyrics_looks_corrupted,
    _split_corrupted_batch_lyrics,
    generate_suno_prompt,
    suggest_track_themes,
    translate_lyrics_to_english,
)
from app.services.instrument_settings_service import (
    build_from_profile,
    ensure_settings,
    serialize_settings,
)
from app.services.queue_service import enqueue_album_job, find_active_album_job
from app.services.settings_service import get_ai_config, get_client_for_task

router = APIRouter()


def _model_to_dict(obj) -> dict:
    if obj is None:
        return {}
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


async def _load_song_profile(
    db: AsyncSession, album: Album | None, song: Song | None = None
) -> MusicProfile | None:
    # 곡별 프리셋이 지정되어 있으면 앨범 프리셋보다 우선
    if song is not None and song.music_profile_id:
        profile = await db.get(MusicProfile, song.music_profile_id)
        if profile:
            return profile
    profile = None
    if album and album.music_profile_id:
        profile = await db.get(MusicProfile, album.music_profile_id)
    if not profile:
        from app.services.profile_service import get_active_profile

        profile = await get_active_profile(db)
    return profile


def _song_duration_info(
    song: Song,
    album: Album | None,
    profile: MusicProfile | None,
) -> dict:
    from app.services.suno_prompt_service import get_track_duration_info

    lyrics = primary_lyrics(song) or lyrics_ko_text(song)
    return get_track_duration_info(
        lyrics,
        _model_to_dict(profile),
        _model_to_dict(album),
        _model_to_dict(song),
    )


async def _build_song_response(
    db: AsyncSession,
    song: Song,
    album: Album | None = None,
    profile: MusicProfile | None = None,
) -> SongResponse:
    if album is None:
        album = await db.get(Album, song.album_id)
    if profile is None:
        profile = await _load_song_profile(db, album, song)
    base = SongResponse.model_validate(song)
    return base.model_copy(update=_song_duration_info(song, album, profile))


# --- Music Profiles ---


@router.get("/profiles", response_model=list[MusicProfileResponse])
async def list_profiles(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(MusicProfile).order_by(
            MusicProfile.last_used_at.desc().nullslast(),
            MusicProfile.updated_at.desc(),
        )
    )
    return result.scalars().all()


@router.get("/profiles/active", response_model=Optional[MusicProfileResponse])
async def get_active_profile_endpoint(db: AsyncSession = Depends(get_db)):
    from app.services.profile_service import get_active_profile

    return await get_active_profile(db)


@router.post("/profiles/{profile_id}/activate", response_model=MusicProfileResponse)
async def activate_profile_endpoint(profile_id: int, db: AsyncSession = Depends(get_db)):
    from app.services.profile_service import activate_profile

    try:
        return await activate_profile(db, profile_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/profiles/{profile_id}/duplicate", response_model=MusicProfileResponse)
async def duplicate_profile_endpoint(profile_id: int, db: AsyncSession = Depends(get_db)):
    from app.services.profile_service import duplicate_profile

    try:
        return await duplicate_profile(db, profile_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/profiles/{profile_id}/apply-to-album/{album_id}")
async def apply_profile_to_album(
    profile_id: int, album_id: int, db: AsyncSession = Depends(get_db)
):
    from app.services.profile_service import activate_profile

    album = await db.get(Album, album_id)
    if not album:
        raise HTTPException(404, "앨범을 찾을 수 없습니다")
    profile = await activate_profile(db, profile_id)
    album.music_profile_id = profile_id
    await db.flush()
    return {"ok": True, "profile": profile, "album_id": album_id}


@router.post("/profiles", response_model=MusicProfileResponse)
async def create_profile(data: MusicProfileCreate, db: AsyncSession = Depends(get_db)):
    from app.services.profile_service import activate_profile

    profile = MusicProfile(**data.model_dump())
    db.add(profile)
    await db.flush()
    await db.refresh(profile)
    return await activate_profile(db, profile.id)


@router.get("/profiles/{profile_id}", response_model=MusicProfileResponse)
async def get_profile(profile_id: int, db: AsyncSession = Depends(get_db)):
    profile = await db.get(MusicProfile, profile_id)
    if not profile:
        raise HTTPException(404, "프로필을 찾을 수 없습니다")
    return profile


@router.patch("/profiles/{profile_id}", response_model=MusicProfileResponse)
async def update_profile(
    profile_id: int, data: MusicProfileUpdate, db: AsyncSession = Depends(get_db)
):
    profile = await db.get(MusicProfile, profile_id)
    if not profile:
        raise HTTPException(404, "프로필을 찾을 수 없습니다")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(profile, key, value)
    await db.flush()
    await db.refresh(profile)
    return profile


@router.delete("/profiles/{profile_id}")
async def delete_profile(profile_id: int, db: AsyncSession = Depends(get_db)):
    profile = await db.get(MusicProfile, profile_id)
    if not profile:
        raise HTTPException(404, "프로필을 찾을 수 없습니다")
    await db.delete(profile)
    return {"ok": True}


# --- Albums ---


@router.get("/albums", response_model=list[AlbumResponse])
async def list_albums(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Album).order_by(Album.updated_at.desc()))
    return result.scalars().all()


@router.post("/albums", response_model=AlbumResponse)
async def create_album(data: AlbumCreate, db: AsyncSession = Depends(get_db)):
    album = Album(**data.model_dump())
    db.add(album)
    await db.flush()
    await db.refresh(album)
    try:
        from app.services.workflow_service import ensure_album_work_folder

        root = await get_work_root(db)
        ensure_album_work_folder(root, album, "music")
    except Exception:
        pass
    return album


@router.get("/albums/{album_id}", response_model=AlbumDetailResponse)
async def get_album(album_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Album)
        .options(selectinload(Album.songs))
        .where(Album.id == album_id)
    )
    album = result.scalar_one_or_none()
    if not album:
        raise HTTPException(404, "앨범을 찾을 수 없습니다")
    album.songs.sort(key=lambda s: s.track_number)
    return album


@router.patch("/albums/{album_id}", response_model=AlbumResponse)
async def update_album(
    album_id: int, data: AlbumUpdate, db: AsyncSession = Depends(get_db)
):
    album = await db.get(Album, album_id)
    if not album:
        raise HTTPException(404, "앨범을 찾을 수 없습니다")
    old_title = album.title
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(album, key, value)
    await db.flush()
    await db.refresh(album)
    # 제목 변경 시 작업폴더 앨범 디렉터리 이름도 맞춤
    if album.title != old_title:
        try:
            from app.services.pipeline_defaults import WORKFLOW_STAGES
            from app.services.workflow_service import album_pipeline_folder_name

            root = await get_work_root(db)
            old_name = album_pipeline_folder_name({"title": old_title})
            new_name = album_pipeline_folder_name(album)
            for stage in WORKFLOW_STAGES:
                old_dir = root / stage["folder"] / old_name
                new_dir = root / stage["folder"] / new_name
                if old_dir.is_dir() and not new_dir.exists():
                    old_dir.rename(new_dir)
        except Exception:
            pass
    return album


@router.delete("/albums/{album_id}")
async def delete_album(album_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Album).options(selectinload(Album.songs)).where(Album.id == album_id)
    )
    album = result.scalar_one_or_none()
    if not album:
        raise HTTPException(404, "앨범을 찾을 수 없습니다")
    root = await get_work_root(db)
    song_ids = {s.id for s in album.songs}
    seen_paths: set[str] = set()
    for song in album.songs:
        if not song.pipeline_path or song.pipeline_path in seen_paths:
            continue
        seen_paths.add(song.pipeline_path)
        await remove_pipeline_project_if_unused(db, root, song.pipeline_path, song_ids)
    await db.delete(album)
    return {"ok": True}


# --- Songs ---


@router.post("/songs", response_model=SongResponse)
async def create_song(data: SongCreate, db: AsyncSession = Depends(get_db)):
    album = await db.get(Album, data.album_id)
    if not album:
        raise HTTPException(404, "앨범을 찾을 수 없습니다")
    song = Song(**data.model_dump())
    db.add(song)
    await db.flush()
    await db.refresh(song)
    return song


@router.get("/songs/{song_id}", response_model=SongResponse)
async def get_song(song_id: int, db: AsyncSession = Depends(get_db)):
    song = await db.get(Song, song_id)
    if not song:
        raise HTTPException(404, "곡을 찾을 수 없습니다")
    return await _build_song_response(db, song)


@router.patch("/songs/{song_id}", response_model=SongResponse)
async def update_song(
    song_id: int, data: SongUpdate, db: AsyncSession = Depends(get_db)
):
    song = await db.get(Song, song_id)
    if not song:
        raise HTTPException(404, "곡을 찾을 수 없습니다")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(song, key, value)
    if "lyrics_ko" in data.model_dump(exclude_unset=True):
        song.lyrics = song.lyrics_ko
    await db.flush()
    await db.refresh(song)
    return await _build_song_response(db, song)


@router.delete("/songs/{song_id}")
async def delete_song(song_id: int, db: AsyncSession = Depends(get_db)):
    song = await db.get(Song, song_id)
    if not song:
        raise HTTPException(404, "곡을 찾을 수 없습니다")
    root = await get_work_root(db)
    await remove_pipeline_project_if_unused(db, root, song.pipeline_path, {song_id})
    await db.delete(song)
    return {"ok": True}


@router.post("/songs/{song_id}/upload-audio")
async def upload_audio(
    song_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    song = await db.get(Song, song_id)
    if not song:
        raise HTTPException(404, "곡을 찾을 수 없습니다")

    import os
    from pathlib import Path

    from app.config import settings

    upload_dir = settings.data_dir / "uploads" / str(song.album_id)
    upload_dir.mkdir(parents=True, exist_ok=True)

    ext = Path(file.filename or "audio.mp3").suffix or ".mp3"
    filename = f"track_{song.track_number:02d}_{song_id}{ext}"
    filepath = upload_dir / filename

    content = await file.read()
    with open(filepath, "wb") as f:
        f.write(content)

    song.audio_path = str(filepath)
    await db.flush()
    return {"audio_path": str(filepath), "filename": filename}


@router.post("/songs/{song_id}/upload-image")
async def upload_image(
    song_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    song = await db.get(Song, song_id)
    if not song:
        raise HTTPException(404, "곡을 찾을 수 없습니다")

    from app.config import settings

    upload_dir = settings.data_dir / "uploads" / str(song.album_id)
    upload_dir.mkdir(parents=True, exist_ok=True)

    ext = Path(file.filename or "cover.jpg").suffix.lower()
    if ext not in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
        ext = ".jpg"
    filename = f"cover_{song.track_number:02d}_{song_id}{ext}"
    filepath = upload_dir / filename

    content = await file.read()
    with open(filepath, "wb") as f:
        f.write(content)

    song.image_path = str(filepath)
    await db.flush()
    return {"image_path": str(filepath), "filename": filename}


@router.get("/songs/{song_id}/cover-image")
async def song_cover_image(song_id: int, db: AsyncSession = Depends(get_db)):
    from app.config import settings

    song = await db.get(Song, song_id)
    if not song or not song.image_path:
        raise HTTPException(404, "커버 이미지가 없습니다")
    filepath = Path(song.image_path).resolve()
    uploads_root = (settings.data_dir / "uploads").resolve()
    if not str(filepath).startswith(str(uploads_root)):
        raise HTTPException(403, "접근 거부")
    if not filepath.is_file():
        raise HTTPException(404, "파일을 찾을 수 없습니다")
    # 재생성 시 즉시 새 이미지가 보이도록 캐시 금지 (2026-09-10 v0.9.48)
    return FileResponse(filepath, headers={"Cache-Control": "no-store"})


# --- AI Generation ---


async def _load_song_context(db: AsyncSession, song_id: int):
    song = await db.get(Song, song_id)
    if not song:
        raise HTTPException(404, "곡을 찾을 수 없습니다")

    album = await db.get(Album, song.album_id)
    profile = await _load_song_profile(db, album, song)

    reference_song = None
    if song.reference_song_id:
        reference_song = await db.get(Song, song.reference_song_id)

    return song, album, profile, reference_song


@router.post("/generate/lyrics", response_model=GenerationResponse)
async def api_generate_lyrics(
    req: GenerateLyricsRequest, db: AsyncSession = Depends(get_db)
):
    song, album, profile, ref = await _load_song_context(db, req.song_id)
    client, model, temp, provider = await get_client_for_task(db, "lyrics")
    model = req.model or model

    lang = req.language if req.language in ("ko", "en") else "ko"

    try:
        generated_title: Optional[str] = None
        if lang == "ko" and (req.lyrics_en or "").strip():
            # 영어 → 한국어 의역 (v0.9.52 — 설정 언어와 무관하게 양방향 의역)
            from app.services.openrouter import translate_lyrics_between

            en = req.lyrics_en.strip()
            if not (song.lyrics_en or "").strip():
                song.lyrics_en = en
            ko_title, content = await translate_lyrics_between(
                client,
                en,
                direction="en2ko",
                song=_model_to_dict(song),
                additional=req.additional_instructions,
                model=model,
                temperature=temp,
            )
            if ko_title:
                song.title = ko_title[:200]
                generated_title = ko_title
                song.title = ko_title[:200]
                generated_title = ko_title
        elif lang == "en":
            ko = (req.lyrics_ko or "").strip() or (lyrics_ko_text(song) or "").strip()
            if req.lyrics_ko and req.lyrics_ko.strip():
                song.lyrics_ko = req.lyrics_ko.strip()
                song.lyrics = song.lyrics_ko
            if ko:
                english_title, content = await translate_lyrics_to_english(
                    client,
                    ko,
                    _model_to_dict(song),
                    req.additional_instructions,
                    model,
                    temp,
                )
                if english_title:
                    song.title_en = english_title[:200]
                    generated_title = english_title
            else:
                content = await generate_lyrics(
                    client,
                    _model_to_dict(profile),
                    _model_to_dict(album),
                    _model_to_dict(song),
                    _model_to_dict(ref) if ref else None,
                    req.additional_instructions,
                    model,
                    temp,
                    language="en",
                )
        else:
            generated_title, content = await generate_lyrics_ko_with_title(
                client,
                _model_to_dict(profile),
                _model_to_dict(album),
                _model_to_dict(song),
                _model_to_dict(ref) if ref else None,
                req.additional_instructions,
                model,
                temp,
            )
            if generated_title:
                song.title = generated_title[:200]
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"AI 생성 실패: {e}")

    model_label = f"{provider}:{model}"
    set_lyrics(song, content, lang)
    duration_info = _song_duration_info(song, album, profile)
    db.add(
        GenerationLog(
            song_id=song.id,
            task_type="lyrics",
            model_used=model_label,
            response=content,
        )
    )
    await db.flush()

    return GenerationResponse(
        content=content,
        model_used=model_label,
        task_type="lyrics",
        title=generated_title,
        **duration_info,
    )


@router.post("/generate/prompt", response_model=GenerationResponse)
async def api_generate_prompt(
    req: GeneratePromptRequest, db: AsyncSession = Depends(get_db)
):
    song, album, profile, ref = await _load_song_context(db, req.song_id)
    client, model, temp, provider = await get_client_for_task(db, "prompt")
    model = req.model or model

    try:
        from app.services.instrument_settings_service import (
            ensure_settings,
            serialize_settings,
        )
        from app.services.suno_prompt_service import resolve_track_bpm

        profile_dict = _model_to_dict(profile)
        song_dict = _model_to_dict(song)
        lyrics = primary_lyrics(song)
        inst_settings = req.instrument_settings or song.instrument_settings
        data = ensure_settings(inst_settings, profile_dict)
        if data.get("tempo_bpm") is None:
            data["tempo_bpm"] = resolve_track_bpm(
                profile_dict, song_dict, lyrics, None
            )
        inst_settings = serialize_settings(data)
        song.instrument_settings = inst_settings
        content = await generate_suno_prompt(
            client,
            profile_dict,
            _model_to_dict(album),
            song_dict,
            lyrics,
            _model_to_dict(ref) if ref else None,
            req.additional_instructions,
            model,
            temp,
            instrument_settings=inst_settings,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"AI 생성 실패: {e}")

    model_label = f"{provider}:{model}"
    song.suno_prompt = content
    duration_info = _song_duration_info(song, album, profile)
    db.add(
        GenerationLog(
            song_id=song.id,
            task_type="prompt",
            model_used=model_label,
            response=content,
        )
    )
    await db.flush()

    return GenerationResponse(
        content=content,
        model_used=model_label,
        task_type="prompt",
        **duration_info,
    )


@router.get("/songs/{song_id}/instruments/preset", response_model=SongInstrumentSettings)
async def get_song_instruments_preset(song_id: int, db: AsyncSession = Depends(get_db)):
    """앨범에 연결된 스타일 프리셋의 기본 악기 목록."""
    _, _, profile, _ = await _load_song_context(db, song_id)
    data = build_from_profile(_model_to_dict(profile))
    return SongInstrumentSettings(**data)


@router.post("/songs/{song_id}/instruments/from-preset", response_model=SongInstrumentSettings)
async def apply_song_instruments_from_preset(
    song_id: int, db: AsyncSession = Depends(get_db)
):
    """프리셋 기본 악기를 곡에 적용 (저장)."""
    song, _, profile, _ = await _load_song_context(db, song_id)
    data = build_from_profile(_model_to_dict(profile))
    content = serialize_settings(data)
    song.instrument_settings = content
    await db.flush()
    return SongInstrumentSettings(**data)


@router.post("/songs/{song_id}/apply-preset", response_model=SongInstrumentSettings)
async def apply_preset_to_song(
    song_id: int, body: SongPresetApplyRequest, db: AsyncSession = Depends(get_db)
):
    """곡에 스타일 프리셋을 지정하고, 그 프리셋의 기본 악기로 곡 악기 세팅을 다시 만든다."""
    song = await db.get(Song, song_id)
    if not song:
        raise HTTPException(404, "곡을 찾을 수 없습니다")

    if body.profile_id is not None:
        profile = await db.get(MusicProfile, body.profile_id)
        if not profile:
            raise HTTPException(404, "프리셋을 찾을 수 없습니다")
        song.music_profile_id = body.profile_id
    else:
        # 프리셋 해제 → 앨범 프리셋 기준으로 복귀
        song.music_profile_id = None

    await db.flush()
    album = await db.get(Album, song.album_id)
    profile = await _load_song_profile(db, album, song)

    data = build_from_profile(_model_to_dict(profile))
    song.instrument_settings = serialize_settings(data)
    await db.flush()
    return SongInstrumentSettings(**data)


@router.put("/songs/{song_id}/instruments", response_model=SongInstrumentSettings)
async def update_song_instruments(
    body: SongInstrumentSettings, song_id: int, db: AsyncSession = Depends(get_db)
):
    """곡 악기 목록 수동 저장."""
    song = await db.get(Song, song_id)
    if not song:
        raise HTTPException(404, "곡을 찾을 수 없습니다")
    data = body.model_dump()
    content = serialize_settings(data)
    song.instrument_settings = content
    await db.flush()
    return body


@router.post("/generate/instruments", response_model=GenerationResponse)
async def api_generate_instruments(
    req: GenerateInstrumentsRequest, db: AsyncSession = Depends(get_db)
):
    song, album, profile, _ = await _load_song_context(db, req.song_id)
    profile_dict = _model_to_dict(profile)

    if not req.use_ai:
        data = ensure_settings(song.instrument_settings, profile_dict)
        content = serialize_settings(data)
        song.instrument_settings = content
        await db.flush()
        return GenerationResponse(
            content=content, model_used="preset", task_type="instruments"
        )

    client, model, temp, provider = await get_client_for_task(db, "instruments")
    model = req.model or model
    base = ensure_settings(song.instrument_settings, profile_dict)

    try:
        content = await generate_instruments(
            client,
            profile_dict,
            _model_to_dict(album),
            _model_to_dict(song),
            lyrics=primary_lyrics(song),
            suno_prompt=song.suno_prompt,
            additional=req.additional_instructions,
            model=model,
            temperature=temp,
            base_instruments=serialize_settings(base),
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"AI 생성 실패: {e}")

    model_label = f"{provider}:{model}"
    song.instrument_settings = content
    db.add(
        GenerationLog(
            song_id=song.id,
            task_type="instruments",
            model_used=model_label,
            response=content,
        )
    )
    await db.flush()

    return GenerationResponse(content=content, model_used=model_label, task_type="instruments")


@router.post("/generate/ab", response_model=list[GenerationVariantResponse])
async def generate_ab_variants(
    req: GenerateABRequest, db: AsyncSession = Depends(get_db)
):
    """A/B 비교용 여러 변형 생성."""
    song, album, profile, ref = await _load_song_context(db, req.song_id)
    task = req.task_type if req.task_type in ("lyrics", "prompt", "instruments") else "lyrics"
    client, model, temp, provider = await get_client_for_task(db, task)
    labels = ["A", "B", "C"][: req.count]
    variants = []

    for label in labels:
        try:
            if task == "lyrics":
                title, content = await generate_lyrics_ko_with_title(
                    client,
                    _model_to_dict(profile),
                    _model_to_dict(album),
                    _model_to_dict(song),
                    _model_to_dict(ref) if ref else None,
                    req.additional_instructions,
                    model,
                    temp + 0.1 * labels.index(label),
                )
            elif task == "prompt":
                content = await generate_suno_prompt(
                    client,
                    _model_to_dict(profile),
                    _model_to_dict(album),
                    _model_to_dict(song),
                    primary_lyrics(song),
                    _model_to_dict(ref) if ref else None,
                    req.additional_instructions,
                    model,
                    temp + 0.1 * labels.index(label),
                    instrument_settings=song.instrument_settings,
                )
            else:
                content = await generate_instruments(
                    client,
                    _model_to_dict(profile),
                    _model_to_dict(album),
                    _model_to_dict(song),
                    lyrics=primary_lyrics(song),
                    suno_prompt=song.suno_prompt,
                    additional=req.additional_instructions,
                    model=model,
                    temperature=temp + 0.1 * labels.index(label),
                )

            model_label = f"{provider}:{model}"
            variant = GenerationVariant(
                song_id=song.id,
                task_type=req.task_type,
                variant_label=label,
                content=content,
                model_used=model_label,
            )
            db.add(variant)
            await db.flush()
            await db.refresh(variant)
            variants.append(variant)
        except Exception:
            continue

    if not variants:
        raise HTTPException(502, "변형 생성 실패")
    return variants


@router.post("/generate/similar", response_model=SongResponse)
async def generate_similar_song(
    req: GenerateSimilarSongRequest, db: AsyncSession = Depends(get_db)
):
    """참조 곡과 같은 분위기의 새 곡 생성 (가사+프롬프트+악기 일괄)."""
    ref_song = await db.get(Song, req.reference_song_id)
    if not ref_song:
        raise HTTPException(404, "참조 곡을 찾을 수 없습니다")

    album = await db.get(Album, req.album_id)
    if not album:
        raise HTTPException(404, "앨범을 찾을 수 없습니다")

    profile = None
    if album.music_profile_id:
        profile = await db.get(MusicProfile, album.music_profile_id)

    # 트랙 번호 자동 할당
    result = await db.execute(
        select(Song.track_number)
        .where(Song.album_id == req.album_id)
        .order_by(Song.track_number.desc())
        .limit(1)
    )
    max_track = result.scalar() or 0

    new_song = Song(
        album_id=req.album_id,
        track_number=max_track + 1,
        title=req.title,
        theme=req.theme,
        mood=ref_song.mood,
        reference_song_id=req.reference_song_id,
    )
    db.add(new_song)
    await db.flush()

    ref_dict = _model_to_dict(ref_song)
    album_dict = _model_to_dict(album)
    profile_dict = _model_to_dict(profile)
    song_dict = _model_to_dict(new_song)

    try:
        lyrics_client, lyrics_model, lyrics_temp, lyrics_provider = await get_client_for_task(db, "lyrics")
        lyrics = await generate_lyrics(
            lyrics_client, profile_dict, album_dict, song_dict, ref_dict,
            model=lyrics_model, temperature=lyrics_temp,
        )
        set_lyrics(new_song, lyrics, "ko")
        inst_client, inst_model, inst_temp, inst_provider = await get_client_for_task(db, "instruments")
        instruments = await generate_instruments(
            inst_client, profile_dict, album_dict, song_dict, lyrics=lyrics, model=inst_model, temperature=inst_temp,
        )
        new_song.instrument_settings = instruments
        prompt_client, prompt_model, prompt_temp, prompt_provider = await get_client_for_task(db, "prompt")
        prompt = await generate_suno_prompt(
            prompt_client, profile_dict, album_dict, song_dict, lyrics, ref_dict,
            model=prompt_model, temperature=prompt_temp, instrument_settings=instruments,
        )
        new_song.suno_prompt = prompt
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"AI 생성 실패: {e}")

    await db.flush()
    await db.refresh(new_song)
    return new_song


@router.post("/generate/album-tracks", response_model=QueueJobResponse)
async def generate_album_tracks(
    req: GenerateAlbumTracksRequest,
    db: AsyncSession = Depends(get_db),
):
    """앨범 전체 트랙 일괄 생성 (큐)."""
    album = await db.get(Album, req.album_id)
    if not album:
        raise HTTPException(404, "앨범을 찾을 수 없습니다")

    if req.use_queue:
        active = await find_active_album_job(db, req.album_id)
        if active:
            maybe_enqueue = active.status == "pending"
            if maybe_enqueue:
                enqueue_album_job(active.id)
            return active

        job = QueueJob(
            job_type="album_tracks",
            status="pending",
            total=album.track_count,
            payload_json=json.dumps({
                "album_id": req.album_id,
                "track_themes": req.track_themes,
            }),
            message="대기 중...",
        )
        db.add(job)
        await db.flush()
        await db.refresh(job)
        enqueue_album_job(job.id)
        return job

    lyrics_client, lyrics_model, lyrics_temp, _ = await get_client_for_task(db, "lyrics")

    profile = None
    if album.music_profile_id:
        profile = await db.get(MusicProfile, album.music_profile_id)

    themes = req.track_themes
    if not themes:
        themes = await suggest_track_themes(
            lyrics_client,
            _model_to_dict(album),
            _model_to_dict(profile),
            album.track_count,
            model=lyrics_model,
            temperature=lyrics_temp,
        )

    if len(themes) < album.track_count:
        themes.extend([f"Track {i+1}" for i in range(len(themes), album.track_count)])

    created = 0
    for i, theme in enumerate(themes[: album.track_count]):
        song = Song(
            album_id=album.id,
            track_number=i + 1,
            title=f"Track {i + 1}",
            theme=theme,
            mood=album.mood,
        )
        db.add(song)
        created += 1

    job = QueueJob(
        job_type="album_tracks",
        status="completed",
        progress=created,
        total=album.track_count,
        message=f"{created}곡 등록 완료",
    )
    db.add(job)
    await db.flush()
    await db.refresh(job)
    return job


@router.post("/generate/album-lyrics")
async def generate_album_lyrics(
    req: GenerateAlbumLyricsRequest,
    db: AsyncSession = Depends(get_db),
):
    """앨범 전체 한글 가사를 한 번의 API 호출로 생성 (ChatGPT 방식)."""
    result = await db.execute(
        select(Album).options(selectinload(Album.songs)).where(Album.id == req.album_id)
    )
    album = result.scalar_one_or_none()
    if not album:
        raise HTTPException(404, "앨범을 찾을 수 없습니다")
    if not album.songs:
        raise HTTPException(400, "먼저 트랙 목록을 등록하세요")

    profile = None
    if album.music_profile_id:
        profile = await db.get(MusicProfile, album.music_profile_id)

    client, model, temp, provider = await get_client_for_task(db, "lyrics")
    model = req.model or model

    try:
        batch = await generate_album_lyrics_batch(
            client,
            _model_to_dict(profile),
            _model_to_dict(album),
            [_model_to_dict(s) for s in album.songs],
            req.additional_instructions,
            model,
            temp,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"AI 생성 실패: {e}")

    by_track: dict[int, dict] = {}
    for item in batch:
        lyrics = str(item.get("lyrics") or "").strip()
        if not lyrics:
            continue
        if _lyrics_looks_corrupted(lyrics):
            for recovered in _split_corrupted_batch_lyrics(lyrics):
                by_track[recovered["track_number"]] = recovered
        else:
            by_track[int(item["track_number"])] = item

    updated = 0
    for song in album.songs:
        item = by_track.get(song.track_number)
        if not item:
            continue
        if item.get("title"):
            song.title = str(item["title"])[:200]
        set_lyrics(song, item["lyrics"], "ko")
        updated += 1

    await db.flush()
    return {
        "updated": updated,
        "total": len(album.songs),
        "model_used": f"{provider}:{model}",
    }


@router.post("/generate/repair-album-lyrics")
async def repair_album_lyrics(
    req: GenerateAlbumLyricsRequest,
    db: AsyncSession = Depends(get_db),
):
    """첫 곡에 합쳐진 가사를 트랙별로 분리해 저장."""
    result = await db.execute(
        select(Album).options(selectinload(Album.songs)).where(Album.id == req.album_id)
    )
    album = result.scalar_one_or_none()
    if not album:
        raise HTTPException(404, "앨범을 찾을 수 없습니다")
    if not album.songs:
        raise HTTPException(400, "트랙이 없습니다")

    song_payload = [
        {
            "track_number": s.track_number,
            "lyrics_ko": lyrics_ko_text(s),
        }
        for s in album.songs
    ]
    recovered = repair_merged_album_lyrics(song_payload)
    if not recovered:
        raise HTTPException(400, "합쳐진 가사를 찾지 못했습니다")

    by_track = {item["track_number"]: item for item in recovered}
    updated = 0
    for song in album.songs:
        item = by_track.get(song.track_number)
        if not item:
            continue
        if item.get("title"):
            song.title = str(item["title"])[:200]
        set_lyrics(song, item["lyrics"], "ko")
        updated += 1

    await db.flush()
    return {"updated": updated, "total": len(album.songs), "recovered_tracks": len(recovered)}


# --- OpenRouter Models ---


@router.get("/models", response_model=list[OpenRouterModel])
async def list_openrouter_models(provider: str = "openrouter", db: AsyncSession = Depends(get_db)):
    from app.services.settings_service import list_provider_models

    if provider not in PROVIDER_INFO:
        raise HTTPException(404, "제공업체를 찾을 수 없습니다")
    try:
        models = await list_provider_models(db, provider)
        return [
            OpenRouterModel(id=m["id"], name=m["name"], description=None)
            for m in models
        ]
    except ValueError as e:
        raise HTTPException(400, str(e))
