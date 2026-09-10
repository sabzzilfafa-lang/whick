"""앨범 썸네일 3종 AI 생성 서비스 (2026-09-09).

앨범 커버 + 앨범 정보로 이미지 생성 프롬프트 3개를 AI가 만들고,
이미지 생성 모델(Google gemini-2.5-flash-image / OpenAI gpt-image-1)로
1280x720 썸네일 3장(thumb-A/B/C.jpg)을 앨범 폴더 thumbnails/에 저장한다.

유튜브 Test & Compare는 공개 API가 없어(Studio 전용) 이 앱은
3종 파일 생성 + 스튜디오 수동 등록 안내까지만 제공한다.
"""

from __future__ import annotations

import base64
import io
import json
import re
from pathlib import Path
from typing import Any

import httpx
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai_client import AIClient, API_KEY_FIELDS, PROVIDER_INFO
from app.services.settings_service import get_all_settings
from app.services.workflow_service import (
    ensure_album_work_folder,
    find_project_assets,
    resolve_safe_path,
)

THUMB_W, THUMB_H = 1280, 720
VARIANT_IDS = ("A", "B", "C")

# 이미지 생성 지원 제공업체 → (모델, 키 필드)
IMAGE_PROVIDERS: dict[str, dict[str, str]] = {
    "openrouter": {"model": "google/gemini-2.5-flash-image", "key_field": "openrouter_api_key"},
    "google": {"model": "gemini-2.5-flash-image", "key_field": "google_api_key"},
    "openai": {"model": "gpt-image-1", "key_field": "openai_api_key"},
}


IMAGE_MODELS_OPENROUTER_FALLBACK = [
    {"id": "google/gemini-2.5-flash-image", "name": "Gemini 2.5 Flash Image (Nano Banana)"},
    {"id": "openai/gpt-image-1", "name": "GPT Image 1"},
]


async def list_image_models(db: AsyncSession) -> list[dict[str, str]]:
    """이미지 생성 모델 목록 — openrouter는 /api/v1/images/models, 나머지는 고정."""
    s = await get_all_settings(db)
    prov = (s.get("image_provider") or "openrouter").strip().lower()
    if prov == "openrouter":
        key = s.get("openrouter_api_key", "")
        if key:
            try:
                async with httpx.AsyncClient(timeout=20.0) as client:
                    r = await client.get(
                        "https://openrouter.ai/api/v1/images/models",
                        headers={"Authorization": f"Bearer {key}"},
                    )
                    r.raise_for_status()
                    data = r.json().get("data") or []
                    models = [
                        {"id": m.get("id", ""), "name": m.get("name") or m.get("id", "")}
                        for m in data
                        if m.get("id")
                    ]
                    if models:
                        return models
            except Exception:
                pass
        return list(IMAGE_MODELS_OPENROUTER_FALLBACK)
    conf = IMAGE_PROVIDERS.get(prov)
    return [{"id": conf["model"], "name": conf["model"]}] if conf else []


def thumbnails_dir(album_dir: Path) -> Path:
    return album_dir / "thumbnails"


def list_generated_thumbnails(album_dir: Path) -> list[dict[str, str]]:
    """생성된 썸네일 3종 현황 (variant → 상대경로·파일명)."""
    out: list[dict[str, str]] = []
    tdir = thumbnails_dir(album_dir)
    for v in VARIANT_IDS:
        p = tdir / f"thumb-{v}.jpg"
        out.append(
            {
                "variant": v,
                "path": str(p) if p.is_file() else "",
                "ready": p.is_file(),
            }
        )
    return out


