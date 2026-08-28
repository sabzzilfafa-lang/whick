from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class AppSetting(Base):
    """앱 설정 (API 키, 모델, temperature 등)."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class MusicProfile(Base):
    __tablename__ = "music_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    genre: Mapped[Optional[str]] = mapped_column(String(100))
    mood: Mapped[Optional[str]] = mapped_column(String(200))
    tempo_bpm: Mapped[Optional[int]] = mapped_column(Integer)
    key_signature: Mapped[Optional[str]] = mapped_column(String(20))
    vocal_style: Mapped[Optional[str]] = mapped_column(String(200))
    instruments: Mapped[Optional[str]] = mapped_column(Text)
    production_style: Mapped[Optional[str]] = mapped_column(Text)
    reference_artists: Mapped[Optional[str]] = mapped_column(Text)
    extra_notes: Mapped[Optional[str]] = mapped_column(Text)
    tags: Mapped[Optional[str]] = mapped_column(String(300))  # 카페, 댄스, 드럼강조 등
    emoji: Mapped[Optional[str]] = mapped_column(String(10))
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    albums: Mapped[list["Album"]] = relationship(back_populates="music_profile")


class Album(Base):
    __tablename__ = "albums"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    concept: Mapped[Optional[str]] = mapped_column(Text)
    mood: Mapped[Optional[str]] = mapped_column(String(300))
    target_duration_min: Mapped[Optional[int]] = mapped_column(Integer)
    track_count: Mapped[int] = mapped_column(Integer, default=10)
    music_profile_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("music_profiles.id"), nullable=True
    )
    music_profile: Mapped[Optional["MusicProfile"]] = relationship(
        back_populates="albums"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    songs: Mapped[list["Song"]] = relationship(
        back_populates="album", cascade="all, delete-orphan"
    )


class Song(Base):
    __tablename__ = "songs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    album_id: Mapped[int] = mapped_column(ForeignKey("albums.id"), nullable=False)
    track_number: Mapped[int] = mapped_column(Integer, default=1)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    title_en: Mapped[Optional[str]] = mapped_column(String(200))
    lyrics: Mapped[Optional[str]] = mapped_column(Text)
    lyrics_ko: Mapped[Optional[str]] = mapped_column(Text)
    lyrics_en: Mapped[Optional[str]] = mapped_column(Text)
    suno_prompt: Mapped[Optional[str]] = mapped_column(Text)
    instrument_settings: Mapped[Optional[str]] = mapped_column(Text)
    theme: Mapped[Optional[str]] = mapped_column(Text)
    mood: Mapped[Optional[str]] = mapped_column(String(200))
    tags: Mapped[Optional[str]] = mapped_column(String(500))
    audio_path: Mapped[Optional[str]] = mapped_column(String(500))
    image_path: Mapped[Optional[str]] = mapped_column(String(500))
    pipeline_path: Mapped[Optional[str]] = mapped_column(String(500))
    reference_song_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("songs.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    album: Mapped["Album"] = relationship(back_populates="songs")
    reference_song: Mapped[Optional["Song"]] = relationship(
        "Song", remote_side="Song.id"
    )
    variants: Mapped[list["GenerationVariant"]] = relationship(
        back_populates="song", cascade="all, delete-orphan"
    )


class GenerationVariant(Base):
    """A/B 비교용 생성 결과."""

    __tablename__ = "generation_variants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    song_id: Mapped[int] = mapped_column(ForeignKey("songs.id"), nullable=False)
    task_type: Mapped[str] = mapped_column(String(30))
    variant_label: Mapped[str] = mapped_column(String(10))
    content: Mapped[str] = mapped_column(Text)
    model_used: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    song: Mapped["Song"] = relationship(back_populates="variants")


class FavoriteTrack(Base):
    """취향 곡 분석용."""

    __tablename__ = "favorite_tracks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    artist: Mapped[Optional[str]] = mapped_column(String(200))
    lyrics: Mapped[Optional[str]] = mapped_column(Text)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    audio_path: Mapped[Optional[str]] = mapped_column(String(500))
    analysis_json: Mapped[Optional[str]] = mapped_column(Text)
    suno_prompt: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class QueueJob(Base):
    """배치 생성 큐."""

    __tablename__ = "queue_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_type: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[Optional[str]] = mapped_column(String(300))
    payload_json: Mapped[Optional[str]] = mapped_column(Text)
    result_json: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class GenerationLog(Base):
    __tablename__ = "generation_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    song_id: Mapped[Optional[int]] = mapped_column(ForeignKey("songs.id"))
    task_type: Mapped[str] = mapped_column(String(50))
    model_used: Mapped[str] = mapped_column(String(100))
    prompt_sent: Mapped[Optional[str]] = mapped_column(Text)
    response: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
