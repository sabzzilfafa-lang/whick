"""Suno 스타일 프롬프트 생성 — 구간별 편곡, 최대 1000자."""

from __future__ import annotations

import json
import re
from typing import Optional

from app.services.instrument_settings_service import parse_settings

SUNO_PROMPT_MAX_CHARS = 1000

SECTION_SPECS: tuple[tuple[str, str], ...] = (
    ("overview", "[Overview]"),
    ("intro", "[Intro]"),
    ("verse_main", "[Verse]"),
    ("build", "[Build]"),
    ("chorus_climax", "[Chorus]"),
    ("bridge", "[Bridge]"),
    ("outro", "[Outro]"),
    ("mix_notes", "[Mix]"),
)

PROMPT_JSON_SYSTEM = f"""You are a Suno AI arrangement producer. Output ONLY valid JSON (no markdown).
Write in English inside JSON string values. HARD LIMIT: formatted output must be under {SUNO_PROMPT_MAX_CHARS - 50} characters total.

Required JSON keys (each value: ONE short sentence, max 90 characters):
- overview: genre, THIS song's mood/emotion, BPM, vocal style, exact total duration mm:ss, LIST EVERY allowed instrument by name
- intro: start feel using ONLY allowed instruments, no vocals
- verse_main: verse using ONLY allowed instruments, groove from those instruments (not a drum kit unless listed), vocal mix
- build: pre-chorus layering with ONLY allowed instruments
- chorus_climax: peak arrangement with ONLY allowed instruments, hook, effects
- bridge: contrast using ONLY allowed instruments
- outro: ending with ONLY allowed instruments, fade/stop
- mix_notes: balance, keep BPM, keep total duration, explicitly "no drums/percussion" if not in the list, use only listed instruments

CRITICAL instrument lock (highest priority):
- The song instrument list is a CLOSED set. Name those instruments (English) in overview and mix.
- NEVER invent instruments not in the list — especially drums, drum kit, percussion, kick, snare, hi-hat, cymbals, synth, strings, pads, brass, unless listed.
- If drums/percussion are NOT in the list, write "no drums, no percussion" in overview or mix, and do NOT imply a drum kit with words like "full band", "driving beat", "drum groove", "kick", "snare".
- Groove/pulse must come from listed instruments only (e.g. bass + guitar + piano).
- Manual song instrument settings override the album style preset completely.

CRITICAL emotion rules:
- Derive mood from THIS song's lyrics, theme, and mood field (excitement, reunion warmth, melancholy, longing, hope, etc.).
- Album profile mood is a baseline only — do not copy the same arrangement for every track.
- Vary energy via dynamics and listed-instrument roles, not by adding unlisted instruments.

If Song-specific directions mention vocals (duet, 혼성, 남녀, etc.), overview MUST state that vocal setup in English (e.g. male-female duet vocals).
User Song-specific directions override profile default vocal_style. Repeat key vocal instructions in verse_main and chorus_climax when relevant.

The overview MUST state the exact target total duration (mm:ss) provided in the user prompt.
Do not invent a different song length.

Be specific but terse. Do NOT write long paragraphs. Do NOT output comma-separated tags only."""


def _format_duration(sec: int) -> str:
    m, s = divmod(sec, 60)
    return f"{m}:{s:02d}"


def format_track_duration(sec: int) -> str:
    return _format_duration(sec)


BPM_VARIATION = 5  # 프리셋 BPM ±5 안에서 곡별 변주


def _base_bpm(profile: Optional[dict], song: Optional[dict] = None) -> int:
    """프리셋(또는 곡에 저장된) 기준 BPM."""
    for src in (song, profile):
        if not src:
            continue
        raw = src.get("tempo_bpm")
        if raw is None:
            continue
        try:
            return max(40, min(220, int(raw)))
        except (TypeError, ValueError):
            continue
    return 85


def _bpm_from_instrument_settings(instrument_settings: Optional[str]) -> Optional[int]:
    parsed = parse_settings(instrument_settings)
    if not parsed:
        return None
    raw = parsed.get("tempo_bpm")
    if raw is None:
        return None
    try:
        return max(40, min(220, int(raw)))
    except (TypeError, ValueError):
        return None


# 에너지↑ → BPM↑ / 에너지↓ → BPM↓ (한국어·영어)
_BPM_ENERGY_UP = (
    "설렘", "설레", "두근", "신나", "신남", "들뜸", "신나는", "흥분", "환희",
    "희망", "희망찬", "밝", "밝은", "경쾌", "경쾌한", "활기", "에너지", "파티",
    "댄스", "춤", "달려", "뛰", "질주", "열정", "뜨거운", "뜨거", "기쁨", "기뻐",
    "반가", "반갑", "축하", "축제", "흥", "업템포", "빠르게", "신바람",
    "exciting", "excited", "upbeat", "energetic", "dance", "party", "joyful",
    "happy", "bright", "hopeful", "passionate", "rush", "thrill", "celebrate",
)
_BPM_ENERGY_DOWN = (
    "우울", "슬픔", "슬픈", "슬퍼", "그리움", "그립", "쓸쓸", "외로", "외로운",
    "허무", "잔잔", "고요", "고요한", "차분", "차분한", "느린", "느리", "애잔",
    "눈물", "이별", "작별", "아픈", "아픔", "그리워", "회상", "밤비", "빗소리",
    "몽환", "몽환적", "나른", "여유", "고요함", "침묵", "고요히", "다운템포",
    "sad", "melancholy", "melancholic", "lonely", "longing", "grief", "sorrow",
    "slow", "calm", "quiet", "soft", "dreamy", "nostalgic", "bittersweet",
    "tear", "farewell", "gentle", "peaceful", "ambient",
)


