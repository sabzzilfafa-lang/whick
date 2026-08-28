"""프리셋에서 악기별 역할·음색·텍스처 정보를 추출."""

from __future__ import annotations

import re
from typing import Any

# 한국어/영어 악기명 → 기본 음색 특성
INSTRUMENT_TONE_DB: dict[str, dict[str, str]] = {
    "업라이트 베이스": {
        "name_en": "upright bass",
        "role": "bass",
        "tone": "deep, warm, round",
        "texture": "prominent walking bass lines",
    },
    "더블베이스": {
        "name_en": "double bass",
        "role": "bass",
        "tone": "deep, woody, resonant",
        "texture": "acoustic warmth",
    },
    "베이스": {
        "name_en": "bass",
        "role": "bass",
        "tone": "deep, groovy",
        "texture": "steady foundation",
    },
    "808": {
        "name_en": "808 bass",
        "role": "bass",
        "tone": "sub-heavy, punchy",
        "texture": "low-end driven",
    },
    "808 베이스": {
        "name_en": "808 bass",
        "role": "bass",
        "tone": "sub-heavy, distorted",
        "texture": "trap low-end",
    },
    "서브베이스": {
        "name_en": "sub bass",
        "role": "bass",
        "tone": "rumbling, deep sub",
        "texture": "felt more than heard",
    },
    "색소폰": {
        "name_en": "saxophone",
        "role": "lead",
        "tone": "smooth, smoky, expressive",
        "texture": "jazz phrasing",
    },
    "트럼펫": {
        "name_en": "trumpet",
        "role": "lead",
        "tone": "bright, brassy",
        "texture": "cool jazz accents",
    },
    "피아노": {
        "name_en": "piano",
        "role": "harmony",
        "tone": "warm, mellow",
        "texture": "chord voicings and comping",
    },
    "그랜드 피아노": {
        "name_en": "grand piano",
        "role": "lead",
        "tone": "rich, emotional, resonant",
        "texture": "melodic centerpiece",
    },
    "로파이 피아노": {
        "name_en": "lo-fi piano",
        "role": "lead",
        "tone": "dusty, nostalgic, soft",
        "texture": "tape-saturated keys",
    },
    "일렉 피아노": {
        "name_en": "electric piano",
        "role": "harmony",
        "tone": "warm Rhodes, bell-like",
        "texture": "soulful chords",
    },
    "브러시 드럼": {
        "name_en": "brushed drums",
        "role": "rhythm",
        "tone": "soft, swishing",
        "texture": "intimate jazz groove",
    },
    "브러시": {
        "name_en": "brushed drums",
        "role": "rhythm",
        "tone": "soft, swishing",
        "texture": "gentle swing",
    },
    "드럼": {
        "name_en": "drums",
        "role": "rhythm",
        "tone": "punchy, tight",
        "texture": "steady groove",
    },
    "라이트 드럼": {
        "name_en": "light drums",
        "role": "rhythm",
        "tone": "soft, minimal",
        "texture": "unobtrusive beat",
    },
    "어쿠스틱 기타": {
        "name_en": "acoustic guitar",
        "role": "rhythm",
        "tone": "warm, fingerpicked",
        "texture": "organic strumming",
    },
    "일렉 기타": {
        "name_en": "electric guitar",
        "role": "lead",
        "tone": "crisp, overdriven",
        "texture": "riff-driven energy",
    },
    "클린 기타": {
        "name_en": "clean electric guitar",
        "role": "rhythm",
        "tone": "bright, jangly",
        "texture": "open chords",
    },
    "리버브 기타": {
        "name_en": "reverb-drenched guitar",
        "role": "texture",
        "tone": "ethereal, washed-out",
        "texture": "wall of sound",
    },
    "신스": {
        "name_en": "synthesizer",
        "role": "texture",
        "tone": "lush, atmospheric",
        "texture": "pad layers",
    },
    "패드 신스": {
        "name_en": "synth pads",
        "role": "texture",
        "tone": "ambient, spacious",
        "texture": "atmospheric bed",
    },
    "패드": {
        "name_en": "pads",
        "role": "texture",
        "tone": "soft, enveloping",
        "texture": "background wash",
    },
    "아날로그 신스": {
        "name_en": "analog synth",
        "role": "lead",
        "tone": "warm, retro, fat",
        "texture": "80s analog leads",
    },
    "신스 리드": {
        "name_en": "synth lead",
        "role": "lead",
        "tone": "bright, cutting",
        "texture": "hook melody",
    },
    "하이햇": {
        "name_en": "hi-hats",
        "role": "rhythm",
        "tone": "crisp, rolling",
        "texture": "trap groove",
    },
    "킥": {
        "name_en": "kick drum",
        "role": "rhythm",
        "tone": "punchy, four-on-the-floor",
        "texture": "dance drive",
    },
    "하우스 킥": {
        "name_en": "house kick",
        "role": "rhythm",
        "tone": "deep, thumping",
        "texture": "club pulse",
    },
    "비닐 크랙": {
        "name_en": "vinyl crackle",
        "role": "texture",
        "tone": "dusty, nostalgic",
        "texture": "lo-fi ambience",
    },
    "스트링": {
        "name_en": "strings",
        "role": "texture",
        "tone": "lush, emotional",
        "texture": "orchestral swell",
    },
    "오케스트라": {
        "name_en": "orchestra",
        "role": "lead",
        "tone": "epic, cinematic",
        "texture": "full arrangement",
    },
    "나일론 기타": {
        "name_en": "nylon guitar",
        "role": "rhythm",
        "tone": "soft, warm",
        "texture": "bossa nova rhythm",
    },
    "재즈 기타": {
        "name_en": "jazz guitar",
        "role": "rhythm",
        "tone": "mellow, comping",
        "texture": "swing accompaniment",
    },
    "플루트": {
        "name_en": "flute",
        "role": "lead",
        "tone": "airy, delicate",
        "texture": "melodic accents",
    },
    "오르간": {
        "name_en": "organ",
        "role": "harmony",
        "tone": "warm, churchy",
        "texture": "sustained chords",
    },
    "브라스": {
        "name_en": "brass section",
        "role": "lead",
        "tone": "bold, punchy",
        "texture": "funk hits",
    },
    "퍼커션": {
        "name_en": "percussion",
        "role": "rhythm",
        "tone": "organic, layered",
        "texture": "rhythmic color",
    },
    "드론": {
        "name_en": "drone",
        "role": "texture",
        "tone": "dark, sustained",
        "texture": "unsettling atmosphere",
    },
    "브레이크비트": {
        "name_en": "breakbeats",
        "role": "rhythm",
        "tone": "fast, chopped",
        "texture": "jungle energy",
    },
    "카우벨": {
        "name_en": "cowbell",
        "role": "rhythm",
        "tone": "metallic, sharp",
        "texture": "phonk signature",
    },
}

