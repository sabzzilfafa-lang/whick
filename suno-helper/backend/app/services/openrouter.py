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
    *,
    omit_profile_instruments: bool = False,
) -> str:
    """음악 컨텍스트 문자열 생성.

    omit_profile_instruments=True: 곡별 악기 세팅이 있을 때 프로필 기본 악기를
    넣지 않음 (프롬프트가 프리셋 악기로 되돌아가는 문제 방지).
    """
    parts = []

    if profile:
        parts.append("## 음악 프로필 (앨범 장르·톤 기준)")
        if profile.get("genre"):
            parts.append(f"- 장르: {profile['genre']}")
        if profile.get("mood"):
            parts.append(f"- 앨범 기본 분위기: {profile['mood']}")
        if profile.get("tempo_bpm"):
            base = profile["tempo_bpm"]
            parts.append(
                f"- 기준 템포: {base} BPM "
                f"(곡마다 가사·분위기에 따라 {int(base) - 5}~{int(base) + 5} 중 하나 사용)"
            )
        if profile.get("key_signature"):
            parts.append(f"- 조성: {profile['key_signature']}")
        if profile.get("vocal_style"):
            parts.append(f"- 기본 보컬 스타일: {profile['vocal_style']}")
        if profile.get("instruments"):
            if omit_profile_instruments:
                parts.append(
                    "- 악기: (아래 곡별 악기 목록이 우선 — 프로필 기본 악기로 되돌리지 말 것)"
                )
            else:
                parts.append(f"- 기본 악기 팔레트: {profile['instruments']}")
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
        parts.append("\n## 곡 정보 (이 곡만의 감정·테마 — 편곡에 반영)")
        parts.append(f"- 곡명: {song.get('title', '')}")
        if song.get("theme"):
            parts.append(f"- 테마: {song['theme']}")
        if song.get("mood"):
            parts.append(f"- 곡 분위기(최우선): {song['mood']}")
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
- 앨범에서 배분된 **곡당 목표 시간**에 맞는 가사 **줄 수·섹션 수**를 반드시 채울 것
- 짧은 2분 30초 팝 한 세트(Verse+Chorus 1~2회) 금지
- 가사는 [Verse], [Chorus], [Bridge], [Outro] 등 섹션 태그 사용
- 제목을 가사 본문에 넣지 말 것
- 출력은 아래 JSON만 (마크다운 없음):

{"title": "곡 제목", "lyrics": "전체 가사"}""" + LYRICS_KO_NATURAL + """

Suno 길이: 프롬프트 시간이 아니라 가사 줄 수가 곡 길이를 결정함. 목표 줄 수 미달 시 실패."""

LYRICS_ALBUM_BATCH_SYSTEM = """당신은 전문 작사가입니다. 앨범의 여러 곡 한국어 제목·가사를 한 번에 작성합니다.

규칙:
- 각 곡은 테마에 맞는 제목 1개 + [Verse]/[Chorus] 등 섹션 태그 가사
- **모든 곡**이 앨범에서 배분된 곡당 목표 시간·가사 줄 수를 반드시 지킬 것
- 곡마다 동일한 줄 수 목표 (앨범 배분 기준)
- 짧은 2분 30초 팝 한 세트 금지 — Verse 2~3회 이상, Bridge, Outro 등으로 분량 확보
- 곡마다 제목을 가사 본문에 넣지 말 것
- 출력은 아래 JSON만 (마크다운 없음):

{"tracks":[{"track_number":1,"title":"곡 제목","lyrics":"전체 가사"}, ...]}""" + LYRICS_KO_NATURAL

LYRICS_TRANSLATE_SYSTEM = """당신은 K-pop·발라드 전문 작사·번역가입니다. 사용자가 확정한 한국어 가사를 Suno AI용 영어 노래 가사로 옮깁니다.

규칙:
- 직역 금지 — 부르기 좋은 영어 **노래 가사**로 의역·각색
- 한국어 원문의 의미·감정·이미지·스토리를 유지
- [Verse], [Chorus], [Bridge], [Outro] 등 **섹션 태그·줄 수·줄바꿈 구조를 한국어와 동일하게 유지** (줄을 줄이지 말 것)
- 영어권 가사처럼 자연스럽게 (어색한 번역체·문어체 금지)
- 한국어 곡명을 영어 노래 제목으로 의역 (직역보다 자연스러운 영어 곡명)
- 출력은 아래 JSON만 (마크다운 없음):