def _emotion_energy_score(
    song: Optional[dict] = None,
    lyrics: Optional[str] = None,
) -> float:
    """-1.0(느림) ~ +1.0(빠름) 감정 에너지."""
    chunks: list[str] = []
    if song:
        for key in ("mood", "theme", "title", "tags"):
            val = song.get(key)
            if val:
                chunks.append(str(val))
    if lyrics:
        chunks.append(lyrics[:2500])
    text = " ".join(chunks).lower()
    if not text.strip():
        return 0.0

    up = sum(1 for w in _BPM_ENERGY_UP if w.lower() in text)
    down = sum(1 for w in _BPM_ENERGY_DOWN if w.lower() in text)
    raw = up - down
    # 트랙 번호로 미세 분산 (같은 분위기 곡이 전부 같은 BPM이 되지 않게)
    track = 0
    if song and song.get("track_number") is not None:
        try:
            track = int(song["track_number"])
        except (TypeError, ValueError):
            track = 0
    tie = ((track * 17) % 11) / 10.0 - 0.5  # -0.5 ~ 0.5
    score = raw + tie * 0.35
    return max(-1.0, min(1.0, score / 4.0 if abs(raw) > 0 else tie * 0.6))


def resolve_track_bpm(
    profile: Optional[dict] = None,
    song: Optional[dict] = None,
    lyrics: Optional[str] = None,
    instrument_settings: Optional[str] = None,
    *,
    variation: int = BPM_VARIATION,
) -> int:
    """프리셋 BPM을 중심으로 가사·분위기 에너지에 따라 ±variation 안에서 곡 BPM 결정.

    예: 프리셋 80 → 75~85. 이미 악기 세팅에 tempo_bpm이 있으면 그대로 사용.
    """
    stored = _bpm_from_instrument_settings(
        instrument_settings
        or (song.get("instrument_settings") if song else None)
    )
    if stored is not None:
        return stored

    base = _base_bpm(profile, song)
    energy = _emotion_energy_score(song, lyrics)
    # energy -1..1 → offset -variation..+variation
    offset = int(round(energy * variation))
    offset = max(-variation, min(variation, offset))
    return max(40, min(220, base + offset))


def bpm_range_label(base: int, variation: int = BPM_VARIATION) -> str:
    return f"{base - variation}~{base + variation}"


def _parse_bpm(
    profile: Optional[dict],
    song: Optional[dict] = None,
    lyrics: Optional[str] = None,
    instrument_settings: Optional[str] = None,
) -> int:
    """곡 생성용 BPM — 가능하면 가사·분위기 기반 ±5 변주."""
    return resolve_track_bpm(profile, song, lyrics, instrument_settings)


def _lyrics_stats(lyrics: Optional[str]) -> dict[str, int]:
    if not lyrics or not lyrics.strip():
        return {"lines": 0, "sections": 0, "chars": 0}
    sections = len(re.findall(r"\[[^\]]+\]", lyrics))
    lines = 0
    chars = 0
    for line in lyrics.splitlines():
        stripped = line.strip()
        if not stripped or re.match(r"^\[[^\]]+\]$", stripped):
            continue
        lines += 1
        chars += len(stripped)
    return {"lines": lines, "sections": sections, "chars": chars}


def _album_duration_hint_sec(album: Optional[dict]) -> Optional[int]:
    if not album:
        return None
    total_min = album.get("target_duration_min")
    track_count = album.get("track_count") or 1
    if total_min and track_count > 0:
        return max(120, int((total_min * 60) / track_count))
    return None


