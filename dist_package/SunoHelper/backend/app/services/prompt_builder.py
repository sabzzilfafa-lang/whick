"""프리셋 + 사용자 입력 → 영어 Suno 프롬프트 생성."""

from __future__ import annotations

from typing import Any, Optional

from app.config import settings
from app.services.ai_client import AIClient
from app.services.instrument_details import (
    get_instrument_details,
    profile_to_musical_traits,
)

PROMPT_BUILDER_SYSTEM = """You are a Suno AI music prompt expert.

Given structured musical traits and per-instrument details (role, tone, texture), create ONE concise English Suno style prompt.

Rules:
- Output ONLY the English prompt text (no quotes, no explanation)
- Max 250 characters
- Comma-separated keywords style
- Include: genre, mood, tempo (BPM), vocal style, key instruments with tonal qualities, production character
- User additions may be in Korean — understand and incorporate, output in English only
- Prioritize instrument tones and textures when specified
- Reference artists only if they fit naturally

Example: deep bass jazz, upright bass prominent, warm smoky tenor sax, brushed drums, 78 BPM, vinyl crackle, late night lounge, instrumental"""


def build_instrument_context(instruments: list[dict[str, Any]]) -> str:
    if not instruments:
        return ""
    lines = ["## Per-Instrument Details"]
    for inst in instruments:
        name = inst.get("name_en") or inst.get("name", "")
        parts = [f"- {name}"]
        if inst.get("role"):
            parts.append(f"role: {inst['role']}")
        if inst.get("tone"):
            parts.append(f"tone: {inst['tone']}")
        if inst.get("texture"):
            parts.append(f"texture: {inst['texture']}")
        if inst.get("notes"):
            parts.append(f"notes: {inst['notes']}")
        lines.append(", ".join(parts))
    return "\n".join(lines)


def build_traits_context(traits: dict[str, Any]) -> str:
    lines = ["## Musical Traits"]
    if traits.get("genre"):
        lines.append(f"- Genre: {traits['genre']}")
    if traits.get("mood"):
        lines.append(f"- Mood: {traits['mood']}")
    if traits.get("tempo_bpm"):
        lines.append(f"- Tempo: {traits['tempo_bpm']} BPM")
    if traits.get("key_signature"):
        lines.append(f"- Key: {traits['key_signature']}")
    if traits.get("vocal_style"):
        lines.append(f"- Vocal: {traits['vocal_style']}")
    if traits.get("production_style"):
        lines.append(f"- Production: {traits['production_style']}")
    if traits.get("reference_artists"):
        lines.append(f"- Reference: {traits['reference_artists']}")
    if traits.get("description"):
        lines.append(f"- Description: {traits['description']}")
    return "\n".join(lines)


def build_draft_prompt_english(
    traits: dict[str, Any],
    instruments: list[dict[str, Any]],
    user_additions: str = "",
) -> str:
    """API 없이 즉시 생성 가능한 영어 프롬프트 초안."""
    parts: list[str] = []

    if traits.get("genre"):
        parts.append(traits["genre"].split(",")[0].strip().lower())
    if traits.get("mood"):
        mood_words = [m.strip().lower() for m in traits["mood"].split(",")[:2]]
        parts.extend(mood_words)
    if traits.get("tempo_bpm"):
        parts.append(f"{traits['tempo_bpm']} BPM")
    if traits.get("vocal_style"):
        vocal = traits["vocal_style"].lower()
        if "인스트" in vocal or "instrumental" in vocal.lower():
            parts.append("instrumental")
        else:
            parts.append(vocal.split(",")[0].strip()[:40])

    for inst in instruments[:5]:
        name_en = inst.get("name_en") or inst.get("name", "")
        tone = inst.get("tone", "")
        if name_en:
            entry = name_en
            if tone:
                entry = f"{name_en} ({tone.split(',')[0].strip()})"
            parts.append(entry)

    if traits.get("production_style"):
        prod = traits["production_style"].split(",")[0].strip().lower()
        parts.append(prod)

    if user_additions.strip():
        parts.append(user_additions.strip()[:80])

    # 쉼표 구분, 중복 제거
    seen: set[str] = set()
    unique: list[str] = []
    for p in parts:
        key = p.lower()
        if key and key not in seen:
            seen.add(key)
            unique.append(p)

    return ", ".join(unique)[:250]


def build_builder_context(
    traits: dict[str, Any],
    instruments: list[dict[str, Any]],
    user_additions: str = "",
    song: Optional[dict] = None,
) -> str:
    sections = [build_traits_context(traits), build_instrument_context(instruments)]

    if song:
        sections.append("\n## Song Context")
        if song.get("title"):
            sections.append(f"- Title: {song['title']}")
        if song.get("theme"):
            sections.append(f"- Theme: {song['theme']}")
        if song.get("mood"):
            sections.append(f"- Song mood: {song['mood']}")

    if user_additions.strip():
        sections.append(f"\n## User Additions (may be Korean)\n{user_additions.strip()}")

    return "\n".join(sections)


async def generate_prompt_english(
    client: AIClient,
    traits: dict[str, Any],
    instruments: list[dict[str, Any]],
    user_additions: str = "",
    song: Optional[dict] = None,
    model: Optional[str] = None,
    temperature: float = 0.5,
) -> str:
    context = build_builder_context(traits, instruments, user_additions, song)
    user_prompt = (
        f"{context}\n\n"
        "Create the final Suno style prompt in English based on all the above."
    )
    result = await client.chat(
        model or settings.model_prompt,
        PROMPT_BUILDER_SYSTEM,
        user_prompt,
        temperature=temperature,
    )
    return result.strip().strip('"').strip("'")


def build_template_from_preset(preset: dict) -> dict[str, Any]:
    """프리셋 → 프롬프트 빌더 템플릿."""
    traits = profile_to_musical_traits(preset)
    instruments = get_instrument_details(preset)
    draft = build_draft_prompt_english(traits, instruments)
    return {
        "preset_id": preset.get("id"),
        "name": preset.get("name"),
        "emoji": preset.get("emoji"),
        "category": preset.get("category"),
        "musical_traits": traits,
        "instruments": instruments,
        "draft_prompt_english": draft,
    }


def build_template_from_profile(profile: dict) -> dict[str, Any]:
    traits = profile_to_musical_traits(profile)
    instruments = parse_instruments_fallback(profile)
    draft = build_draft_prompt_english(traits, instruments)
    return {
        "profile_id": profile.get("id"),
        "name": profile.get("name"),
        "emoji": profile.get("emoji"),
        "musical_traits": traits,
        "instruments": instruments,
        "draft_prompt_english": draft,
    }


def parse_instruments_fallback(profile: dict) -> list[dict[str, Any]]:
    from app.services.instrument_details import parse_instruments_from_text

    preset_like = {"id": "", "instruments": profile.get("instruments", "")}
    return get_instrument_details(preset_like) or parse_instruments_from_text(
        profile.get("instruments", "")
    )
