"""OpenRouter API client for multi-model AI generation."""

import json
import re
from typing import Optional

import httpx

from app.config import settings
from app.services.ai_client import AIClient

OPENROUTER_BASE = "https://openrouter.ai/api/v1"


class OpenRouterClient:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.openrouter_api_key

    async def chat(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
    ) -> str:
        if not self.api_key:
            raise ValueError(
                "OpenRouter API 키가 설정되지 않았습니다. 설정 > 사용자 정보에서 API 키를 입력하세요."
            )

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{OPENROUTER_BASE}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "http://localhost:8765",
                    "X-Title": "Suno Helper",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": temperature,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

    async def list_models(self) -> list[dict]:
        if not self.api_key:
            return []

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{OPENROUTER_BASE}/models",
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            response.raise_for_status()
            return response.json().get("data", [])


def _build_music_context(
    profile: Optional[dict] = None,
    album: Optional[dict] = None,
    song: Optional[dict] = None,
    reference_song: Optional[dict] = None,
) -> str:
    parts = []

    if profile:
        parts.append("## 음악 프로필 (일관된 스타일)")
        if profile.get("genre"):
            parts.append(f"- 장르: {profile['genre']}")
        if profile.get("mood"):
            parts.append(f"- 분위기: {profile['mood']}")
        if profile.get("tempo_bpm"):
            parts.append(f"- 템포: {profile['tempo_bpm']} BPM")
        if profile.get("key_signature"):
            parts.append(f"- 조성: {profile['key_signature']}")
        if profile.get("vocal_style"):
            parts.append(f"- 보컬 스타일: {profile['vocal_style']}")
        if profile.get("instruments"):
            parts.append(f"- 악기: {profile['instruments']}")
        if profile.get("production_style"):
            parts.append(f"- 프로덕션: {profile['production_style']}")
        if profile.get("reference_artists"):
            parts.append(f"- 참고 아티스트: {profile['reference_artists']}")
        if profile.get("extra_notes"):
            parts.append(f"- 추가 메모: {profile['extra_notes']}")

    if album:
        parts.append("\n## 앨범 정보")
        parts.append(f"- 앨범명: {album.get('title', '')}")
        if album.get("concept"):
            parts.append(f"- 컨셉/기획: {album['concept']}")
        if album.get("mood"):
            parts.append(f"- 앨범 분위기: {album['mood']}")
        total_min = album.get("target_duration_min")
        track_count = album.get("track_count")
        if total_min and track_count:
            per_sec = max(120, int((total_min * 60) / track_count))
            m, s = divmod(per_sec, 60)
            parts.append(f"- 목표: 전체 {total_min}분 / {track_count}곡 (곡당 약 {m}:{s:02d})")

    if song:
        parts.append("\n## 곡 정보")
        parts.append(f"- 곡명: {song.get('title', '')}")
        if song.get("theme"):
            parts.append(f"- 테마: {song['theme']}")
        if song.get("mood"):
            parts.append(f"- 곡 분위기: {song['mood']}")
        if song.get("track_number"):
            parts.append(f"- 트랙 번호: {song['track_number']}")

    if reference_song:
        parts.append("\n## 참조 곡 (같은 분위기로 생성)")
        parts.append(f"- 참조 곡명: {reference_song.get('title', '')}")
        if reference_song.get("lyrics"):
            parts.append(f"- 참조 가사:\n{reference_song['lyrics']}")
        if reference_song.get("suno_prompt"):
            parts.append(f"- 참조 Suno 프롬프트: {reference_song['suno_prompt']}")
        if reference_song.get("mood"):
            parts.append(f"- 참조 분위기: {reference_song['mood']}")

    return "\n".join(parts)


LYRICS_KO_NATURAL = """
한국어 가사·제목 추가 규칙 (필수):
- 실제 한국인이 일상에서 말하는 구어체로 쓸 것 (노래 가사이지만 딱딱한 문어체·시조체 금지)
- 시간·수량·나이는 아라비아 숫자+단위: 5분, 10분, 3시, 2번 (예: "5분만 더", "5분 전" — "다섯 분만 더" 같은 한글 숫자 시간 표현 지양)
- 알람 스누즈·출근·지하철 등 일상 소재는 친구에게 말하듯 자연스럽게
- "~하여", "~하려 하며", "~해보고자" 같은 작문체·보고서체 종결 지양
- "~잖아", "~거든", "~할까", "~해볼까" 등 구어 종결은 자연스러우면 사용
- 제목은 짧고 기억하기 쉽게 (숫자가 들어가면 아라비아 숫자 우선, 예: "5분 전")
- 같은 표현(후렴)도 매번 똑같이 반복하지 말고 약간씩 변주 가능"""