def _structure_blueprint_for_duration(per_track_sec: int, target_lines: int) -> str:
    """곡당 목표 줄 수에 맞춘 가사 섹션 뼈대 (동적).

    기존은 180/240초 3단계라 200초(18곡/60분)와 240초(15곡/60분)가 같은
    뼈대를 공유 → 곡 수와 무관하게 비슷한 길이의 가사가 나오는 원인.
    2026-09-10 v0.9.50 — 목표 줄 수 기반 6단계로 세분화.
    """
    if target_lines <= 26:
        return (
            "[Verse 1] 4~5줄\n[Chorus] 4줄\n[Verse 2] 4~5줄 (1절과 다른 내용)\n"
            "[Chorus] 4줄\n[Bridge] 3~4줄\n[Chorus] 4줄"
        )
    if target_lines <= 36:
        return (
            "[Verse 1] 5~6줄\n[Pre-Chorus] 2~3줄\n[Chorus] 4줄\n"
            "[Verse 2] 5~6줄 (스토리 전개)\n[Pre-Chorus] 2~3줄\n[Chorus] 4줄\n"
            "[Bridge] 3~4줄\n[Chorus] 4줄"
        )
    if target_lines <= 46:
        return (
            "[Verse 1] 5~6줄\n[Pre-Chorus] 2~3줄\n[Chorus] 4줄\n"
            "[Verse 2] 5~6줄 (스토리 전개)\n[Pre-Chorus] 2~3줄\n[Chorus] 4줄\n"
            "[Verse 3] 4~5줄 (또 다른 장면)\n[Bridge] 4~5줄\n[Chorus] 4줄\n[Outro] 2~3줄"
        )
    if target_lines <= 52:
        return (
            "[Verse 1] 6줄\n[Pre-Chorus] 3줄\n[Chorus] 4줄\n"
            "[Verse 2] 6줄\n[Pre-Chorus] 3줄\n[Chorus] 4줄\n"
            "[Verse 3] 5~6줄\n[Bridge] 4~5줄\n[Chorus] 4줄\n[Outro] 3줄"
        )
    if target_lines <= 68:
        return (
            "[Verse 1] 6~8줄\n[Pre-Chorus] 3줄\n[Chorus] 4~5줄\n"
            "[Verse 2] 6~8줄\n[Pre-Chorus] 3줄\n[Chorus] 4~5줄\n"
            "[Verse 3] 6~8줄\n[Bridge] 5~6줄\n[Chorus] 4~5줄\n"
            "[Verse 4] 4~6줄\n[Chorus] 4~5줄\n[Outro] 3~5줄"
        )
    return (
        "[Verse 1] 6~8줄\n[Pre-Chorus] 3줄\n[Chorus] 4~5줄\n"
        "[Verse 2] 6~8줄\n[Pre-Chorus] 3줄\n[Chorus] 4~5줄\n"
        "[Verse 3] 6~8줄\n[Chorus] 4~5줄\n[Bridge] 5~6줄\n"
        "[Chorus] 4~5줄\n[Verse 4] 4~6줄 (마무리 전개)\n[Chorus] 4~5줄\n"
        "[Verse 5] 4~6줄\n[Outro] 3~5줄"
    )


LYRICS_SUNO_LENGTH_RULES = """
Suno AI 길이 맞추기 규칙 (필수 — 프롬프트 시간 지정보다 중요):
- Suno는 **가사 줄 수·섹션 수**로 곡 길이를 맞춤. 목표 가사 줄 수를 반드시 채울 것.
- 목표 최소~최대 줄 수 범위를 지킬 것 — **최대 줄 수 초과 금지** (앨범 총 러닝타임이 목표를 초과하는 원인).
- 시간을 채우려고 2절 이후 **같은 가사 전체를 처음부터 반복**하지 말 것 (무의미한 루프 금지).
- 후렴만 짧게 여러 번 반복하지 말 것.
- 대신 Verse / Pre-Chorus / Bridge / Outro마다 **새 가사**로 스토리를 늘릴 것.
- Chorus 후렴 가사는 동일해도 되지만, Verse는 절마다 내용이 달라야 함.
- 필요 시 [Instrumental] 태그만 단독 줄로 넣을 수 있음 (가사 줄 수에는 포함하지 않음)."""


def compute_track_lyrics_target(
    album: Optional[dict],
    profile: Optional[dict] = None,
) -> Optional[dict[str, int | str]]:
    """앨범 곡수·런닝타임 → 곡당 Suno용 목표 가사 분량."""
    per_track_sec = _album_duration_hint_sec(album)
    if not per_track_sec:
        return None

    total_min = album.get("target_duration_min") if album else None
    track_count = (album or {}).get("track_count") or 1
    bpm = _parse_bpm(profile)
    sec_per_line = 3.2 * (85 / bpm)
    vocal_budget = max(90, per_track_sec - 48)
    target_mid = int(vocal_budget / sec_per_line)
    target_lines_min = max(24, int(target_mid * 0.88))
    target_lines_max = max(target_lines_min + 10, int(target_mid * 1.12))
    blueprint = _structure_blueprint_for_duration(per_track_sec, target_mid)

    return {
        "per_track_sec": per_track_sec,
        "per_track_label": _format_duration(per_track_sec),
        "target_lines_min": target_lines_min,
        "target_lines_max": target_lines_max,
        "target_lines_mid": target_mid,
        "structure_blueprint": blueprint,
        "album_total_min": total_min or 0,
        "album_track_count": track_count,
    }


def lyrics_length_status(
    lyrics: Optional[str],
    album: Optional[dict],
    profile: Optional[dict] = None,
) -> dict[str, int | str | bool | None]:
    """현재 가사가 앨범 목표 분량에 맞는지."""
    target = compute_track_lyrics_target(album, profile)
    stats = _lyrics_stats(lyrics)
    if not target:
        return {
            "target_lyrics_lines_min": None,
            "target_lyrics_lines_max": None,
            "actual_lyrics_lines": stats["lines"] or None,
            "lyrics_length_ok": None,
            "lyrics_length_status": "none" if not stats["lines"] else "unknown",
        }

    lines = stats["lines"]
    min_l = int(target["target_lines_min"])
    max_l = int(target["target_lines_max"])
    if lines <= 0:
        status = "none"
        ok = False
    elif lines < min_l:
        status = "short"
        ok = False
    elif lines > int(max_l * 1.1):
        status = "long"
        ok = False
    else:
        status = "ok"
        ok = True

    return {
        "target_lyrics_lines_min": min_l,
        "target_lyrics_lines_max": max_l,
        "actual_lyrics_lines": lines or None,
        "lyrics_length_ok": ok,
        "lyrics_length_status": status,
    }


