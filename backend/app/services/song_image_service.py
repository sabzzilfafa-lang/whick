"""곡별 재생 배경 이미지 AI 생성 (2026-09-10).

앨범 썸네일(thumbnail_ai_service)과 같은 방식 — 곡 제목·테마·분위기로
프롬프트를 만들어 이미지 생성 AI로 배경 이미지를 만들고 곡 image_path에 저장.
UI에서 재생 배경(커버 이미지)으로 사용된다.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.settings_service import get_all_settings, PROVIDER_INFO
from app.services.thumbnail_ai_service import (
    IMAGE_PROVIDERS,
    _ai_text,
    _extract_json,
    _crop_to_thumb,
    _gen_image_google,
    _gen_image_openai,
    _gen_image_openrouter,
)

logger = logging.getLogger(__name__)


def _song_prompt_request(title: str, theme: str, mood: str, tags: str) -> tuple[str, str]:
    """곡 1개의 배경 이미지 프롬프트 생성 요청 (재생 화면 배경용 — 글자 없음).

    기준은 곡 제목 + 트랙별 분위기(theme, 예: "차가운 늦가을 아침, 문을 연 카페에
    첫 햇살과 갓 내린 커피 향이 천천히 번지는 순간") — 이 장면을 그대로 그린다 (2026-09-10).
    """
    system = (
        "You are a music visualizer / streaming-background art director. "
        "Reply with ONLY a JSON array with EXACTLY 1 string — one image-generation "
        "prompt for a single song's PLAYING BACKGROUND image (16:9 landscape). "
        "PRIMARY SOURCE: the song title and its SCENE DESCRIPTION (Theme) — the image "
        "must literally depict that described moment (place, time, action, sensory "
        "details). Translate the scene faithfully; do NOT invent unrelated imagery. "
        "Mood/genre tags only refine lighting and palette. "
        "Keep it CONCISE: 2-3 sentences, under 120 words total — the response must "
        "not be truncated. "
        "ABSOLUTELY NO text, letters, words, captions, watermarks or logos in the "
        "image (it plays behind other UI). Do not draw any typography."
    )
    user = (
        f"Song title: {title}\n"
        f"Scene description (depict THIS): {theme or 'unspecified'}\n"
        f"Mood: {mood or 'unspecified'}\n"
        f"Tags/genre: {tags or 'unspecified'}\n"
        'Return: ["prompt"]'
    )
    return system, user


async def generate_song_image(
    db: AsyncSession,
    song,
    *,
    album_context: str = "",
    provider: str | None = None,
    model: str | None = None,
    variation: int = 0,
) -> dict[str, Any]:
    """곡 1개의 배경 이미지 생성 → uploads/{album_id}/ 저장, song.image_path 갱신."""
    from app.config import settings

    s = await get_all_settings(db)

    # 1) 프롬프트 생성 (곡 데이터 기반)
    title = str(getattr(song, "title", "") or "").strip()
    if not title:
        raise ValueError("곡 제목이 없습니다.")
    theme = str(getattr(song, "theme", "") or "").strip()
    mood = str(getattr(song, "mood", "") or "").strip()
    tags = str(getattr(song, "tags", "") or "").strip()
    system, user = _song_prompt_request(title, theme, mood, tags)
    # 재생성 시 다른 결과 — 컨셉 자체를 순환 교체 (2026-09-10 v0.9.46)
    # 이미지 모델이 seed를 지원하지 않고(gemini·gpt-image 전부 미지원) temperature만으론
    # 유사 이미지가 반복되므, 프롬프트 단계에서 장면 구성을 강제로 바꾼다.
    if int(variation or 0):
        concepts = [
            "TIME SHIFT: move the moment — e.g. dusk or night version of the scene, "
            "or a different season/weather, keeping the place recognizable",
            "NEW FOCAL POINT: pick a DIFFERENT subject within the scene (e.g. a person, "
            "an object, or a detail) and build the composition around it",
            "DIFFERENT VANTAGE: dramatically change the viewpoint — overhead, low-angle, "
            "or extreme close-up with shallow depth of field",
            "WEATHER & ATMOSPHERE: rain, fog, snow, or strong wind transforming the mood",
            "STYLE CHANGE: switch to another medium — e.g. film photograph, painterly, "
            "or cinematic teal-orange grade",
            "INTERIOR/EXTERIOR SWAP: move to the opposite space of the same story "
            "(inside↔outside), or a neighboring location that continues the narrative",
        ]
        c = concepts[(int(variation) - 1) % len(concepts)]
        user += (
            f"\n\nREGENERATION #{int(variation)} — MANDATORY DIVERSITY. "
            f"Follow this directive: {c}. The final image must be CLEARLY different "
            "from the previous attempt while still depicting the song's scene. "
            "Rewrite the prompt accordingly — do not reuse the previous wording."
        )
    if album_context:
        user += (
            "\nAlbum context (secondary — only for lighting/palette consistency, "
            "the Scene description above stays the subject):\n" + album_context[:600]
        )
    temp = 0.9 if int(variation or 0) else 0.7
    try:
        raw = await _ai_text(db, "thumbnail", system, user, temperature=temp)
    except Exception as e:
        raise ValueError(f"[프롬프트 생성 실패] {e}") from e
    prompts = _extract_json(raw)
    prompt = prompts[0] if prompts else (
        f"Cinematic atmospheric scene for the song '{title}', "
        f"{mood or tags or 'music mood'}, no text"
    )

    # 2) 이미지 생성 — 앨범 썸네일과 동일 provider 로직
    configured_img = (s.get("image_provider") or "").strip().lower()
    if provider:
        prov = provider
    elif configured_img in IMAGE_PROVIDERS and s.get(IMAGE_PROVIDERS[configured_img]["key_field"]):
        prov = configured_img
    else:
        prov = "google" if s.get("google_api_key") else "openai"
    conf = IMAGE_PROVIDERS.get(prov)
    if not conf:
        raise ValueError(f"이미지 생성을 지원하지 않는 제공업체: {prov}")
    api_key = s.get(conf["key_field"], "")
    if not api_key:
        raise ValueError(
            f"{PROVIDER_INFO[prov]['name']} API 키가 없습니다. 설정 > AI 제공업체에서 입력하세요."
        )
    mdl = model or s.get("image_model") or conf["model"]

    try:
        import random as _random
        seed = _random.randint(0, 2**31 - 1)
        if prov == "openrouter":
            raw_img = await _gen_image_openrouter(api_key, mdl, prompt, seed=seed)
        elif prov == "google":
            raw_img = await _gen_image_google(api_key, mdl, prompt, None)
        else:
            raw_img = await _gen_image_openai(api_key, mdl, prompt)
    except Exception as e:
        raise ValueError(f"[이미지 생성 실패 {prov}:{mdl}] {e}") from e

    jpg = _crop_to_thumb(raw_img)

    # 3) 저장 — 기존 곡 커버 업로드와 같은 위치/규칙
    from app.config import settings

    upload_dir = settings.data_dir / "uploads" / str(getattr(song, "album_id", 0))
    upload_dir.mkdir(parents=True, exist_ok=True)
    base = f"cover_{int(getattr(song, 'track_number', 0) or 0):02d}_{getattr(song, 'id', 0)}"
    suffix = f".v{int(variation)}" if int(variation or 0) else ""
    filepath = upload_dir / f"{base}{suffix}.jpg"
    try:
        filepath.write_bytes(jpg)
    except OSError as e:
        raise ValueError(f"[저장 실패] {filepath.parent} — {e}") from e

    song.image_path = str(filepath)
    await db.flush()

    return {
        "song_id": song.id,
        "track": int(getattr(song, "track_number", 0) or 0),
        "title": title,
        "prompt": prompt,
        "image_path": str(filepath),
    }