LYRICS_SYSTEM = """당신은 전문 작사가입니다. Suno AI 음악 생성에 최적화된 가사를 작성합니다.

규칙:
- [Verse], [Chorus], [Bridge], [Outro] 등 섹션 태그 사용
- Suno가 잘 해석할 수 있도록 명확한 구조
- 사용자의 음악 프로필과 앨범 컨셉에 맞는 일관된 톤 유지
- 한국어 또는 요청된 언어로 작성
- 가사만 출력 (설명 없이)"""

LYRICS_SYSTEM_KO = LYRICS_SYSTEM + LYRICS_KO_NATURAL

LYRICS_KO_JSON_SYSTEM = """당신은 전문 작사가입니다. Suno AI용 한국어 곡 제목과 가사를 작성합니다.

규칙:
- 곡 테마·앨범 컨셉·트랙 테마에 맞는 감성적인 한국어 곡 제목 1개
- 앨범 곡당 목표 길이에 맞게 가사 분량 작성 (짧은 2분 30초 팝 한 세트 금지)
- 가사는 [Verse], [Chorus], [Bridge], [Outro] 등 섹션 태그 사용
- 제목을 가사 본문에 넣지 말 것
- 출력은 아래 JSON만 (마크다운 없음):

{"title": "곡 제목", "lyrics": "전체 가사"}""" + LYRICS_KO_NATURAL

LYRICS_ALBUM_BATCH_SYSTEM = """당신은 전문 작사가입니다. 앨범의 여러 곡 한국어 제목·가사를 한 번에 작성합니다.

규칙:
- 각 곡은 테마에 맞는 제목 1개 + [Verse]/[Chorus] 등 섹션 태그 가사
- 앨범 전체 런닝타임·곡 수에 맞는 **곡당 목표 길이**를 반드시 지킬 것 (짧은 2분 30초 팝 한 세트 금지)
- 곡당 목표에 맞게 Verse/Chorus 반복·Bridge·[Instrumental] 등으로 분량 확보
- 곡마다 제목을 가사 본문에 넣지 말 것
- 출력은 아래 JSON만 (마크다운 없음):

{"tracks":[{"track_number":1,"title":"곡 제목","lyrics":"전체 가사"}, ...]}""" + LYRICS_KO_NATURAL

LYRICS_TRANSLATE_SYSTEM = """당신은 K-pop·발라드 전문 작사·번역가입니다. 사용자가 확정한 한국어 가사를 Suno AI용 영어 노래 가사로 옮깁니다.

규칙:
- 직역 금지 — 부르기 좋은 영어 **노래 가사**로 의역·각색
- 한국어 원문의 의미·감정·이미지·스토리를 유지
- [Verse], [Chorus], [Bridge], [Outro] 등 섹션 태그와 줄바꿈 구조 유지
- 영어권 가사처럼 자연스럽게 (어색한 번역체·문어체 금지)
- 한국어 곡명을 영어 노래 제목으로 의역 (직역보다 자연스러운 영어 곡명)
- 출력은 아래 JSON만 (마크다운 없음):

{"title": "English song title", "lyrics": "full English lyrics"}"""

def _estimate_track_duration_sec(album: Optional[dict], song: Optional[dict] = None) -> int:
    """앨범 목표 시간과 곡 수로 트랙당 길이(초) 추정."""
    if album:
        total_min = album.get("target_duration_min")
        track_count = album.get("track_count") or 1
        if total_min and track_count > 0:
            return max(120, int((total_min * 60) / track_count))
    return 210  # 기본 3분 30초


def _format_duration(sec: int) -> str:
    m, s = divmod(sec, 60)
    return f"{m}:{s:02d}"


