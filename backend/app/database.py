from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.models import Base

engine = create_async_engine(
    settings.database_url,
    echo=False,
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _run_migrations(conn):
    """기존 DB에 새 컬럼 추가."""
    result = await conn.execute(text("PRAGMA table_info(songs)"))
    columns = {row[1] for row in result.fetchall()}
    if "tags" not in columns:
        await conn.execute(text("ALTER TABLE songs ADD COLUMN tags VARCHAR(500)"))

    result = await conn.execute(text("PRAGMA table_info(music_profiles)"))
    profile_cols = {row[1] for row in result.fetchall()}
    if "tags" not in profile_cols:
        await conn.execute(text("ALTER TABLE music_profiles ADD COLUMN tags VARCHAR(300)"))
    if "emoji" not in profile_cols:
        await conn.execute(text("ALTER TABLE music_profiles ADD COLUMN emoji VARCHAR(10)"))
    if "last_used_at" not in profile_cols:
        await conn.execute(text("ALTER TABLE music_profiles ADD COLUMN last_used_at DATETIME"))

    result = await conn.execute(text("PRAGMA table_info(songs)"))
    song_cols = {row[1] for row in result.fetchall()}
    if "lyrics_ko" not in song_cols:
        await conn.execute(text("ALTER TABLE songs ADD COLUMN lyrics_ko TEXT"))
    if "lyrics_en" not in song_cols:
        await conn.execute(text("ALTER TABLE songs ADD COLUMN lyrics_en TEXT"))
    if "pipeline_path" not in song_cols:
        await conn.execute(text("ALTER TABLE songs ADD COLUMN pipeline_path VARCHAR(500)"))
    if "image_path" not in song_cols:
        await conn.execute(text("ALTER TABLE songs ADD COLUMN image_path VARCHAR(500)"))
    if "title_en" not in song_cols:
        await conn.execute(text("ALTER TABLE songs ADD COLUMN title_en VARCHAR(200)"))
    await conn.execute(
        text(
            "UPDATE songs SET lyrics_ko = lyrics "
            "WHERE (lyrics_ko IS NULL OR lyrics_ko = '') AND lyrics IS NOT NULL AND lyrics != ''"
        )
    )


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _run_migrations(conn)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
