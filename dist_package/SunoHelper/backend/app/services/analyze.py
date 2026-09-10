"""취향 곡 분석 → Suno 프롬프트 생성."""

import json
from typing import Optional

from app.services.ai_client import AIClient

ANALYZE_SYSTEM = """당신은 음악 분석 전문가입니다. 사용자가 좋아하는 곡을 분석해 Suno AI용 정보를 제공합니다.

JSON 형식으로만 출력:
{
  "genre": "장르",
  "mood": "분위기 키워드",
  "tempo_bpm": 120,
  "key_signature": "조성 (추정)",
  "vocal_style": "보컬 스타일",
  "instruments": "주요 악기",
  "production_style": "프로덕션 특성",
  "energy_level": "low/medium/high",
  "suno_prompt": "영어 Suno 스타일 프롬프트 (200자 이내, 쉼표 구분)",
  "summary": "한국어로 이 곡의 음악적 특징 2-3문장 요약"
}"""


async def analyze_favorite_track(
    client: AIClient,
    title: str,
    artist: Optional[str] = None,
    lyrics: Optional[str] = None,
    notes: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.7,
) -> dict:
    parts = [f"곡명: {title}"]
    if artist:
        parts.append(f"아티스트: {artist}")
    if lyrics:
        parts.append(f"\n## 가사\n{lyrics}")
    if notes:
        parts.append(f"\n## 사용자 메모 (이 곡의 느낌, 좋아하는 이유)\n{notes}")

    parts.append(
        "\n위 곡을 분석해 Suno에서 비슷한 느낌의 음악을 만들 수 있도록 JSON을 작성해주세요."
    )
    if not lyrics:
        parts.append(
            "가사가 없으므로 곡명과 아티스트 정보를 바탕으로 알려진 스타일을 추론해주세요."
        )

    result = await client.chat(
        model or "openai/gpt-4o",
        ANALYZE_SYSTEM,
        "\n".join(parts),
        temperature=temperature,
    )

    try:
        cleaned = result.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        return json.loads(cleaned.strip())
    except json.JSONDecodeError:
        return {
            "suno_prompt": result.strip(),
            "summary": result.strip(),
            "genre": "",
            "mood": "",
        }