PROMPT_SYSTEM = """You are a Suno AI arrangement producer. Write a compact English style prompt in English.

Goal: control Intro → Verse → Build → Chorus → Bridge → Outro with specific instruments per section.
Do NOT output only comma-separated tags.

Rules:
- English only (Suno optimized)
- Use instruments from the provided instrument settings
- Reflect lyrics sections [Verse], [Chorus], [Bridge], [Outro]
- Include BPM, vocal style, mood, **exact total duration mm:ss from user prompt**
- HARD LIMIT: entire output under 950 characters
- One short sentence per section header (max ~90 chars each)
- Output prompt body only (no explanation)

Format (one line per section):

[Overview] genre, mood, BPM, vocals, **total duration mm:ss**, instruments, production
[Intro] opening instruments, density, no vocals
[Verse] lead instruments, rhythm, vocal mix
[Build] pre-chorus layering
[Chorus] peak arrangement, hook, effects
[Bridge] contrast or variation
[Outro] ending, fade/stop
[Mix] balance, keep BPM and **total duration**, instruments
"""

PROMPT_RETRY_NOTE = """
CRITICAL: Total output MUST be under 950 characters.
Use ALL section headers on separate lines. One short sentence each. No long paragraphs.
Do NOT output a short comma-separated tag list only.
"""

INSTRUMENTS_SYSTEM = """당신은 음악 프로듀서입니다. 앨범 스타일 프리셋의 기본 악기 구성을 바탕으로, 이 곡의 가사·테마·분위기에 맞게 악기를 조정합니다.

규칙:
- 제공된 기본 악기 구성을 출발점으로 삼고, 대부분 유지합니다
- 곡에 어울리면 악기를 0~2개 추가하거나, 불필요한 악기만 제거할 수 있습니다
- 출력은 아래 JSON 형식만 사용합니다 (설명 없이)

출력 형식:
{
  "preset_name": "프리셋명 (유지 또는 빈 문자열)",
  "mix_notes": "이 곡 믹스·연주 관련 한 줄 메모",
  "instruments": [
    {
      "name": "악기명 (한국어)",
      "name_en": "english name",
      "role": "lead|rhythm|bass|harmony|texture|effects",
      "tone": "음색 키워드",
      "texture": "연주·패턴 설명",
      "notes": "이 곡에서의 역할 한 줄",
      "from_preset": true
    }
  ]
}"""


def _strip_codeblock(text: str) -> str:
    if not text:
        return ""
    text = text.strip()
    if not text.startswith("```"):
        return text
    lines = text.split("\n")
    if lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _unescape_json_string(value: str) -> str:
    try:
        return json.loads(f'"{value}"')
    except json.JSONDecodeError:
        return value.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")


def _extract_json_string_field(text: str, field: str) -> Optional[str]:
    match = re.search(rf'"{field}"\s*:\s*"((?:[^"\\]|\\.)*)"', text, re.DOTALL)
    if match:
        return _unescape_json_string(match.group(1)).strip()
    marker = re.search(rf'"{field}"\s*:\s*"', text)
    if not marker:
        return None
    start = marker.end()
    end_match = re.search(r'"\s*[,}]\s*', text[start:], re.DOTALL)
    if not end_match:
        return None
    raw = text[start : start + end_match.start()]
    return _unescape_json_string(raw).strip()


_TRACK_HEADER_RE = re.compile(
    r'"track_number"\s*:\s*(\d+)\s*,\s*"title"\s*:\s*"((?:[^"\\]|\\.)*)"\s*,\s*"lyrics"\s*:\s*"',
    re.DOTALL,
)
_ALBUM_LYRICS_CHUNK_SIZE = 5


def _lyrics_looks_corrupted(lyrics: str) -> bool:
    return bool(
        re.search(r'"\s*,\s*"track_number"\s*:', lyrics)
        or '"track_number"' in lyrics
        or '", "title"' in lyrics
    )


def _read_json_string_until_delimiter(text: str, start: int) -> Optional[str]:
    """lyrics 값의 시작 위치(여는 따옴표 직후)부터 다음 트랙/객체 끝까지 읽기."""
    i = start
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            i += 2
            continue
        if ch == '"':
            rest = text[i + 1 :]
            if re.match(r'\s*,\s*"track_number"', rest):
                return text[start:i]
            if re.match(r"\s*}\s*,", rest) or re.match(r"\s*}\s*]", rest) or re.match(
                r"\s*}\s*$", rest
            ):
                return text[start:i]
        i += 1
    boundary = re.search(r'",\s*"track_number"', text[start:])
    if boundary:
        return text[start : start + boundary.start()]
    return text[start:] if start < len(text) else None