# 프리셋별 악기 상세 오버라이드 (더 정밀한 기본값)
PRESET_INSTRUMENT_OVERRIDES: dict[str, list[dict[str, str]]] = {
    "deep_bass_jazz": [
        {
            "name": "업라이트 베이스",
            "name_en": "upright bass",
            "role": "bass",
            "tone": "deep, warm, woody, front-of-mix",
            "texture": "walking bass lines, prominent sub",
            "notes": "딥베이스 재즈의 핵심 — 저음이 주도",
        },
        {
            "name": "색소폰",
            "name_en": "tenor saxophone",
            "role": "lead",
            "tone": "smooth, smoky, breathy",
            "texture": "late-night jazz solos",
            "notes": "멜로디 리드",
        },
        {
            "name": "피아노",
            "name_en": "jazz piano",
            "role": "harmony",
            "tone": "warm, mellow, sparse voicings",
            "texture": "comping behind sax",
            "notes": "코드 반주",
        },
        {
            "name": "브러시 드럼",
            "name_en": "brushed drums",
            "role": "rhythm",
            "tone": "soft, swishing, intimate",
            "texture": "gentle swing, brushed snare",
            "notes": "은은한 스윙 그루브",
        },
    ],
    "lofi": [
        {
            "name": "로파이 피아노",
            "name_en": "lo-fi piano",
            "role": "lead",
            "tone": "dusty, soft, detuned",
            "texture": "sampled jazz chords",
            "notes": "메인 멜로디 소스",
        },
        {
            "name": "재즈 기타",
            "name_en": "jazz guitar",
            "role": "rhythm",
            "tone": "mellow, warm",
            "texture": "fingerpicked comping",
            "notes": "배경 그루브",
        },
        {
            "name": "비닐 크랙",
            "name_en": "vinyl crackle",
            "role": "texture",
            "tone": "nostalgic, dusty",
            "texture": "constant lo-fi ambience",
            "notes": "레코드 노이즈",
        },
        {
            "name": "808",
            "name_en": "sub bass",
            "role": "bass",
            "tone": "soft sub, rounded",
            "texture": "gentle low-end",
            "notes": "부드러운 저음",
        },
    ],
    "phonk": [
        {
            "name": "808 베이스",
            "name_en": "distorted 808",
            "role": "bass",
            "tone": "heavy, clipped, sub-rattling",
            "texture": "drift phonk signature",
            "notes": "과장된 저음",
        },
        {
            "name": "카우벨",
            "name_en": "cowbell",
            "role": "rhythm",
            "tone": "metallic, sharp",
            "texture": "memphis phonk hook",
            "notes": "시그니처 리듬",
        },
    ],
}