def lyrics_meets_target(
    lyrics: Optional[str],
    album: Optional[dict],
    profile: Optional[dict] = None,
) -> bool:
    info = lyrics_length_status(lyrics, album, profile)
    return bool(info.get("lyrics_length_ok"))


def build_lyrics_duration_prompt_block(
    album: Optional[dict],
    profile: Optional[dict] = None,
) -> str:
    """가사 생성 AI용 — 곡당 시간 배분 + 목표 줄 수 + 섹션 뼈대."""
    target = compute_track_lyrics_target(album, profile)
    if not target:
        return ""

    per_track = target["per_track_label"]
    per_sec = target["per_track_sec"]
    min_l = target["target_lines_min"]
    max_l = target["target_lines_max"]
    mid_l = target["target_lines_mid"]
    total_min = target["album_total_min"]
    track_count = target["album_track_count"]
    blueprint = target["structure_blueprint"]

    return (
        f"\n## 앨범 길이 → 이 곡 가사 분량 (필수)\n"
        f"- 앨범 전체 {total_min}분 / {track_count}곡 → **이 곡 목표 약 {per_track} ({per_sec}초)**\n"
        f"- Suno는 프롬프트 시간이 아니라 **가사 줄 수**로 길이를 맞춤\n"
        f"- **이 곡 가사 목표: {min_l}~{max_l}줄** (권장 {mid_l}줄 전후, 섹션 태그 줄 제외)\n"
        f"- **{max_l}줄 초과 절대 금지** — 넘치면 앨범 총 러닝타임({total_min}분)이 초과됨. 분량은 줄 수로 통제\n"
        f"- 짧은 2분 30초 팝 한 세트(Verse+Chorus 1~2회)로 끝내지 말 것\n"
        f"- 아래 뼈대를 참고해 섹션·줄 수를 채울 것:\n{blueprint}\n"
        f"{LYRICS_SUNO_LENGTH_RULES}"
    )


def format_album_lyrics_duration_context(album: Optional[dict]) -> str:
    """하위 호환 alias."""
    return build_lyrics_duration_prompt_block(album)


def estimate_track_duration_sec(
    lyrics: Optional[str],
    profile: Optional[dict] = None,
    album: Optional[dict] = None,
    song: Optional[dict] = None,
) -> int:
    """트랙 길이(초). 앨범 목표 배분 기본, 단 가사 분량이 배분을 15% 이상 초과하면 실측 반영.

    기존은 목표가 있으면 가사 분량과 무관하게 항상 배분값을 반환해
    실제 Suno 결과가 길어져도 화면에서 알 수 없었다 (v0.9.50).
    """
    album_hint = _album_duration_hint_sec(album)
    if album_hint:
        stats = _lyrics_stats(lyrics)
        if stats["lines"] > 0:
            lyric_based = _lyrics_based_duration_sec(stats, _parse_bpm(profile, song, lyrics))
            # 가사 기반 추정이 배분값을 15% 이상 초과하면 실측 우선 (넘침 경고 목적)
            if lyric_based > album_hint * 1.15:
                return lyric_based
        return album_hint

    bpm = _parse_bpm(
        profile,
        song,
        lyrics,
        song.get("instrument_settings") if song else None,
    )
    stats = _lyrics_stats(lyrics)
    if stats["lines"] > 0:
        return _lyrics_based_duration_sec(stats, bpm)

    return 210


def _lyrics_based_duration_sec(stats: dict, bpm: int) -> int:
    """가사 줄 수·섹션 수 기반 트랙 길이(초) 추정."""
    ref_bpm = 85
    sec_per_line = 3.25 * (ref_bpm / max(40, bpm))
    avg_chars = stats["chars"] / max(stats["lines"], 1)
    sec_per_line *= min(1.35, 0.85 + avg_chars / 40)

    vocal_sec = stats["lines"] * sec_per_line
    section_count = max(stats["sections"], 1)
    intro_sec = 10 + min(8, section_count * 2)
    outro_sec = 12 + min(10, section_count * 2)
    interlude_sec = max(0, section_count - 1) * (5.5 * ref_bpm / max(40, bpm))
    lyric_based = int(vocal_sec + intro_sec + outro_sec + interlude_sec)
    return max(90, min(420, lyric_based))


def get_track_duration_info(
    lyrics: Optional[str],
    profile: Optional[dict] = None,
    album: Optional[dict] = None,
    song: Optional[dict] = None,
) -> dict[str, int | str]:
    """곡 페이지·프롬프트용 런닝타임 추정."""
    duration_sec = estimate_track_duration_sec(lyrics, profile, album, song)
    stats = _lyrics_stats(lyrics)
    album_hint = _album_duration_hint_sec(album)
    if album_hint:
        source = "album"
    elif stats["lines"] > 0:
        source = "lyrics"
    else:
        source = "default"
    bpm = _parse_bpm(
        profile,
        song,
        lyrics,
        song.get("instrument_settings") if song else None,
    )
    base = _base_bpm(profile, song)
    return {
        "estimated_duration_sec": duration_sec,
        "estimated_duration_label": _format_duration(duration_sec),
        "estimated_duration_source": source,
        "tempo_bpm": bpm,
        "tempo_bpm_base": base,
        "tempo_bpm_range": bpm_range_label(base),
        **lyrics_length_status(lyrics, album, profile),
    }