def _split_corrupted_batch_lyrics(lyrics: str) -> list[dict]:
    """첫 곡에 여러 트랙 JSON이 합쳐진 경우 트랙별로 분리."""
    if not _lyrics_looks_corrupted(lyrics):
        return []

    parts = re.split(r'",\s*"track_number"\s*:\s*', lyrics)
    results: list[dict] = []
    if parts:
        first = _unescape_json_string(parts[0]).strip()
        if first:
            results.append({"track_number": 1, "title": "", "lyrics": first})

    for part in parts[1:]:
        match = re.match(
            r'(\d+)\s*,\s*"title"\s*:\s*"((?:[^"\\]|\\.)*)"\s*,\s*"lyrics"\s*:\s*"(.*)',
            part,
            re.DOTALL,
        )
        if not match:
            continue
        track_number = int(match.group(1))
        title = _unescape_json_string(match.group(2)).strip()
        rest = match.group(3)
        boundary = re.search(r'",\s*"track_number"', rest)
        lyrics_raw = rest[: boundary.start()] if boundary else rest
        lyrics_text = _unescape_json_string(lyrics_raw).strip()
        if lyrics_text:
            results.append(
                {"track_number": track_number, "title": title, "lyrics": lyrics_text}
            )
    return results


def _extract_json_lyrics_field(text: str) -> Optional[str]:
    direct = _extract_json_string_field(text, "lyrics")
    if direct and not _lyrics_looks_corrupted(direct):
        return direct
    marker = re.search(r'"lyrics"\s*:\s*"', text)
    if not marker:
        return None
    start = marker.end()
    raw = _read_json_string_until_delimiter(text, start)
    if not raw:
        return None
    lyrics = _unescape_json_string(raw).strip()
    if _lyrics_looks_corrupted(lyrics):
        return None
    return lyrics


def _parse_lyrics_ko_json(raw: str) -> tuple[Optional[str], str]:
    text = _strip_codeblock(raw)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, dict):
        title = str(data.get("title") or "").strip() or None
        lyrics = str(data.get("lyrics") or "").strip()
        if lyrics:
            if _lyrics_looks_corrupted(lyrics):
                recovered = _split_corrupted_batch_lyrics(lyrics)
                if recovered:
                    first = recovered[0]
                    return first.get("title") or title, first["lyrics"]
            if lyrics.lstrip().startswith("{") and '"lyrics"' in lyrics:
                nested_title, nested_lyrics = _parse_lyrics_ko_json(lyrics)
                return nested_title or title, nested_lyrics
            return title, lyrics

    title = _extract_json_string_field(text, "title")
    lyrics = _extract_json_lyrics_field(text)
    if lyrics:
        return title, lyrics
    return None, (raw or "").strip()


def _normalize_album_track(item: dict) -> Optional[dict]:
    tn = item.get("track_number")
    title = str(item.get("title") or "").strip()
    lyrics = str(item.get("lyrics") or "").strip()
    if tn is None or not lyrics:
        return None
    if _lyrics_looks_corrupted(lyrics):
        recovered = _split_corrupted_batch_lyrics(lyrics)
        if recovered:
            return None
    return {"track_number": int(tn), "title": title, "lyrics": lyrics}


def _parse_album_lyrics_json(raw: str) -> list[dict]:
    text = _strip_codeblock(raw)
    results: list[dict] = []
    recovered_from_corruption: list[dict] = []

    try:
        data = json.loads(text)
        tracks = data.get("tracks", data) if isinstance(data, dict) else data
        if isinstance(tracks, list):
            for item in tracks:
                if not isinstance(item, dict):
                    continue
                lyrics = str(item.get("lyrics") or "").strip()
                if lyrics and _lyrics_looks_corrupted(lyrics):
                    recovered_from_corruption.extend(_split_corrupted_batch_lyrics(lyrics))
                    continue
                normalized = _normalize_album_track(item)
                if normalized:
                    results.append(normalized)
    except json.JSONDecodeError:
        pass

    if recovered_from_corruption:
        by_track = {item["track_number"]: item for item in recovered_from_corruption}
        results = [by_track[k] for k in sorted(by_track)]
        if results:
            return results

    if results:
        by_track = {item["track_number"]: item for item in results}
        return [by_track[k] for k in sorted(by_track)]

    sequential: dict[int, dict] = {}
    for match in _TRACK_HEADER_RE.finditer(text):
        lyrics_raw = _read_json_string_until_delimiter(text, match.end())
        if not lyrics_raw:
            continue
        lyrics = _unescape_json_string(lyrics_raw).strip()
        if not lyrics:
            continue
        track_number = int(match.group(1))
        sequential[track_number] = {
            "track_number": track_number,
            "title": _unescape_json_string(match.group(2)).strip(),
            "lyrics": lyrics,
        }

    return [sequential[k] for k in sorted(sequential)]


