from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# --- Settings ---


class SettingsUpdate(BaseModel):
    openrouter_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    google_api_key: Optional[str] = None
    provider_lyrics: Optional[str] = None
    provider_prompt: Optional[str] = None
    provider_instruments: Optional[str] = None
    provider_analyze: Optional[str] = None
    model_lyrics: Optional[str] = None
    model_prompt: Optional[str] = None
    model_instruments: Optional[str] = None
    model_analyze: Optional[str] = None
    temperature_lyrics: Optional[str] = None
    temperature_prompt: Optional[str] = None
    temperature_instruments: Optional[str] = None
    temperature_analyze: Optional[str] = None
    lyrics_primary_lang: Optional[str] = None
    lyrics_second_lang: Optional[str] = None


class SettingsResponse(BaseModel):
    openrouter_api_key_set: bool
    openrouter_api_key_masked: str
    openai_api_key_set: bool
    openai_api_key_masked: str
    anthropic_api_key_set: bool
    anthropic_api_key_masked: str
    google_api_key_set: bool
    google_api_key_masked: str
    provider_lyrics: str
    provider_prompt: str
    provider_instruments: str
    provider_analyze: str
    model_lyrics: str
    model_prompt: str
    model_instruments: str
    model_analyze: str
    temperature_lyrics: str
    temperature_prompt: str
    temperature_instruments: str
    temperature_analyze: str
    lyrics_primary_lang: str
    lyrics_second_lang: str


# --- Music Profile ---


class MusicProfileBase(BaseModel):
    name: str
    description: Optional[str] = None
    genre: Optional[str] = None
    mood: Optional[str] = None
    tempo_bpm: Optional[int] = None
    key_signature: Optional[str] = None
    vocal_style: Optional[str] = None
    instruments: Optional[str] = None
    production_style: Optional[str] = None
    reference_artists: Optional[str] = None
    extra_notes: Optional[str] = None
    tags: Optional[str] = None
    emoji: Optional[str] = None


class MusicProfileCreate(MusicProfileBase):
    pass


class MusicProfileUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    genre: Optional[str] = None
    mood: Optional[str] = None
    tempo_bpm: Optional[int] = None
    key_signature: Optional[str] = None
    vocal_style: Optional[str] = None
    instruments: Optional[str] = None
    production_style: Optional[str] = None
    reference_artists: Optional[str] = None
    extra_notes: Optional[str] = None
    tags: Optional[str] = None
    emoji: Optional[str] = None


class MusicProfileResponse(MusicProfileBase):
    id: int
    last_used_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# --- Album ---


class AlbumBase(BaseModel):
    title: str
    concept: Optional[str] = None
    mood: Optional[str] = None
    target_duration_min: Optional[int] = None
    track_count: int = 10
    music_profile_id: Optional[int] = None


class AlbumCreate(AlbumBase):
    pass


class AlbumUpdate(BaseModel):
    title: Optional[str] = None
    concept: Optional[str] = None
    mood: Optional[str] = None
    target_duration_min: Optional[int] = None
    track_count: Optional[int] = None
    music_profile_id: Optional[int] = None