{"title": "English song title", "lyrics": "full English lyrics"}"""

LYRICS_TRANSLATE_KO_SYSTEM = """당신은 K-pop·발라드 전문 작사·번역가입니다. 사용자가 확정한 영어 가사를 Suno AI용 한국어 노래 가사로 옮깁니다.

규칙:
- 직역 금지 — 실제 한국인이 부르기 좋은 한국어 **노래 가사**로 의역·각색
- 영어 원문의 의미·감정·이미지·스토리를 유지
- [Verse], [Chorus], [Bridge], [Outro] 등 **섹션 태그·줄 수·줄바꿈 구조를 영어와 동일하게 유지** (줄을 줄이지 말 것)
- 실제 한국인이 일상에서 말하는 구어체로 쓸 것 (딱딱한 문어체·번역체 금지)
- 시간·수량·나이는 아라비아 숫자+단위: 5분, 10분, 3시, 2번
- "~하여", "~하려 하며" 같은 작문체 종결 지양, "~잖아", "~할까" 등 구어 종결 자연스럽게 사용
- 영어 곡명을 한국어 노래 제목으로 의역 (직역보다 자연스러운 한국어 곡명)
- 출력은 아래 JSON만 (마크다운 없음):

{"title": "한국어 곡 제목", "lyrics": "전체 한국어 가사"}"""

LYRICS_EN_JSON_SYSTEM = """당신은 전문 작사가입니다. Suno AI용 영어 곡 제목과 가사를 작성합니다.

규칙:
- 곡 테마·앨범 컨셉·트랙 테마에 맞는 자연스러운 영어 곡 제목 1개 (직역보다 영어권 노래 제목처럼)
- 앨범에서 배분된 **곡당 목표 시간**에 맞는 가사 **줄 수·섹션 수**를 반드시 채울 것
- 짧은 2분 30초 팝 한 세트(Verse+Chorus 1~2회) 금지
- 가사는 [Verse], [Chorus], [Bridge], [Outro] 등 섹션 태그 사용
- 영어권 가사처럼 자연스럽게 (어색한 번역체·문어체 금지)
- 제목을 가사 본문에 넣지 말 것
- 출력은 아래 JSON만 (마크다운 없음):

{"title": "English song title", "lyrics": "full English lyrics"}

Suno 길이: 프롬프트 시간이 아니라 가사 줄 수가 곡 길이를 결정함. 목표 줄 수 미달 시 실패."""

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
- CLOSED instrument set: use ONLY the song-specific instrument list; list every name in [Overview] and [Mix]
- NEVER invent drums/percussion/kick/snare/hi-hat/synth/strings unless they appear in the list
- If drums are not listed, say "no drums, no percussion" and avoid "full band" / "drum groove" / "driving beat"
- Mood/emotion from THIS song's lyrics & theme overrides album default mood
- Groove from listed instruments only (bass/guitar/piano pulse — not a kit unless listed)
- Reflect lyrics sections [Verse], [Chorus], [Bridge], [Outro]
- Include BPM, vocal style, mood, **exact total duration mm:ss from user prompt**
- HARD LIMIT: entire output under 950 characters
- One short sentence per section header (max ~90 chars each)
- Output prompt body only (no explanation)

Format (one line per section):

[Overview] genre, mood, BPM, vocals, **total duration mm:ss**, ALL instruments, production
[Intro] opening instruments, density, no vocals
[Verse] lead instruments, groove from listed instruments, vocal mix
[Build] pre-chorus layering
[Chorus] peak arrangement, hook, effects
[Bridge] contrast or variation
[Outro] ending, fade/stop
[Mix] balance, keep BPM and **total duration**, only listed instruments (+ no drums if not listed)
"""

PROMPT_RETRY_NOTE = """
CRITICAL: Total output MUST be under 950 characters.
Use ALL section headers on separate lines. One short sentence each. No long paragraphs.
Do NOT output a short comma-separated tag list only.
"""