async def _ai_text(db: AsyncSession, task: str, system: str, user: str) -> str:
    """설정된 텍스트 제공업체로 짧은 JSON 응답 요청.

    썸네일은 설정 > 썸네일 생성 AI(provider_thumbnail/model_thumbnail)를 우선 사용하고
    없으면 기존 프롬프트 태스크 설정을 따른다 (2026-09-10).
    """
    s = await get_all_settings(db)
    if task == "thumbnail":
        provider = s.get("provider_thumbnail") or s.get("provider_prompt") or "openrouter"
        # model_thumbnail이 비면 provider 기본 썸네일 모델 사용 — 딥시크(가사) 폴백 방지 (2026-09-10)
        model = s.get("model_thumbnail") or ""
    else:
        provider = s.get(f"provider_{task}") or "openrouter"
        model = s.get(f"model_{task}") or ""
    key = s.get(API_KEY_FIELDS.get(provider, ""), "")  # type: ignore[arg-type]
    client = AIClient(provider, key)
    if not model:
        model = PROVIDER_INFO.get(provider, {}).get("default_models", {}).get("thumbnail", "")
    return await client.chat(model, system, user, temperature=0.7, json_mode=True)


def _extract_json(text: str) -> list[str]:
    """AI 응답에서 JSON 배열(문자열 3개) 추출 — 코드펜스·잡담 허용."""
    m = re.search(r"\[[\s\S]*\]", text)
    if not m:
        raise ValueError("AI가 프롬프트 3개를 JSON 배열로 반환하지 않았습니다.")
    data = json.loads(m.group(0))
    prompts = [str(p).strip() for p in data if str(p).strip()]
    if len(prompts) < 3:
        raise ValueError(f"AI가 3개 미만의 프롬프트를 반환했습니다: {len(prompts)}개")
    return prompts[:3]


def _build_prompt_request(album_title: str, mood: str, concept: str) -> tuple[str, str]:
    system = (
        "You are a YouTube thumbnail art director for music albums. "
        "Reply with ONLY a JSON array of exactly 3 strings — each an image-generation "
        "prompt for ONE distinct thumbnail concept (A: bold photo-composition with big "
        "readable title text, B: moody atmospheric scene, C: minimal graphic/poster "
        "style). Each prompt must specify: 16:9 landscape, music album mood, no "
        "watermarks, no logos. IMPORTANT: concept A must include the album title as "
        "large, creative, stylized typography rendered INTO the image (bold display "
        "font, artistic placement, matching the mood). Keep the album title text "
        "short and in English."
    )
    user = (
        f"Album title: {album_title}\n"
        f"Mood: {mood or 'unspecified'}\n"
        f"Concept: {concept or 'unspecified'}\n"
        "Return: [\"prompt A\", \"prompt B\", \"prompt C\"]"
    )
    return system, user