def build_duration_block(
    lyrics: Optional[str],
    profile: Optional[dict] = None,
    album: Optional[dict] = None,
    song: Optional[dict] = None,
    instrument_settings: Optional[str] = None,
) -> str:
    inst = instrument_settings or (song.get("instrument_settings") if song else None)
    bpm = _parse_bpm(profile, song, lyrics, inst)
    base = _base_bpm(profile, song)
    duration_sec = estimate_track_duration_sec(lyrics, profile, album, song)
    stats = _lyrics_stats(lyrics)
    dur = _format_duration(duration_sec)
    lines = [
        f"EXACT target total duration: {dur} ({duration_sec}s) — mandatory, do NOT shorten",
        f"EXACT Tempo for THIS track: {bpm} BPM "
        f"(base preset {base} BPM, allowed range {bpm_range_label(base)} — do NOT use other BPM)",
        f"Put exactly \"{bpm} BPM\" and \"total length ~{dur} ({duration_sec}s)\" in [Overview] and [Mix].",
        "Ignore lyric line count for duration — extend with instrumental sections to fill time.",
    ]
    if stats["lines"] > 0:
        lines.insert(
            2,
            f"Lyrics reference only: {stats['lines']} sung lines, "
            f"{stats['sections']} section tags (NOT the song length).",
        )
    else:
        lines.insert(2, "No lyrics yet — duration from album target or default.")
    return "\n".join(lines)


def _estimate_duration_sec(album: Optional[dict]) -> int:
    return estimate_track_duration_sec(None, album=album)


def _vocal_style_for_prompt(profile: Optional[dict], mix_user: str) -> str:
    if mix_user:
        text = mix_user.strip()
        if "혼성" in text or "듀오" in text:
            if "남녀" in text:
                return "male-female duet vocals"
            return "duet vocals"
        return text
    return (profile or {}).get("vocal_style") or "soft intimate vocals"


def _mix_notes_from_settings(instrument_settings: Optional[str]) -> str:
    parsed = parse_settings(instrument_settings)
    if not parsed:
        return ""
    return str(parsed.get("mix_notes") or "").strip()


def _instrument_names(instrument_settings: Optional[str], profile: Optional[dict]) -> list[str]:
    names: list[str] = []
    parsed = parse_settings(instrument_settings)
    if parsed:
        for item in parsed.get("instruments", []):
            name = item.get("name_en") or item.get("name")
            if name:
                names.append(str(name))
    if not names and profile and profile.get("instruments"):
        for part in re.split(r"[,，、/|]", str(profile["instruments"])):
            part = part.strip()
            if part:
                names.append(part)
    return names[:8]


_DRUM_HINT_RE = re.compile(
    r"(?i)\b("
    r"drums?|drum\s*kit|drumkit|percussion|percussive|"
    r"kick(?:\s*drum)?|snare|hi-?hats?|cymbals?|tom(?:s|[- ]toms?)?|"
    r"beat\b|beats\b|backbeat|drum\s*groove|full\s*band"
    r")\b"
)
_NO_DRUM_PHRASE = "no drums, no percussion"


def _allows_drums(names: list[str]) -> bool:
    blob = " ".join(names).lower()
    keys = (
        "drum", "percussion", "kick", "snare", "hi-hat", "hihat",
        "cymbal", "드럼", "퍼커션", "킥", "스네어", "하이햇",
    )
    return any(k in blob for k in keys)


def _strip_drum_language(text: str) -> str:
    """목록에 드럼이 없을 때 드럼·키트 암시 표현을 제거."""
    if not text:
        return text
    cleaned = _DRUM_HINT_RE.sub("", text)
    cleaned = re.sub(r"\bwith\s+and\b", "with", cleaned, flags=re.I)
    cleaned = re.sub(r"\band\s+and\b", "and", cleaned, flags=re.I)
    cleaned = re.sub(r"\band\s+create\b", "create", cleaned, flags=re.I)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = re.sub(r"\s+,", ",", cleaned)
    cleaned = re.sub(r",\s*,+", ",", cleaned)
    cleaned = re.sub(r"\s+\.", ".", cleaned)
    return cleaned.strip(" ,;")


def _append_locked_clause(text: str, clause: str, max_len: int = 160) -> str:
    """필수 구절을 우선 보존하고, 앞부분 본문만 줄인다."""
    clause = " ".join(clause.split()).strip(" .,")
    if not clause:
        return _truncate_sentence(text, max_len)
    if clause.lower() in text.lower():
        return _truncate_sentence(text, max_len)
    # 필수 구절은 자르지 않음
    room = max_len - len(clause) - 2
    if room < 24:
        return clause if len(clause) <= max_len else clause[: max_len - 1].rstrip() + "."
    base = " ".join(text.split()).rstrip("., ")
    if len(base) > room:
        cut = base[: room - 1].rstrip(" ,;")
        if " " in cut:
            cut = cut.rsplit(" ", 1)[0]
        base = cut.rstrip("., ")
    return f"{base}. {clause}."


