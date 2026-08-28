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
- overview: genre, mood, BPM, vocal style, exact total duration mm:ss, core instruments
- intro: start feel, lead instruments, no vocals
- verse_main: verse instruments, rhythm, vocal mix
- build: pre-chorus layering
- chorus_climax: peak arrangement, hook, effects
- bridge: contrast or variation
- outro: ending, fade/stop
- mix_notes: balance, keep BPM, keep total duration, use only listed instruments

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


def _parse_bpm(profile: Optional[dict], song: Optional[dict] = None) -> int:
    for src in (profile, song):
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


def format_album_lyrics_duration_context(album: Optional[dict]) -> str:
    """가사 생성 프롬프트용 앨범 길이 안내."""
    if not album:
        return ""
    total_min = album.get("target_duration_min")
    track_count = album.get("track_count") or 1
    if not total_min or track_count <= 0:
        return ""
    per_track_sec = _album_duration_hint_sec(album) or 210
    per_track = _format_duration(per_track_sec)
    # 대략 3초/줄 기준 가사 줄 수 힌트
    target_lines = max(28, int((per_track_sec - 35) / 3.0))
    return (
        f"\n## 앨범 길이 목표 (필수)\n"
        f"- 전체 {total_min}분 / {track_count}곡 → **곡당 약 {per_track} ({per_track_sec}초)**\n"
        f"- 일반 2분 30초짜리 짧은 팝 구조가 아니라, 위 길이에 맞게 가사 분량을 잡을 것\n"
        f"- 곡당 가사 약 {target_lines}줄 전후 (Verse 2~3회, Chorus 2~3회, Bridge, 필요 시 [Instrumental] 태그)\n"
        f"- 같은 후렴만 짧게 반복하지 말고, 섹션을 늘려 전체 재생 시간이 목표에 가깝게"
    )


def estimate_track_duration_sec(
    lyrics: Optional[str],
    profile: Optional[dict] = None,
    album: Optional[dict] = None,
    song: Optional[dict] = None,
) -> int:
    """트랙 길이(초). 앨범 목표가 있으면 항상 곡당 배분값 우선, 없으면 가사 분량 추정."""
    album_hint = _album_duration_hint_sec(album)
    if album_hint:
        return album_hint

    bpm = _parse_bpm(profile, song)
    stats = _lyrics_stats(lyrics)
    if stats["lines"] > 0:
        ref_bpm = 85
        sec_per_line = 3.25 * (ref_bpm / bpm)
        avg_chars = stats["chars"] / stats["lines"]
        sec_per_line *= min(1.35, 0.85 + avg_chars / 40)

        vocal_sec = stats["lines"] * sec_per_line
        section_count = max(stats["sections"], 1)
        intro_sec = 10 + min(8, section_count * 2)
        outro_sec = 12 + min(10, section_count * 2)
        interlude_sec = max(0, section_count - 1) * (5.5 * (ref_bpm / bpm))
        lyric_based = int(vocal_sec + intro_sec + outro_sec + interlude_sec)
        return max(90, min(420, lyric_based))

    return 210


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
    return {
        "estimated_duration_sec": duration_sec,
        "estimated_duration_label": _format_duration(duration_sec),
        "estimated_duration_source": source,
    }


def build_duration_block(
    lyrics: Optional[str],
    profile: Optional[dict] = None,
    album: Optional[dict] = None,
    song: Optional[dict] = None,
) -> str:
    bpm = _parse_bpm(profile, song)
    duration_sec = estimate_track_duration_sec(lyrics, profile, album, song)
    stats = _lyrics_stats(lyrics)
    dur = _format_duration(duration_sec)
    lines = [
        f"EXACT target total duration: {dur} ({duration_sec}s) — mandatory, do NOT shorten",
        f"Tempo: {bpm} BPM (must stay consistent)",
        f"Put exactly \"total length ~{dur} ({duration_sec}s)\" in [Overview] and [Mix].",
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


def finalize_suno_prompt(
    text: str,
    duration_sec: int,
    max_chars: int = SUNO_PROMPT_MAX_CHARS,
) -> str:
    """생성된 Suno 프롬프트에 목표 런닝타임을 최종 보정."""
    cleaned = enforce_duration_in_prompt_text(text.strip(), duration_sec)
    return enforce_suno_limit(cleaned, max_chars)


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
    inst_str = ", ".join(inst) if inst else "acoustic guitar, piano, light drums, bass"

    genre = (profile or {}).get("genre") or "acoustic pop"
    mood = song.get("mood") or (profile or {}).get("mood") or (album or {}).get("mood") or "warm"
    bpm = _parse_bpm(profile, song)
    theme = song.get("theme") or ""
    production = (profile or {}).get("production_style") or "warm organic"

    lead = inst[0] if inst else "acoustic guitar"
    second = inst[1] if len(inst) > 1 else "piano"
    rhythm = next((n for n in inst if "drum" in n.lower()), "light drums")
    bass = next((n for n in inst if "bass" in n.lower()), "bass")

    has_bridge = bool(lyrics and _lyrics_has_section(lyrics, "Bridge"))
    bridge_note = (
        "Strip to voice and sparse guitar, then rebuild to final chorus."
        if has_bridge
        else "Brief instrumental break with muted drums and featured melody."
    )

    mix_user = _mix_notes_from_settings(instrument_settings)
    vocal = _vocal_style_for_prompt(profile, mix_user)

    data = {
        "overview": (
            f"{genre}, {mood}, {bpm} BPM, {vocal}, total length ~{dur} ({duration_sec}s). "
            f"Instruments: {inst_str}. {production}."
            + (f" Theme: {theme}." if theme else "")
        ),
        "intro": f"0:00 start, sparse {lead}, no vocals, ~10% of {dur} intro.",
        "verse_main": (
            f"{lead} leads, {second} harmony, light {rhythm} and {bass}, {vocal}."
        ),
        "build": f"Add layers before chorus: fuller harmony, stronger {rhythm}, rising energy.",
        "chorus_climax": (
            f"Full band ({inst_str}), {vocal}, hook forward, warm reverb on voice."
        ),
        "bridge": bridge_note,
        "outro": f"Final ~15% of {dur}: drop drums/bass, fade {lead} and vocals, gentle end.",
        "mix_notes": (
            (f"{mix_user} " if mix_user else "")
            + f"Total length ~{dur} at {bpm} BPM, vocals upfront, use only: {inst_str}."
        ),
    }
    for key in data:
        data[key] = _truncate_sentence(data[key], 110)
    return enforce_suno_limit(format_sections(data))


def build_user_prompt_for_json(
    context: str,
    album: dict,
    lyrics: Optional[str],
    instrument_settings: Optional[str],
    additional: Optional[str],
    profile: Optional[dict] = None,
    song: Optional[dict] = None,
) -> str:
    duration_block = build_duration_block(lyrics, profile, album, song)
    parts = [
        context,
        f"\n## Target duration (required)\n{duration_block}",
        f"\n## Character limit\nTotal formatted prompt MUST be under {SUNO_PROMPT_MAX_CHARS} characters.",
    ]
    if lyrics:
        parts.append(f"\n## Lyrics (match section structure)\n{lyrics}")
    if instrument_settings:
        parts.append(f"\n## Instruments (assign to each section)\n{instrument_settings}")
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