def repair_merged_album_lyrics(songs: list[dict]) -> list[dict]:
    """DB에 합쳐진 가사가 있으면 트랙별로 분리."""
    merged: list[dict] = []
    for song in songs:
        lyrics = str(song.get("lyrics_ko") or song.get("lyrics") or "").strip()
        if lyrics and _lyrics_looks_corrupted(lyrics):
            merged.extend(_split_corrupted_batch_lyrics(lyrics))
    if not merged:
        return []
    by_track = {item["track_number"]: item for item in merged}
    return [by_track[k] for k in sorted(by_track)]


async def generate_lyrics(
    client: AIClient,
    profile: Optional[dict],
    album: dict,
    song: dict,
    reference_song: Optional[dict] = None,
    additional: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.8,
    language: str = "ko",
) -> str:
    context = _build_music_context(profile, album, song, reference_song)
    lang_label = "한국어" if language == "ko" else "English"
    user_prompt = f"{context}\n\n위 정보를 바탕으로 {lang_label} 가사를 작성해주세요."
    if additional:
        user_prompt += f"\n\n추가 지시: {additional}"

    system = LYRICS_SYSTEM_KO if language == "ko" else LYRICS_SYSTEM
    return await client.chat(
        model or settings.model_lyrics,
        system,
        user_prompt,
        temperature=temperature,
    )


async def generate_lyrics_ko_with_title(
    client: AIClient,
    profile: Optional[dict],
    album: dict,
    song: dict,
    reference_song: Optional[dict] = None,
    additional: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.8,
) -> tuple[Optional[str], str]:
    """한국어 가사 + 곡 제목 JSON 생성. 실패 시 가사만 반환."""
    context = _build_music_context(profile, album, song, reference_song)
    from app.services.suno_prompt_service import format_album_lyrics_duration_context

    duration_ctx = format_album_lyrics_duration_context(album)
    user_prompt = (
        f"{context}{duration_ctx}\n\n"
        "위 정보를 바탕으로 이 곡의 한국어 제목과 가사를 JSON으로 작성해주세요."
    )
    if additional:
        user_prompt += f"\n\n추가 지시: {additional}"

    raw = await client.chat(
        model or settings.model_lyrics,
        LYRICS_KO_JSON_SYSTEM,
        user_prompt,
        temperature=temperature,
        max_tokens=2000,
        json_mode=True,
    )
    title, lyrics = _parse_lyrics_ko_json(raw)
    if lyrics and title:
        return title, lyrics
    if lyrics:
        return None, lyrics
    # JSON 파싱 실패 시 일반 가사 생성으로 폴백
    fallback = await generate_lyrics(
        client,
        profile,
        album,
        song,
        reference_song,
        additional,
        model,
        temperature,
        language="ko",
    )
    return None, fallback