def enforce_instrument_lock(
    text: str,
    instrument_settings: Optional[str],
    profile: Optional[dict] = None,
) -> str:
    """선택 악기만 쓰이도록 프롬프트를 사후 보정 (없는 드럼 암시 제거 등)."""
    names = _instrument_names(instrument_settings, None)
    if not names:
        return text

    inst_str = ", ".join(names)
    allow_drums = _allows_drums(names)
    parsed = parse_sections(text)
    if not parsed:
        body = text if allow_drums else _strip_drum_language(text)
        lock = f"Use only: {inst_str}"
        if not allow_drums:
            lock += f"; {_NO_DRUM_PHRASE}"
        return _append_locked_clause(body, lock, 240)

    for key, value in list(parsed.items()):
        if not allow_drums:
            parsed[key] = _truncate_sentence(_strip_drum_language(value), 110)

    def _name_hit(name: str, hay: str) -> bool:
        n = name.lower().strip()
        t = hay.lower()
        if n in t:
            return True
        tokens = [tok for tok in re.split(r"[\s/\-]+", n) if len(tok) >= 4]
        return any(tok in t for tok in tokens)

    overview = parsed.get("overview", "")
    named_hits = sum(1 for n in names if _name_hit(n, overview))
    overview_lock_parts: list[str] = []
    if named_hits < max(1, (len(names) + 1) // 2):
        overview_lock_parts.append(f"Instruments: {inst_str}")
    if not allow_drums and _NO_DRUM_PHRASE not in overview.lower():
        overview_lock_parts.append(_NO_DRUM_PHRASE)
    if overview_lock_parts:
        overview = _append_locked_clause(
            overview, "; ".join(overview_lock_parts), 160
        )
    parsed["overview"] = overview

    mix = parsed.get("mix_notes", "")
    mix_lock_parts: list[str] = []
    if "use only" not in mix.lower():
        mix_lock_parts.append(f"Use only: {inst_str}")
    if not allow_drums and _NO_DRUM_PHRASE not in mix.lower():
        mix_lock_parts.append(_NO_DRUM_PHRASE)
    if mix_lock_parts:
        mix = _append_locked_clause(mix, "; ".join(mix_lock_parts), 160)
    parsed["mix_notes"] = mix

    return format_sections(parsed)


def finalize_suno_prompt(
    text: str,
    duration_sec: int,
    max_chars: int = SUNO_PROMPT_MAX_CHARS,
    instrument_settings: Optional[str] = None,
    profile: Optional[dict] = None,
) -> str:
    """생성된 Suno 프롬프트에 목표 런닝타임·악기 잠금을 최종 보정."""
    cleaned = enforce_duration_in_prompt_text(text.strip(), duration_sec)
    if instrument_settings:
        cleaned = enforce_instrument_lock(cleaned, instrument_settings, profile)
    return enforce_suno_limit(cleaned, max_chars)


def _lyrics_has_section(lyrics: str, tag: str) -> bool:
    return bool(re.search(rf"\[{tag}\]", lyrics, re.I))


def _truncate_sentence(text: str, max_len: int) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_len:
        return cleaned
    cut = cleaned[: max_len - 1].rstrip(" ,;")
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(".,;") + "."


def _parse_prompt_json(raw: str) -> Optional[dict[str, str]]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
    try:
        data = json.loads(text.strip())
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    keys = tuple(k for k, _ in SECTION_SPECS)
    if not all(k in data and str(data[k]).strip() for k in keys):
        return None
    return {k: _truncate_sentence(str(data[k]).strip(), 120) for k in keys}


def _replace_duration_in_text(
    text: str,
    dur: str,
    duration_sec: int,
    *,
    fallback_suffix: str = "",
) -> str:
    """문장 안의 잘못된 mm:ss 길이를 목표 길이로 교체."""
    if not text.strip():
        return fallback_suffix.lstrip(", ") if fallback_suffix else text

    dur_full = f"~{dur} ({duration_sec}s)"
    patterns = [
        (
            r"(?i)(total\s+(?:length|duration)|track\s+length)\s*:?\s*~?\s*\d{1,2}:\d{2}(\s*\(\d+s\))?",
            rf"\1 {dur_full}",
        ),
        (
            r"(?i)(keep\s+total\s+duration|total\s+duration)\s*:?\s*~?\s*\d{1,2}:\d{2}(\s*\(\d+s\))?",
            rf"\1 {dur_full}",
        ),
        (
            r"(?i)(final\s+~?\d{1,2}%?\s+of)\s+~?\d{1,2}:\d{2}",
            rf"\1 ~{dur}",
        ),
        (
            r"(?i)(~?\d{1,2}%?\s+of)\s+~?\d{1,2}:\d{2}",
            rf"\1 ~{dur}",
        ),
    ]
    updated = text
    for pattern, repl in patterns:
        updated = re.sub(pattern, repl, updated)

    if updated == text and re.search(r"\b\d{1,2}:\d{2}\b", text):
        updated = re.sub(r"\b\d{1,2}:\d{2}\b", dur, text, count=1)
    elif updated == text and fallback_suffix:
        updated = text.rstrip("., ") + fallback_suffix

    if f"({duration_sec}s)" not in updated and re.search(rf"\b{re.escape(dur)}\b", updated):
        updated = re.sub(rf"\b{re.escape(dur)}\b", dur_full.replace("~", ""), updated, count=1)
    return updated


def enforce_target_duration_in_sections(
    data: dict[str, str],
    duration_sec: int,
) -> dict[str, str]:
    """AI가 가사 기준으로 짧게 쓴 프롬프트 섹션에 앨범 목표 길이를 강제 반영."""
    dur = _format_duration(duration_sec)
    dur_full = f"~{dur} ({duration_sec}s)"
    result = dict(data)

    overview = result.get("overview", "")
    result["overview"] = _truncate_sentence(
        _replace_duration_in_text(
            overview,
            dur,
            duration_sec,
            fallback_suffix=f", total length {dur_full}.",
        ),
        120,
    )

    for key, fallback in (
        ("intro", f"Sparse opening, no vocals, ~10% of {dur}."),
        ("mix_notes", f"Keep total length {dur_full} at consistent BPM."),
        ("outro", f"Final ~15% of {dur}: gentle fade and end."),
    ):
        if key in result:
            result[key] = _truncate_sentence(
                _replace_duration_in_text(
                    result[key],
                    dur,
                    duration_sec,
                    fallback_suffix=fallback if not result[key].strip() else f", target ~{dur}.",
                ),
                120,
            )

    return result


def enforce_duration_in_prompt_text(text: str, duration_sec: int) -> str:
    """구간 파싱 가능한 Suno 프롬프트 본문에 목표 길이를 주입."""
    parsed = parse_sections(text)
    if parsed:
        return format_sections(enforce_target_duration_in_sections(parsed, duration_sec))

    dur = _format_duration(duration_sec)
    dur_full = f"~{dur} ({duration_sec}s)"
    lines = []
    for line in text.splitlines():
        header = line[:20].lower()
        if line.startswith("[") and any(
            tag in header for tag in ("overview", "mix", "intro", "outro")
        ):
            lines.append(_replace_duration_in_text(line, dur, duration_sec))
        else:
            lines.append(line)
    merged = "\n".join(lines)
    if dur not in merged:
        merged = f"[Overview] total length {dur_full}.\n" + merged
    return merged


def format_sections(data: dict[str, str]) -> str:
    return "\n".join(f"{label} {data[key]}" for key, label in SECTION_SPECS)


def parse_sections(text: str) -> Optional[dict[str, str]]:
    pattern = re.compile(
        r"\[(Overview|Intro|Verse(?:\s*/\s*Main body)?|Build(?:\s*&\s*Pre-Chorus)?|"
        r"Chorus(?:\s*/\s*Climax)?|Bridge|Outro(?:\s*/\s*Ending)?|Mix(?:\s*Notes)?)\]\s*",
        re.I,
    )
    matches = list(pattern.finditer(text))
    if len(matches) < 3:
        return None

    key_map = {
        "overview": "overview",
        "intro": "intro",
        "verse": "verse_main",
        "build": "build",
        "chorus": "chorus_climax",
        "bridge": "bridge",
        "outro": "outro",
        "mix": "mix_notes",
    }
    parsed: dict[str, str] = {}
    for i, match in enumerate(matches):
        header = match.group(1).lower().split("/")[0].split("&")[0].strip()
        key = key_map.get(header.split()[0])
        if not key:
            continue
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        value = " ".join(text[start:end].split())
        if value:
            parsed[key] = value
    return parsed or None


def enforce_suno_limit(text: str, max_chars: int = SUNO_PROMPT_MAX_CHARS) -> str:
    cleaned = text.strip()
    if len(cleaned) <= max_chars:
        return cleaned

    parsed = parse_sections(cleaned)
    if not parsed:
        return _truncate_sentence(cleaned, max_chars)

    for _ in range(40):
        formatted = format_sections(parsed)
        if len(formatted) <= max_chars:
            return formatted
        longest = max(parsed, key=lambda k: len(parsed[k]))
        parsed[longest] = _truncate_sentence(
            parsed[longest], max(24, len(parsed[longest]) - 20)
        )

    formatted = format_sections(parsed)
    if len(formatted) <= max_chars:
        return formatted
    return formatted[: max_chars - 3].rstrip() + "..."


def is_detailed_suno_prompt(text: str) -> bool:
    cleaned = text.strip()
    if len(cleaned) < 120 or len(cleaned) > SUNO_PROMPT_MAX_CHARS:
        return False
    markers = ("[Overview]", "[Intro]", "[Chorus", "[Outro", "[Verse")
    if sum(1 for m in markers if m in cleaned) >= 2:
        return True
    if "," in cleaned and "[" not in cleaned and len(cleaned) < 250:
        return False
    return len(cleaned) >= 200


def build_template_fallback(
    profile: Optional[dict],
    album: Optional[dict],
    song: dict,
    lyrics: Optional[str],
    instrument_settings: Optional[str],
) -> str:
    """AI 실패 시 가사·악기·프로필로 1000자 이내 구간 프롬프트 생성."""
    duration_sec = estimate_track_duration_sec(lyrics, profile, album, song)
    dur = _format_duration(duration_sec)
    inst = _instrument_names(instrument_settings, profile)
    # 선택 악기가 있으면 그대로만 사용 — drums 등 임의 추가 금지
    if inst:
        inst_str = ", ".join(inst)
    else:
        inst_str = "acoustic guitar, piano, bass"

    genre = (profile or {}).get("genre") or "acoustic pop"
    mood = song.get("mood") or (profile or {}).get("mood") or (album or {}).get("mood") or "warm"
    bpm = _parse_bpm(profile, song, lyrics, instrument_settings)
    theme = song.get("theme") or ""
    production = (profile or {}).get("production_style") or "warm organic"

    lead = inst[0] if inst else "acoustic guitar"
    second = inst[1] if len(inst) > 1 else (inst[0] if inst else "piano")
    bass = next((n for n in inst if "bass" in n.lower()), None)
    has_drums = _allows_drums(inst)
    groove = (
        next((n for n in inst if "drum" in n.lower() or "percussion" in n.lower()), None)
        if has_drums
        else (bass or second)
    )

    has_bridge = bool(lyrics and _lyrics_has_section(lyrics, "Bridge"))
    bridge_note = (
        f"Strip to voice and sparse {lead}, then rebuild with {inst_str}."
        if has_bridge
        else f"Brief instrumental break featuring {lead} and {second}."
    )

    mix_user = _mix_notes_from_settings(instrument_settings)
    vocal = _vocal_style_for_prompt(profile, mix_user)
    no_drum = "" if has_drums else f" {_NO_DRUM_PHRASE}."

    data = {
        "overview": (
            f"{genre}, {mood}, {bpm} BPM, {vocal}, total length ~{dur} ({duration_sec}s). "
            f"Instruments: {inst_str}.{no_drum} {production}."
            + (f" Theme: {theme}." if theme else "")
        ),
        "intro": f"0:00 start, sparse {lead}, no vocals, ~10% of {dur} intro.",
        "verse_main": (
            f"{lead} leads, {second} support"
            + (f", {bass} pulse" if bass and bass not in (lead, second) else "")
            + f", {vocal}."
        ),
        "build": f"Add layers before chorus with {second} and {groove}, rising energy.",
        "chorus_climax": (
            f"Peak with {inst_str}, {vocal}, hook forward, warm reverb on voice."
        ),
        "bridge": bridge_note,
        "outro": (
            f"Final ~15% of {dur}: thin to {lead}"
            + (f" and {bass}" if bass else "")
            + ", fade vocals, gentle end."
        ),
        "mix_notes": (
            (f"{mix_user} " if mix_user else "")
            + f"Total length ~{dur} at {bpm} BPM, vocals upfront, use only: {inst_str}."
            + ("" if has_drums else f" {_NO_DRUM_PHRASE}.")
        ),
    }
    for key in data:
        data[key] = _truncate_sentence(data[key], 110)
    return enforce_suno_limit(format_sections(data))


def _format_instruments_block(instrument_settings: Optional[str]) -> str:
    """곡별 악기 세팅을 AI가 따르기 쉬운 목록으로 변환."""
    parsed = parse_settings(instrument_settings)
    if not parsed or not parsed.get("instruments"):
        return (instrument_settings or "").strip()

    names = _instrument_names(instrument_settings, None)
    allow_drums = _allows_drums(names)
    lines = [
        "CLOSED instrument set — use ONLY these names in every section "
        "(do not invent drums or other instruments):",
        f"Allowed: {', '.join(names)}",
    ]
    if not allow_drums:
        lines.append(
            "FORBIDDEN unless listed: drums, drum kit, percussion, kick, snare, "
            "hi-hat, cymbals, full band beat. Write 'no drums, no percussion'."
        )
    for item in parsed["instruments"]:
        name = item.get("name_en") or item.get("name") or ""
        if not name:
            continue
        bits = [str(name)]
        if item.get("role"):
            bits.append(f"role={item['role']}")
        if item.get("tone"):
            bits.append(f"tone={item['tone']}")
        if item.get("texture"):
            bits.append(f"texture={item['texture']}")
        if item.get("notes"):
            bits.append(str(item["notes"]))
        lines.append("- " + "; ".join(bits))
    mix = str(parsed.get("mix_notes") or "").strip()
    if mix:
        lines.append(f"Mix notes: {mix}")
    tempo = parsed.get("tempo_bpm")
    if tempo is not None:
        lines.append(f"Tempo for THIS track: {tempo} BPM (use exactly this)")
    return "\n".join(lines)


def build_user_prompt_for_json(
    context: str,
    album: dict,
    lyrics: Optional[str],
    instrument_settings: Optional[str],
    additional: Optional[str],
    profile: Optional[dict] = None,
    song: Optional[dict] = None,
) -> str:
    duration_block = build_duration_block(
        lyrics, profile, album, song, instrument_settings
    )
    parts = [
        context,
        f"\n## Target duration (required)\n{duration_block}",
        f"\n## Character limit\nTotal formatted prompt MUST be under {SUNO_PROMPT_MAX_CHARS} characters.",
        "\n## Per-track variation\n"
        "Match arrangement to THIS track's lyric emotion and mood. "
        "Do not reuse a generic album arrangement.",
    ]
    if lyrics:
        parts.append(f"\n## Lyrics (match section structure + emotion)\n{lyrics}")
    inst_block = _format_instruments_block(instrument_settings) if instrument_settings else ""
    if inst_block:
        parts.append(f"\n## Instruments (assign to each section)\n{inst_block}")
    song_notes = _mix_notes_from_settings(instrument_settings)
    if song_notes:
        parts.insert(
            1,
            "\n## CRITICAL — User directions (highest priority, MUST follow)\n"
            f"{song_notes}\n"
            "Reflect these in [Overview] vocal style (translate Korean to natural English for Suno, "
            "e.g. 남녀 혼성듀오 → male-female duet vocals). "
            "Also repeat in verse/chorus lines when about vocals or mix.",
        )
    parts.append(
        "\nReturn JSON only with keys: overview, intro, verse_main, build, "
        "chorus_climax, bridge, outro, mix_notes. One short sentence per key."
    )
    if additional:
        parts.append(f"\nAdditional: {additional}")
    return "".join(parts)