def _find_font(size: int) -> "ImageFont.FreeTypeFont | ImageFont.ImageFont":
    """OS별 사용 가능한 굵은 폰트 탐색 — 없으면 기본 폰트."""
    from PIL import ImageFont
    candidates = [
        r"C:\\Windows\\Fonts\\arialbd.ttf",
        r"C:\\Windows\\Fonts\\malgunbd.ttf",
        r"C:\\Windows\\Fonts\\seguisb.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for c in candidates:
        try:
            return ImageFont.truetype(c, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _audio_seconds(path: Path) -> int:
    """오디오 길이(초) — soundfile 우선, 실패 시 av. 모두 실패 시 0."""
    try:
        import soundfile as sf
        info = sf.info(str(path))
        return int(info.frames / max(info.samplerate, 1))
    except Exception:
        pass
    try:
        import av as _av
        with _av.open(str(path)) as c:
            dur = c.duration or 0
            return int(dur / 1_000_000)
    except Exception:
        return 0


def _format_duration(seconds: int) -> str:
    m, s2 = divmod(max(0, seconds), 60)
    return f"{m}:{s2:02d}"


def _overlay_text(
    img_bytes: bytes,
    title: str,
    subtitle: str = "",
    track_count: int = 0,
    total_seconds: int = 0,
) -> bytes:
    """썸네일 하단에 반투명 바 + 앨범제목·부제·곡수·런닝타임 오버레이 (2026-09-10).

    AI 이미지에는 정확한 글자를 넣기 어려우므로 PIL 후처리로 확정 표기한다.
    """
    from PIL import Image, ImageDraw
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    img = img.resize((THUMB_W, THUMB_H), Image.LANCZOS)
    draw = ImageDraw.Draw(img, "RGBA")

    bar_h = 96 if title else 0
    if bar_h:
        draw.rectangle([(0, THUMB_H - bar_h), (THUMB_W, THUMB_H)], fill=(0, 0, 0, 170))
        f_title = _find_font(40)
        f_meta = _find_font(24)
        tx, ty = 28, THUMB_H - bar_h + 10
        if title:
            # 그림자 + 아웃라인 — AI 이미지 위에서도 글자가 또렷하게 읽힘
            draw.text((tx + 2, ty + 3), title[:40], font=f_title, fill=(0, 0, 0, 160))
            draw.text(
                (tx, ty), title[:40], font=f_title,
                fill=(255, 255, 255, 240),
                stroke_width=2, stroke_fill=(0, 0, 0, 200),
            )
        if subtitle:
            draw.text((tx + 1, ty + 51), subtitle[:60], font=f_meta, fill=(0, 0, 0, 140))
            draw.text((tx, ty + 50), subtitle[:60], font=f_meta, fill=(215, 215, 215, 225))
        meta_parts = []
        if track_count:
            meta_parts.append(f"{track_count} tracks")
        if total_seconds:
            meta_parts.append(_format_duration(total_seconds))
        if meta_parts:
            mw = draw.textlength(" · ".join(meta_parts), font=f_meta)
            draw.text(
                (THUMB_W - mw - 28, THUMB_H - bar_h + 22),
                " · ".join(meta_parts),
                font=f_meta,
                fill=(255, 255, 255, 220),
            )
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=92)
    return buf.getvalue()


def _crop_to_thumb(img_bytes: bytes) -> bytes:
    """생성 이미지를 1280x720으로 센터크롭+리사이즈해 JPEG로 인코딩."""
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    w, h = img.size
    target = THUMB_W / THUMB_H
    if w / h > target:
        nw = int(h * target)
        x = (w - nw) // 2
        img = img.crop((x, 0, x + nw, h))
    else:
        nh = int(w / target)
        y = (h - nh) // 2
        img = img.crop((0, y, w, y + nh))
    img = img.resize((THUMB_W, THUMB_H), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=92)
    return buf.getvalue()


async def _gen_image_openrouter(api_key: str, model: str, prompt: str) -> bytes:
    """OpenRouter Image API — POST /api/v1/images, 응답 data[0].b64_json (2026-09-10).

    OpenAI 호환 게이트웨이 — openrouter_api_key 하나로 Gemini·GPT-Image 등
    이미지 모델을 모두 쓸 수 있다. 기본 모델 google/gemini-2.5-flash-image.
    """
    async with httpx.AsyncClient(timeout=180.0) as client:
        resp = await client.post(
            "https://openrouter.ai/api/v1/images",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={"model": model, "prompt": prompt, "aspect_ratio": "16:9"},
        )
        resp.raise_for_status()
        data = resp.json()
    b64 = ((data.get("data") or [{}])[0].get("b64_json")) or ""
    if not b64:
        raise ValueError("OpenRouter 이미지 응답에 b64_json이 없습니다.")
    return base64.b64decode(b64)


async def _gen_image_google(
    api_key: str, model: str, prompt: str, cover_b64: str | None
) -> bytes:
    """Gemini 이미지 생성 — responseModalities [TEXT, IMAGE], inlineData로 반환."""
    parts: list[dict] = [{"text": prompt}]
    if cover_b64:
        parts.append(
            {"inline_data": {"mime_type": "image/jpeg", "data": cover_b64}}
        )
    body = {
        "contents": [{"parts": parts}],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    async with httpx.AsyncClient(timeout=180.0) as client:
        resp = await client.post(
            url,
            # 키는 헤더로 전달 — URL 쿼리(?key=)로 보내면 httpx 에러 메시지에
            # 전체 URL(쿼리 포함)이 들어가 API 키가 응답으로 누출된다 (bugbot 2026-09-10).
            headers={"x-goog-api-key": api_key},
            json=body,
        )
        resp.raise_for_status()
        data = resp.json()
    for part in (data.get("candidates") or [{}])[0].get("content", {}).get("parts", []):
        inline = part.get("inlineData") or part.get("inline_data")
        if inline and inline.get("data"):
            return base64.b64decode(inline["data"])
    raise ValueError("Gemini 이미지 응답에 inlineData가 없습니다.")


async def _gen_image_openai(api_key: str, model: str, prompt: str) -> bytes:
    """OpenAI images/generations — gpt-image-1, 1280x720 근사(1536x1024 → 크롭)."""
    async with httpx.AsyncClient(timeout=180.0) as client:
        resp = await client.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "prompt": prompt, "size": "1536x1024"},
        )
        resp.raise_for_status()
        data = resp.json()
    item = (data.get("data") or [{}])[0]
    b64 = item.get("b64_json")
    if not b64 and item.get("url"):
        async with httpx.AsyncClient(timeout=120.0) as c2:
            r2 = await c2.get(item["url"])
            r2.raise_for_status()
            return r2.content
    if not b64:
        raise ValueError("OpenAI 이미지 응답에 데이터가 없습니다.")
    return base64.b64decode(b64)