async def _generate_album_lyrics_chunk(
    client: AIClient,
    profile: Optional[dict],
    album: dict,
    songs: list[dict],
    additional: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.8,
) -> list[dict]:
    from app.services.suno_prompt_service import format_album_lyrics_duration_context

    context = _build_music_context(profile, album, None, None)
    duration_ctx = format_album_lyrics_duration_context(album)
    lines = ["\n## 트랙 목록"]
    for s in sorted(songs, key=lambda x: x.get("track_number") or 0):
        tn = s.get("track_number")
        theme = s.get("theme") or ""
        lines.append(f"- Track {tn}: {theme}")
    user_prompt = (
        f"{context}{duration_ctx}\n"
        + "\n".join(lines)
        + f"\n\n위 {len(songs)}곡 각각 제목+가사를 JSON tracks 배열로 작성해주세요."
        + "\n각 곡의 lyrics는 해당 곡 가사만 포함하고, 다른 트랙 JSON을 넣지 마세요."
        + "\n모든 곡이 위 곡당 목표 길이에 맞도록 섹션 수·가사 줄 수를 충분히 확보하세요."
    )
    if additional:
        user_prompt += f"\n\n추가 지시: {additional}"

    raw = await client.chat(
        model or settings.model_lyrics,
        LYRICS_ALBUM_BATCH_SYSTEM,
        user_prompt,
        temperature=temperature,
        max_tokens=max(4000, len(songs) * 900),
        json_mode=True,
    )
    parsed = _parse_album_lyrics_json(raw)
    if not parsed:
        raise ValueError("앨범 가사 JSON 파싱 실패 — 다시 시도해주세요")
    if len(parsed) < len(songs):
        raise ValueError(
            f"가사 파싱 불완전 ({len(parsed)}/{len(songs)}곡) — 다시 시도해주세요"
        )
    return parsed


async def generate_album_lyrics_batch(
    client: AIClient,
    profile: Optional[dict],
    album: dict,
    songs: list[dict],
    additional: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.8,
) -> list[dict]:
    """앨범 전체 곡 가사 생성 (5곡씩 나눠 호출)."""
    songs_sorted = sorted(songs, key=lambda x: x.get("track_number") or 0)
    all_results: list[dict] = []
    for i in range(0, len(songs_sorted), _ALBUM_LYRICS_CHUNK_SIZE):
        chunk = songs_sorted[i : i + _ALBUM_LYRICS_CHUNK_SIZE]
        chunk_results = await _generate_album_lyrics_chunk(
            client,
            profile,
            album,
            chunk,
            additional,
            model,
            temperature,
        )
        all_results.extend(chunk_results)

    by_track = {item["track_number"]: item for item in all_results}
    if len(by_track) < len(songs_sorted):
        raise ValueError(
            f"가사 생성 불완전 ({len(by_track)}/{len(songs_sorted)}곡) — 다시 시도해주세요"
        )
    return [by_track[s.get("track_number")] for s in songs_sorted if s.get("track_number") in by_track]


async def translate_lyrics_to_english(
    client: AIClient,
    korean_lyrics: str,
    song: Optional[dict] = None,
    additional: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.5,
) -> tuple[Optional[str], str]:
    user_prompt = "## 한국어 가사\n" + korean_lyrics.strip()
    if song:
        if song.get("title"):
            user_prompt += f"\n\n한국어 곡명: {song['title']}"
        if song.get("theme"):
            user_prompt += f"\n테마: {song['theme']}"
    user_prompt += (
        "\n\n위 한국어 가사는 사용자가 수정한 최종본입니다. "
        "이 내용을 바탕으로 영어 곡 제목과 **노래 가사**를 JSON으로 의역해주세요. "
        "단어 대 단어 번역이 아니라, 같은 곡으로 부를 수 있게 자연스럽게 만들어주세요."
    )
    if additional:
        user_prompt += f"\n\n추가 지시: {additional}"

    raw = await client.chat(
        model or settings.model_lyrics,
        LYRICS_TRANSLATE_SYSTEM,
        user_prompt,
        temperature=temperature,
        max_tokens=4000,
        json_mode=True,
    )
    title, lyrics = _parse_lyrics_ko_json(raw)
    if lyrics:
        return title, lyrics
    return None, (raw or "").strip()