INSTRUMENTS_SYSTEM = """당신은 앨범 프로듀서입니다. 같은 장르 안에서 곡마다 감정·리듬·리드 악기가 달라지도록 구성합니다.

규칙:
- 앨범 프리셋은 **장르 팔레트**일 뿐, 모든 곡에 같은 악기 세트를 복제하지 말 것
- 가사·테마·곡 분위기의 감정(설렘, 반가움, 우울, 그리움, 희망 등)을 읽고 그에 맞는 리드·리듬·텍스처를 고를 것
- 시그니처 악기 1~2개만 앨범 통일감용으로 남기고, 나머지 2~4개는 교체·역할 변경·연주법(tone/texture) 변경
- 감정에 맞게 BPM 느낌·리듬 밀도·리드 악기를 mix_notes와 texture에 명시
- from_preset: 프리셋에서 온 악기는 true, 새로 넣은 악기는 false
- 출력은 아래 JSON만 (설명 없이)

출력 형식:
{
  "preset_name": "프리셋명 (유지 또는 빈 문자열)",
  "mix_notes": "이 곡 감정·리듬·보컬 한 줄 (한국어 OK)",
  "tempo_bpm": 80,
  "instruments": [
    {
      "name": "악기명 (한국어)",
      "name_en": "english name",
      "role": "lead|rhythm|bass|harmony|texture|effects",
      "tone": "음색 키워드",
      "texture": "연주·패턴·리듬 느낌",
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


def _lyrics_max_tokens_for_album(album: dict, profile: Optional[dict] = None) -> int:
    from app.services.suno_prompt_service import compute_track_lyrics_target

    target = compute_track_lyrics_target(album, profile)
    if not target:
        return 2000
    return max(3000, int(target["target_lines_max"]) * 55)


def _lyrics_retry_suffix(
    lyrics: str,
    album: dict,
    profile: Optional[dict] = None,
) -> str:
    from app.services.suno_prompt_service import (
        _lyrics_stats,
        compute_track_lyrics_target,
    )

    target = compute_track_lyrics_target(album, profile)
    if not target:
        return ""
    stats = _lyrics_stats(lyrics)
    return (
        f"\n\n[재시도] 이전 결과는 가사 {stats['lines']}줄로 너무 짧습니다. "
        f"최소 {target['target_lines_min']}줄, 권장 {target['target_lines_mid']}줄 이상 필요합니다. "
        "2절부터 같은 가사를 반복하지 말고, 새 Verse/Bridge/Outro 가사를 추가하세요."
    )


async def _generate_ko_lyrics_json_once(
    client: AIClient,
    system: str,
    user_prompt: str,
    model: Optional[str],
    temperature: float,
    max_tokens: int,
) -> tuple[Optional[str], str]:
    raw = await client.chat(
        model or settings.model_lyrics,
        system,
        user_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        json_mode=True,
    )
    return _parse_lyrics_ko_json(raw)


def _album_lyrics_chunk_max_tokens(
    album: dict,
    profile: Optional[dict],
    song_count: int,
) -> int:
    per_song = _lyrics_max_tokens_for_album(album, profile)
    return max(6000, per_song * song_count)


def _album_lyrics_chunk_size_for_target(album: dict, profile: Optional[dict] = None) -> int:
    """긴 가사 목표일 때 청크 크기 축소."""
    from app.services.suno_prompt_service import compute_track_lyrics_target

    target = compute_track_lyrics_target(album, profile)
    if not target:
        return _ALBUM_LYRICS_CHUNK_SIZE
    if int(target["target_lines_mid"]) >= 55:
        return 3
    if int(target["target_lines_mid"]) >= 45:
        return 4
    return _ALBUM_LYRICS_CHUNK_SIZE


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
    from app.services.suno_prompt_service import (
        build_lyrics_duration_prompt_block,
        lyrics_meets_target,
    )

    context = _build_music_context(profile, album, song, reference_song)
    duration_ctx = build_lyrics_duration_prompt_block(album, profile)
    base_prompt = (
        f"{context}{duration_ctx}\n\n"
        "위 정보를 바탕으로 이 곡의 한국어 제목과 가사를 JSON으로 작성해주세요."
    )
    if additional:
        base_prompt += f"\n\n추가 지시: {additional}"

    max_tokens = _lyrics_max_tokens_for_album(album, profile)
    title, lyrics = await _generate_ko_lyrics_json_once(
        client,
        LYRICS_KO_JSON_SYSTEM,
        base_prompt,
        model,
        temperature,
        max_tokens,
    )
    if lyrics and not lyrics_meets_target(lyrics, album, profile):
        retry_prompt = base_prompt + _lyrics_retry_suffix(lyrics, album, profile)
        r_title, r_lyrics = await _generate_ko_lyrics_json_once(
            client,
            LYRICS_KO_JSON_SYSTEM,
            retry_prompt,
            model,
            min(0.95, temperature + 0.05),
            max_tokens,
        )
        if r_lyrics and (
            not lyrics
            or _lyrics_stats_simple(r_lyrics) >= _lyrics_stats_simple(lyrics)
        ):
            title, lyrics = r_title or title, r_lyrics

    if lyrics and title:
        return title, lyrics
    if lyrics:
        return None, lyrics
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


async def generate_lyrics_en_with_title(
    client: AIClient,
    profile: Optional[dict],
    album: dict,
    song: dict,
    reference_song: Optional[dict] = None,
    additional: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.8,
) -> tuple[Optional[str], str]:
    """영어 가사 + 곡 제목 JSON 생성. 실패 시 가사만 반환."""
    from app.services.suno_prompt_service import (
        build_lyrics_duration_prompt_block,
        lyrics_meets_target,
    )

    context = _build_music_context(profile, album, song, reference_song)
    duration_ctx = build_lyrics_duration_prompt_block(album, profile)
    base_prompt = (
        f"{context}{duration_ctx}\n\n"
        "Based on the above information, write an English song title and lyrics in JSON."
    )
    if additional:
        base_prompt += f"\n\n추가 지시: {additional}"

    max_tokens = _lyrics_max_tokens_for_album(album, profile)
    title, lyrics = await _generate_ko_lyrics_json_once(
        client,
        LYRICS_EN_JSON_SYSTEM,
        base_prompt,
        model,
        temperature,
        max_tokens,
    )
    if lyrics and not lyrics_meets_target(lyrics, album, profile):
        retry_prompt = (
            base_prompt
            + _lyrics_retry_suffix(lyrics, album, profile)
        )
        r_title, r_lyrics = await _generate_ko_lyrics_json_once(
            client,
            LYRICS_EN_JSON_SYSTEM,
            retry_prompt,
            model,
            min(0.95, temperature + 0.05),
            max_tokens,
        )
        if r_lyrics and (
            not lyrics
            or _lyrics_stats_simple(r_lyrics) >= _lyrics_stats_simple(lyrics)
        ):
            title, lyrics = r_title or title, r_lyrics

    if lyrics and title:
        return title, lyrics
    if lyrics:
        return None, lyrics
    fallback = await generate_lyrics(
        client,
        profile,
        album,
        song,
        reference_song,
        additional,
        model,
        temperature,
        language="en",
    )
    return None, fallback


def _lyrics_stats_simple(lyrics: str) -> int:
    from app.services.suno_prompt_service import _lyrics_stats

    return _lyrics_stats(lyrics)["lines"]


async def _generate_album_lyrics_chunk(
    client: AIClient,
    profile: Optional[dict],
    album: dict,
    songs: list[dict],
    additional: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.8,
) -> list[dict]:
    from app.services.suno_prompt_service import (
        _lyrics_stats,
        build_lyrics_duration_prompt_block,
        compute_track_lyrics_target,
        lyrics_meets_target,
    )

    context = _build_music_context(profile, album, None, None)
    duration_ctx = build_lyrics_duration_prompt_block(album, profile)
    target = compute_track_lyrics_target(album, profile)
    lines = ["\n## 트랙 목록"]
    for s in sorted(songs, key=lambda x: x.get("track_number") or 0):
        tn = s.get("track_number")
        theme = s.get("theme") or ""
        lines.append(f"- Track {tn}: {theme}")
    min_lines = target["target_lines_min"] if target else 0
    base_prompt = (
        f"{context}{duration_ctx}\n"
        + "\n".join(lines)
        + f"\n\n위 {len(songs)}곡 각각 제목+가사를 JSON tracks 배열로 작성해주세요."
        + "\n각 곡의 lyrics는 해당 곡 가사만 포함하고, 다른 트랙 JSON을 넣지 마세요."
        + f"\n모든 곡 가사는 각각 최소 {min_lines}줄 이상이어야 합니다."
        + "\n짧은 팝 한 세트나 2절 반복 루프로 시간을 채우지 마세요."
    )
    if additional:
        base_prompt += f"\n\n추가 지시: {additional}"

    max_tokens = _album_lyrics_chunk_max_tokens(album, profile, len(songs))

    async def _call(prompt: str, temp: float) -> list[dict]:
        raw = await client.chat(
            model or settings.model_lyrics,
            LYRICS_ALBUM_BATCH_SYSTEM,
            prompt,
            temperature=temp,
            max_tokens=max_tokens,
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

    parsed = await _call(base_prompt, temperature)
    short_tracks = [
        item
        for item in parsed
        if not lyrics_meets_target(item.get("lyrics", ""), album, profile)
    ]
    if short_tracks and target:
        worst = min(
            short_tracks,
            key=lambda x: _lyrics_stats(x.get("lyrics", ""))["lines"],
        )
        retry_prompt = base_prompt + _lyrics_retry_suffix(
            worst.get("lyrics", ""), album, profile
        )
        retry_prompt += (
            f"\n특히 Track {worst.get('track_number')} 등 "
            f"{len(short_tracks)}곡이 가사 줄 수 부족입니다."
        )
        try:
            retry_parsed = await _call(retry_prompt, min(0.95, temperature + 0.05))
            by_track = {item["track_number"]: item for item in parsed}
            for item in retry_parsed:
                tn = item.get("track_number")
                old = by_track.get(tn)
                if not old:
                    by_track[tn] = item
                    continue
                old_lines = _lyrics_stats(old.get("lyrics", ""))["lines"]
                new_lines = _lyrics_stats(item.get("lyrics", ""))["lines"]
                if new_lines >= old_lines:
                    by_track[tn] = item
            parsed = [by_track[k] for k in sorted(by_track)]
        except Exception:
            pass

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
    chunk_size = _album_lyrics_chunk_size_for_target(album, profile)
    for i in range(0, len(songs_sorted), chunk_size):
        chunk = songs_sorted[i : i + chunk_size]
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
    from app.services.suno_prompt_service import _lyrics_stats

    ko_stats = _lyrics_stats(korean_lyrics)
    if ko_stats["lines"] > 0:
        user_prompt += (
            f"\n\n한국어 가사는 **{ko_stats['lines']}줄**입니다. "
            "영어 가사도 섹션·줄 수를 동일하게 유지하세요 (줄을 줄이지 마세요)."
        )
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


async def translate_lyrics_to_korean(
    client: AIClient,
    english_lyrics: str,
    song: Optional[dict] = None,
    additional: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.5,
) -> tuple[Optional[str], str]:
    """영어 가사를 한국어 가사로 의역. (title, lyrics) 튜플 반환."""
    user_prompt = "## English lyrics\n" + english_lyrics.strip()
    if song:
        if song.get("title_en"):
            user_prompt += f"\n\nEnglish title: {song['title_en']}"
        if song.get("theme"):
            user_prompt += f"\n테마: {song['theme']}"
    from app.services.suno_prompt_service import _lyrics_stats

    en_stats = _lyrics_stats(english_lyrics)
    if en_stats["lines"] > 0:
        user_prompt += (
            f"\n\n영어 가사는 **{en_stats['lines']}줄**입니다. "
            "한국어 가사도 섹션·줄 수를 동일하게 유지하세요 (줄을 줄이지 마세요)."
        )
    user_prompt += (
        "\n\n위 영어 가사는 사용자가 확정한 최종본입니다. "
        "이 내용을 바탕으로 한국어 곡 제목과 **노래 가사**를 JSON으로 의역해주세요. "
        "단어 대 단어 번역이 아니라, 같은 곡을 한국어로 부를 수 있게 자연스럽게 만들어주세요."
    )
    if additional:
        user_prompt += f"\n\n추가 지시: {additional}"

    raw = await client.chat(
        model or settings.model_lyrics,
        LYRICS_TRANSLATE_KO_SYSTEM,
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
    from app.services.instrument_settings_service import parse_settings
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

    parsed_inst = parse_settings(instrument_settings)
    has_song_instruments = bool(parsed_inst and parsed_inst.get("instruments"))
    context = _build_music_context(
        profile,
        album,
        song,
        reference_song,
        omit_profile_instruments=has_song_instruments,
    )
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
            formatted = finalize_suno_prompt(
                format_sections(parsed),
                duration_sec,
                instrument_settings=instrument_settings,
                profile=profile,
            )
            if is_detailed_suno_prompt(formatted):
                return formatted
    except Exception:
        pass

    # 2) 기존 장문 프롬프트 방식 재시도
    try:
        legacy_prompt = user_prompt + (
            "\n\nWrite compact multi-section English prompt under 950 characters. "
            "Headers: [Overview], [Intro], [Verse], [Build], [Chorus], [Bridge], [Outro], [Mix]. "
            "One short sentence per line. Use ONLY the closed instrument list; "
            "if drums are not listed, say no drums/no percussion."
        )
        result = await client.chat(
            chosen_model,
            PROMPT_SYSTEM,
            legacy_prompt,
            temperature=max(0.35, temperature - 0.1),
            max_tokens=900,
        )
        trimmed = finalize_suno_prompt(
            result.strip(),
            duration_sec,
            instrument_settings=instrument_settings,
            profile=profile,
        )
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
        instrument_settings=instrument_settings,
        profile=profile,
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
    from app.services.suno_prompt_service import (
        _base_bpm,
        bpm_range_label,
        resolve_track_bpm,
    )

    context = _build_music_context(
        profile, album, song, omit_profile_instruments=False
    )
    base = ensure_settings(base_instruments, profile)
    # 이미 곡에 확정된 BPM이 있으면 유지, 없으면 가사·분위기 ±5로 결정
    track_bpm = resolve_track_bpm(
        profile,
        song,
        lyrics,
        serialize_settings(base) if base.get("tempo_bpm") is not None else None,
    )
    base["tempo_bpm"] = track_bpm
    bpm_base = _base_bpm(profile, song)
    user_prompt = (
        f"{context}\n\n"
        "## 앨범 프리셋 팔레트 (출발점 — 그대로 복제 금지)\n"
        f"{serialize_settings(base)}\n\n"
        f"## 이 곡 확정 BPM: {track_bpm}\n"
        f"- 프리셋 기준 {bpm_base} BPM, 허용 범위 {bpm_range_label(bpm_base)}\n"
        f"- JSON의 tempo_bpm 필드는 반드시 {track_bpm} 으로 둘 것\n\n"
        "## 편곡 지시 (필수)\n"
        "- 이 곡 가사·테마의 고유 감정(설렘/반가움/우울/그리움/희망 등)을 먼저 파악할 것\n"
        "- 시그니처 악기 1~2개만 남기고 리드·리듬·텍스처를 감정에 맞게 바꿀 것\n"
        "- 같은 앨범의 다른 곡과 악기·리듬이 거의 같으면 실패\n"
        "- mix_notes에 이 곡의 감정과 리듬 느낌을 한 줄로 적을 것"
    )
    if lyrics:
        user_prompt += f"\n\n## 작성된 가사 (감정·분위기 근거)\n{lyrics}"
    if suno_prompt:
        user_prompt += f"\n\n## Suno 프롬프트\n{suno_prompt}"
    if additional:
        user_prompt += f"\n\n추가 지시: {additional}"

    # 감정별 편곡 변주를 위해 기본보다 약간 높게
    temp = max(temperature, 0.55)
    result = await client.chat(
        model or settings.model_instruments,
        INSTRUMENTS_SYSTEM,
        user_prompt,
        temperature=temp,
    )
    try:
        cleaned = result.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        data = json.loads(cleaned.strip())
        if isinstance(data, dict) and isinstance(data.get("instruments"), list):
            data["tempo_bpm"] = track_bpm
            return json.dumps(data, ensure_ascii=False, indent=2)
        return cleaned.strip()
    except json.JSONDecodeError:
        # 파싱 실패 시에도 계산된 BPM을 기본 세팅에 넣어 반환
        base["tempo_bpm"] = track_bpm
        return serialize_settings(base) if not result.strip() else result


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