async def _resolve_album_dir(db: AsyncSession, album) -> Path:
    root = await _work_root(db)
    return ensure_album_work_folder(root, album, "music")


async def _work_root(db: AsyncSession):
    from app.services.workflow_service import get_work_root

    return await get_work_root(db)


async def _cover_b64(album_dir: Path) -> str | None:
    """앨범 첫 곡 커버를 base64로 — 이미지 참조 생성용(없어도 진행)."""
    try:
        for song_dir in sorted(p for p in album_dir.iterdir() if p.is_dir()):
            assets = find_project_assets(song_dir)
            covers = assets.get("cover_image_paths") or []
            if covers:
                return base64.b64encode(Path(covers[0]).read_bytes()).decode()
    except OSError:
        pass
    return None


def _collect_album_context(album) -> str:
    """앨범+곡 데이터에서 썸네일 분위기 컨텍스트 수집 (2026-09-10).

    곡의 mood·tags·스타일(suno_prompt)·가사 분위기를 반영해 곡과 상관없는
    이미지가 나오지 않도록 한다.
    """
    lines: list[str] = []
    mood = str(getattr(album, "mood", "") or "").strip()
    if mood:
        lines.append(f"Album mood: {mood}")
    concept = str(getattr(album, "concept", "") or "").strip()
    if concept:
        lines.append(f"Album concept: {concept[:300]}")
    profile = getattr(album, "music_profile", None)
    if profile is not None:
        bits = []
        for f in ("genre", "mood", "vocal_style", "production_style", "tags", "emoji"):
            v = str(getattr(profile, f, "") or "").strip()
            if v:
                bits.append(f"{f}={v[:120]}")
        if bits:
            lines.append("Style preset: " + ", ".join(bits))
    songs = list(getattr(album, "songs", []) or [])
    if songs:
        moods: list[str] = []
        tags: list[str] = []
        styles: list[str] = []
        for sg in songs[:20]:
            for src, dst in (
                (str(getattr(sg, "mood", "") or ""), moods),
                (str(getattr(sg, "tags", "") or ""), tags),
                (str(getattr(sg, "suno_prompt", "") or ""), styles),
            ):
                if src and src not in dst:
                    dst.append(src)
        if moods:
            lines.append("Track moods: " + ", ".join(moods[:10]))
        if tags:
            lines.append("Track tags: " + ", ".join(tags[:10]))
        if styles:
            lines.append("Track styles: " + " | ".join(x[:150] for x in styles[:5]))
    return "\n".join(lines)


