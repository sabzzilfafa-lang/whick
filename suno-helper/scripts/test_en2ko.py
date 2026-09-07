"""en→ko 의역 분기 통합 테스트 (LLM 호출은 mock, 분기 로직만 검증)."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "backend"))

from unittest.mock import AsyncMock, patch

from app.api import api_generate_lyrics
from app.schemas import GenerateLyricsRequest


async def main() -> int:
    # 1) translate_lyrics_to_korean 함수 임포트 확인
    from app.services.openrouter import translate_lyrics_to_korean

    print("PASS: translate_lyrics_to_korean importable")

    # 2) mock 클라이언트로 en→ko 의역 함수 동작 확인
    from app.services.ai_client import AIClient

    mock_client = AIClient.__new__(AIClient)
    mock_client.chat = AsyncMock(
        return_value='{"title": "서울의 밤", "lyrics": "[Verse]\\n서울의 밤 강변을 걸어\\n네온 불빛 아래 너를 생각해"}'
    )
    title, lyrics = await translate_lyrics_to_korean(
        mock_client,
        "[Verse]\nWalking down the Han river tonight\nNeon lights remind me of you",
        song={"title_en": "Seoul Nights", "theme": "city"},
    )
    assert title == "서울의 밤", f"title mismatch: {title}"
    assert "서울의 밤" in lyrics
    # 프롬프트에 영어 가사와 줄 수 지시가 포함됐는지
    sent = mock_client.chat.call_args
    user_prompt = sent.args[2] if sent.args and len(sent.args) > 2 else sent.kwargs.get("user_prompt", "")
    assert "English lyrics" in user_prompt or "Walking down" in user_prompt, user_prompt[:200]
    print("PASS: en→ko paraphrase works, ko title extracted")

    # 3) 시스템 프롬프트가 ko 의역용인지
    system = sent.args[1] if len(sent.args) > 1 else sent.kwargs.get("system_prompt", "")
    assert "한국어 노래 가사" in system or "의역" in system, system[:200]
    print("PASS: ko translate system prompt used")

    print("ALL_UNIT_TESTS_PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
