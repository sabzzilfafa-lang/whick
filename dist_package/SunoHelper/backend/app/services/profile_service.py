"""스타일 프리셋 활성화/관리."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppSetting, MusicProfile

ACTIVE_PROFILE_KEY = "active_profile_id"


async def _set_active_id(db: AsyncSession, profile_id: int) -> None:
    result = await db.execute(
        select(AppSetting).where(AppSetting.key == ACTIVE_PROFILE_KEY)
    )
    row = result.scalar_one_or_none()
    if row:
        row.value = str(profile_id)
    else:
        db.add(AppSetting(key=ACTIVE_PROFILE_KEY, value=str(profile_id)))
    await db.flush()


async def activate_profile(db: AsyncSession, profile_id: int) -> MusicProfile:
    profile = await db.get(MusicProfile, profile_id)
    if not profile:
        raise ValueError("프리셋을 찾을 수 없습니다")
    profile.last_used_at = datetime.utcnow()
    await _set_active_id(db, profile_id)
    await db.flush()
    await db.refresh(profile)
    return profile


async def get_active_profile(db: AsyncSession) -> MusicProfile | None:
    result = await db.execute(
        select(AppSetting).where(AppSetting.key == ACTIVE_PROFILE_KEY)
    )
    row = result.scalar_one_or_none()
    if not row or not row.value:
        return None
    try:
        profile_id = int(row.value)
    except ValueError:
        return None
    return await db.get(MusicProfile, profile_id)


async def duplicate_profile(db: AsyncSession, profile_id: int) -> MusicProfile:
    source = await db.get(MusicProfile, profile_id)
    if not source:
        raise ValueError("프리셋을 찾을 수 없습니다")

    data = {
        c.name: getattr(source, c.name)
        for c in source.__table__.columns
        if c.name not in ("id", "created_at", "updated_at", "last_used_at")
    }
    data["name"] = f"{source.name} (복사)"
    new_profile = MusicProfile(**data)
    db.add(new_profile)
    await db.flush()
    await db.refresh(new_profile)
    return new_profile