async def generate_prompts(db: AsyncSession, album) -> list[str]:
    """앨범+곡 데이터로 썸네일용 이미지 프롬프트 3개 생성."""
    title = str(getattr(album, "title", "") or "").strip()
    if not title:
        raise ValueError("앨범 제목이 없습니다.")
    context = _collect_album_context(album)
    system, user = _build_prompt_request(title, "", "")
    if context:
        user += "\nContext (use this to match the imagery mood):\n" + context
    raw = await _ai_text(db, "thumbnail", system, user)
    return _extract_json(raw)


async def generate_thumbnails(
    db: AsyncSession,
    album,
    *,
    provider: str | None = None,
    model: str | None = None,
    prompts: list[str] | None = None,
) -> dict[str, Any]:
    """프롬프트 3개로 썸네일 3장 생성 → thumbnails/thumb-A|B|C.jpg 저장.

    provider 미지정 시 google(gemini-2.5-flash-image) 우선, 키 없으면 openai.
    """
    s = await get_all_settings(db)
    # 이미지 생성 제공업체: 요청 지정 > 설정(image_provider) > 키 보유 기준 자동 (2026-09-10)
    configured_img = (s.get("image_provider") or "").strip().lower()
    if provider:
        prov = provider
    elif configured_img in IMAGE_PROVIDERS and s.get(
        IMAGE_PROVIDERS[configured_img]["key_field"]
    ):
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

    album_dir = await _resolve_album_dir(db, album)
    if not prompts:
        prompts = await generate_prompts(db, album)
    if len(prompts) < 3:
        raise ValueError("프롬프트가 3개 필요합니다.")

    cover_b64 = await _cover_b64(album_dir)
    tdir = thumbnails_dir(album_dir)
    tdir.mkdir(parents=True, exist_ok=True)

    # 텍스트 오버레이용 메타 (settings.thumbnail_overlay = "1"일 때 하단 바 표기)
    overlay_on = (s.get("thumbnail_overlay") or "1").strip() == "1"
    ov_title = str(getattr(album, "title", "") or "").strip()
    ov_subtitle = str(getattr(album, "mood", "") or getattr(album, "concept", "") or "").strip()
    ov_tracks = int(getattr(album, "track_count", 0) or 0)
    ov_seconds = 0
    for sg in (getattr(album, "songs", []) or []):
        ap = str(getattr(sg, "audio_path", "") or "")
        if ap:
            try:
                pp = Path(ap)
                if not pp.is_absolute():
                    pp = album_dir / ap
                if pp.is_file():
                    ov_seconds += _audio_seconds(pp)
            except Exception:
                continue

    saved: list[dict[str, str]] = []
    for v, prompt in zip(VARIANT_IDS, prompts):
        if prov == "openrouter":
            raw = await _gen_image_openrouter(api_key, mdl, prompt)
        elif prov == "google":
            raw = await _gen_image_google(api_key, mdl, prompt, cover_b64)
        else:
            raw = await _gen_image_openai(api_key, mdl, prompt)
        jpg = _crop_to_thumb(raw)
        if overlay_on and ov_title:
            jpg = _overlay_text(
                jpg,
                title=ov_title,
                subtitle=ov_subtitle,
                track_count=ov_tracks,
                total_seconds=ov_seconds,
            )
        dest = tdir / f"thumb-{v}.jpg"
        dest.write_bytes(jpg)
        saved.append({"variant": v, "path": str(dest), "ready": True})

    return {
        "ok": True,
        "provider": prov,
        "model": mdl,
        "dir": str(tdir),
        "prompts": prompts,
        "files": saved,
    }