async def generate_suno_prompt(
    client: AIClient,
    profile: Optional[dict],
    album: dict,
    song: dict,
    lyrics: Optional[str] = None,
    reference_song: Optional[dict] = None,
    additional: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.6,
    instrument_settings: Optional[str] = None,
) -> str:
    from app.services.suno_prompt_service import (
        PROMPT_JSON_SYSTEM,
        build_template_fallback,
        build_user_prompt_for_json,
        finalize_suno_prompt,
        format_sections,
        is_detailed_suno_prompt,
        estimate_track_duration_sec,
        _parse_prompt_json,
    )

    context = _build_music_context(profile, album, song, reference_song)
    user_prompt = build_user_prompt_for_json(
        context, album, lyrics, instrument_settings, additional, profile, song
    )
    duration_sec = estimate_track_duration_sec(lyrics, profile, album, song)
    chosen_model = model or settings.model_prompt

    # 1) JSON 구조화 생성 (모델이 짧게 답하는 문제 방지)
    try:
        raw = await client.chat(
            chosen_model,
            PROMPT_JSON_SYSTEM,
            user_prompt,
            temperature=temperature,
            max_tokens=900,
        )
        parsed = _parse_prompt_json(raw)
        if parsed:
            formatted = finalize_suno_prompt(format_sections(parsed), duration_sec)
            if is_detailed_suno_prompt(formatted):
                return formatted
    except Exception:
        pass

    # 2) 기존 장문 프롬프트 방식 재시도
    try:
        legacy_prompt = user_prompt + (
            "\n\nWrite compact multi-section English prompt under 950 characters. "
            "Headers: [Overview], [Intro], [Verse], [Build], [Chorus], [Bridge], [Outro], [Mix]. "
            "One short sentence per line."
        )
        result = await client.chat(
            chosen_model,
            PROMPT_SYSTEM,
            legacy_prompt,
            temperature=max(0.35, temperature - 0.1),
            max_tokens=900,
        )
        trimmed = finalize_suno_prompt(result.strip(), duration_sec)
        if is_detailed_suno_prompt(trimmed):
            return trimmed
    except Exception:
        pass

    # 3) AI 실패 시 템플릿 폴백 (항상 상세 구간 프롬프트 보장)
    return finalize_suno_prompt(
        build_template_fallback(
            profile, album, song, lyrics, instrument_settings
        ),
        duration_sec,
    )


async def generate_instruments(
    client: AIClient,
    profile: Optional[dict],
    album: dict,
    song: dict,
    suno_prompt: Optional[str] = None,
    lyrics: Optional[str] = None,
    additional: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.5,
    base_instruments: Optional[str] = None,
) -> str:
    from app.services.instrument_settings_service import (
        ensure_settings,
        serialize_settings,
    )

    context = _build_music_context(profile, album, song)
    base = ensure_settings(base_instruments, profile)
    user_prompt = f"{context}\n\n## 앨범 프리셋 기본 악기 구성\n{serialize_settings(base)}"
    if lyrics:
        user_prompt += f"\n\n## 작성된 가사\n{lyrics}"
    if suno_prompt:
        user_prompt += f"\n\n## Suno 프롬프트\n{suno_prompt}"
    user_prompt += (
        "\n\n위 기본 악기 구성을 유지하면서, 이 곡의 테마·가사에 맞게 "
        "악기를 추가·삭제·조정한 JSON을 작성해주세요."
    )
    if additional:
        user_prompt += f"\n\n추가 지시: {additional}"

    result = await client.chat(
        model or settings.model_instruments,
        INSTRUMENTS_SYSTEM,
        user_prompt,
        temperature=temperature,
    )
    try:
        cleaned = result.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        data = json.loads(cleaned.strip())
        if isinstance(data, dict) and isinstance(data.get("instruments"), list):
            return json.dumps(data, ensure_ascii=False, indent=2)
        return cleaned.strip()
    except json.JSONDecodeError:
        return result


async def suggest_track_themes(
    client: AIClient,
    album: dict,
    profile: Optional[dict],
    track_count: int,
    model: Optional[str] = None,
    temperature: float = 0.8,
) -> list[str]:
    context = _build_music_context(profile, album)
    user_prompt = f"""{context}

앨범 전체 {track_count}곡의 트랙별 테마/스토리를 제안해주세요.
각 곡은 앨범 컨셉 안에서 고유한 이야기를 가져야 합니다.

JSON 배열로만 출력:
{{"themes": ["곡1 테마", "곡2 테마", ...]}}"""

    result = await client.chat(
        model or settings.model_lyrics,
        "앨범 기획 전문가입니다. 트랙 리스트 테마를 제안합니다. JSON만 출력하세요.",
        user_prompt,
        temperature=temperature,
        max_tokens=2000,
        json_mode=True,
    )

    try:
        cleaned = _strip_codeblock(result)
        data = json.loads(cleaned)
        if isinstance(data, dict) and isinstance(data.get("themes"), list):
            return [str(t) for t in data["themes"]]
        if isinstance(data, list):
            return [str(t) for t in data]
        themes = json.loads(cleaned.strip())
        return themes if isinstance(themes, list) else []
    except json.JSONDecodeError:
        return []