def _split_instruments(text: str) -> list[str]:
    if not text:
        return []
    parts = re.split(r"[,、/·]+", text)
    return [p.strip() for p in parts if p.strip()]


def _match_instrument_token(token: str) -> dict[str, str] | None:
    token_lower = token.lower()
    # 긴 키부터 매칭 (808 베이스 vs 베이스)
    for key in sorted(INSTRUMENT_TONE_DB.keys(), key=len, reverse=True):
        if key in token or key.lower() in token_lower:
            return INSTRUMENT_TONE_DB[key]
    return None


def parse_instruments_from_text(instruments_text: str) -> list[dict[str, Any]]:
    """악기 문자열을 악기별 상세 정보 리스트로 변환."""
    result: list[dict[str, Any]] = []
    seen: set[str] = set()

    for token in _split_instruments(instruments_text):
        if token in seen:
            continue
        seen.add(token)

        matched = _match_instrument_token(token)
        if matched:
            result.append(
                {
                    "name": token,
                    "name_en": matched["name_en"],
                    "role": matched["role"],
                    "tone": matched["tone"],
                    "texture": matched["texture"],
                    "notes": "",
                }
            )
        else:
            result.append(
                {
                    "name": token,
                    "name_en": token,
                    "role": "texture",
                    "tone": "characteristic, expressive",
                    "texture": "supporting layer",
                    "notes": "",
                }
            )
    return result


def get_instrument_details(preset: dict) -> list[dict[str, Any]]:
    preset_id = preset.get("id", "")
    if preset_id in PRESET_INSTRUMENT_OVERRIDES:
        return [dict(item) for item in PRESET_INSTRUMENT_OVERRIDES[preset_id]]

    return parse_instruments_from_text(preset.get("instruments", ""))


def profile_to_musical_traits(profile: dict) -> dict[str, Any]:
    return {
        "genre": profile.get("genre") or "",
        "mood": profile.get("mood") or "",
        "tempo_bpm": profile.get("tempo_bpm"),
        "key_signature": profile.get("key_signature") or "",
        "vocal_style": profile.get("vocal_style") or "",
        "production_style": profile.get("production_style") or "",
        "reference_artists": profile.get("reference_artists") or "",
        "description": profile.get("description") or "",
    }