class AlbumResponse(AlbumBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AlbumDetailResponse(AlbumResponse):
    songs: list["SongResponse"] = []


# --- Song ---


class SongBase(BaseModel):
    track_number: int = 1
    title: str
    theme: Optional[str] = None
    mood: Optional[str] = None
    tags: Optional[str] = None


class SongCreate(SongBase):
    album_id: int
    reference_song_id: Optional[int] = None


class SongUpdate(BaseModel):
    track_number: Optional[int] = None
    title: Optional[str] = None
    title_en: Optional[str] = None
    theme: Optional[str] = None
    mood: Optional[str] = None
    tags: Optional[str] = None
    lyrics: Optional[str] = None
    lyrics_ko: Optional[str] = None
    lyrics_en: Optional[str] = None
    suno_prompt: Optional[str] = None
    instrument_settings: Optional[str] = None
    music_profile_id: Optional[int] = None


class SongResponse(SongBase):
    id: int
    album_id: int
    title_en: Optional[str] = None
    estimated_duration_sec: Optional[int] = None
    estimated_duration_label: Optional[str] = None
    estimated_duration_source: Optional[str] = None
    tempo_bpm: Optional[int] = None
    tempo_bpm_base: Optional[int] = None
    tempo_bpm_range: Optional[str] = None
    target_lyrics_lines_min: Optional[int] = None
    target_lyrics_lines_max: Optional[int] = None
    actual_lyrics_lines: Optional[int] = None
    lyrics_length_ok: Optional[bool] = None
    lyrics_length_status: Optional[str] = None
    lyrics: Optional[str] = None
    lyrics_ko: Optional[str] = None
    lyrics_en: Optional[str] = None
    suno_prompt: Optional[str] = None
    instrument_settings: Optional[str] = None
    audio_path: Optional[str] = None
    image_path: Optional[str] = None
    music_profile_id: Optional[int] = None
    reference_song_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SearchResult(BaseModel):
    type: str
    id: int
    title: str
    subtitle: Optional[str] = None
    album_id: Optional[int] = None


# --- Generation ---


class GenerateLyricsRequest(BaseModel):
    song_id: int
    additional_instructions: Optional[str] = None
    model: Optional[str] = None
    language: str = Field(default="ko", description="ko 또는 en")
    lyrics_ko: Optional[str] = Field(
        default=None,
        description="영어 번역 시 사용할 한글 가사 (화면에서 수정한 최신본)",
    )
    lyrics_en: Optional[str] = Field(
        default=None,
        description="한글 의역 시 사용할 영어 가사 (화면에서 수정한 최신본)",
    )


class GeneratePromptRequest(BaseModel):
    song_id: int
    additional_instructions: Optional[str] = None
    model: Optional[str] = None
    instrument_settings: Optional[str] = Field(
        default=None,
        description="프롬프트 생성 시 사용할 악기·믹스메모 JSON (화면 최신본)",
    )


class GenerateInstrumentsRequest(BaseModel):
    song_id: int
    additional_instructions: Optional[str] = None
    model: Optional[str] = None
    use_ai: bool = True


class SongInstrumentItem(BaseModel):
    name: str
    name_en: Optional[str] = ""
    role: str = "texture"
    tone: Optional[str] = ""
    texture: Optional[str] = ""
    notes: Optional[str] = ""
    from_preset: bool = False


class SongInstrumentSettings(BaseModel):
    preset_name: str = ""
    mix_notes: str = ""
    tempo_bpm: Optional[int] = None
    instruments: list[SongInstrumentItem] = []


class SongPresetApplyRequest(BaseModel):
    profile_id: Optional[int] = None


class GenerateABRequest(BaseModel):
    song_id: int
    task_type: str = Field(description="lyrics, prompt, or instruments")
    count: int = Field(default=2, ge=2, le=3)
    additional_instructions: Optional[str] = None


class GenerateSimilarSongRequest(BaseModel):
    reference_song_id: int
    album_id: int
    title: str
    theme: Optional[str] = None


class GenerateAlbumTracksRequest(BaseModel):
    album_id: int
    track_themes: Optional[list[str]] = None
    use_queue: bool = True


class GenerateAlbumLyricsRequest(BaseModel):
    album_id: int
    additional_instructions: Optional[str] = None
    model: Optional[str] = None


class GenerationResponse(BaseModel):
    content: str
    model_used: str
    task_type: str
    title: Optional[str] = None
    estimated_duration_sec: Optional[int] = None
    estimated_duration_label: Optional[str] = None
    estimated_duration_source: Optional[str] = None
    tempo_bpm: Optional[int] = None
    tempo_bpm_base: Optional[int] = None
    tempo_bpm_range: Optional[str] = None
    target_lyrics_lines_min: Optional[int] = None
    target_lyrics_lines_max: Optional[int] = None
    actual_lyrics_lines: Optional[int] = None
    lyrics_length_ok: Optional[bool] = None
    lyrics_length_status: Optional[str] = None


class GenerationVariantResponse(BaseModel):
    id: int
    song_id: int
    task_type: str
    variant_label: str
    content: str
    model_used: str
    created_at: datetime

    model_config = {"from_attributes": True}


class OpenRouterModel(BaseModel):
    id: str
    name: str
    description: Optional[str] = None


class PresetResponse(BaseModel):
    id: str
    name: str
    description: str
    category: Optional[str] = None
    emoji: Optional[str] = None
    tags: Optional[str] = None
    genre: Optional[str] = None
    mood: Optional[str] = None
    tempo_bpm: Optional[int] = None
    vocal_style: Optional[str] = None
    instruments: Optional[str] = None
    production_style: Optional[str] = None
    reference_artists: Optional[str] = None


# --- Prompt Builder ---


class InstrumentDetail(BaseModel):
    name: str
    name_en: Optional[str] = None
    role: Optional[str] = None
    tone: Optional[str] = None
    texture: Optional[str] = None
    notes: Optional[str] = None


class MusicalTraits(BaseModel):
    genre: Optional[str] = None
    mood: Optional[str] = None
    tempo_bpm: Optional[int] = None
    key_signature: Optional[str] = None
    vocal_style: Optional[str] = None
    production_style: Optional[str] = None
    reference_artists: Optional[str] = None
    description: Optional[str] = None


class PromptBuilderTemplateResponse(BaseModel):
    preset_id: Optional[str] = None
    profile_id: Optional[int] = None
    name: Optional[str] = None
    emoji: Optional[str] = None
    category: Optional[str] = None
    musical_traits: MusicalTraits
    instruments: list[InstrumentDetail]
    draft_prompt_english: str


class PromptBuilderGenerateRequest(BaseModel):
    preset_id: Optional[str] = None
    profile_id: Optional[int] = None
    musical_traits: Optional[MusicalTraits] = None
    instruments: Optional[list[InstrumentDetail]] = None
    user_additions: Optional[str] = None
    song_id: Optional[int] = None
    use_ai: bool = True


class PromptBuilderGenerateResponse(BaseModel):
    prompt_english: str
    draft_prompt_english: str
    model_used: Optional[str] = None


class QueueJobResponse(BaseModel):
    id: int
    job_type: str
    status: str
    progress: int
    total: int
    message: Optional[str] = None
    result_json: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# --- Favorite Track ---


class FavoriteTrackCreate(BaseModel):
    title: str
    artist: Optional[str] = None
    lyrics: Optional[str] = None
    notes: Optional[str] = None


class FavoriteTrackUpdate(BaseModel):
    title: Optional[str] = None
    artist: Optional[str] = None
    lyrics: Optional[str] = None
    notes: Optional[str] = None


class FavoriteTrackResponse(BaseModel):
    id: int
    title: str
    artist: Optional[str] = None
    lyrics: Optional[str] = None
    notes: Optional[str] = None
    audio_path: Optional[str] = None
    analysis_json: Optional[str] = None
    suno_prompt: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AnalyzeResult(BaseModel):
    analysis: dict
    suno_prompt: str


AlbumDetailResponse.model_rebuild()
