"""다중 AI 제공업체 통합 클라이언트."""

from __future__ import annotations

import httpx

PROVIDER_INFO = {
    "openrouter": {
        "name": "OpenRouter",
        "description": "여러 모델을 한 API로 사용",
        "key_url": "https://openrouter.ai/keys",
        "default_models": {
            "lyrics": "~deepseek/deepseek-v4-flash-latest",
            "prompt": "google/gemini-2.5-flash-lite",
            "instruments": "google/gemini-2.5-flash-lite",
            "analyze": "deepseek/deepseek-v3.2",
        },
    },
    "openai": {
        "name": "OpenAI",
        "description": "GPT 시리즈 직접 연동",
        "key_url": "https://platform.openai.com/api-keys",
        "default_models": {
            "lyrics": "gpt-5.5",
            "prompt": "gpt-5.5",
            "instruments": "gpt-5.4-mini",
            "analyze": "gpt-5.5",
        },
    },
    "anthropic": {
        "name": "Anthropic",
        "description": "Claude 시리즈 직접 연동",
        "key_url": "https://console.anthropic.com/settings/keys",
        "default_models": {
            "lyrics": "claude-sonnet-4-20250514",
            "prompt": "claude-sonnet-4-20250514",
            "instruments": "claude-3-5-haiku-20241022",
            "analyze": "claude-sonnet-4-20250514",
        },
    },
    "google": {
        "name": "Google Gemini",
        "description": "Gemini 시리즈 직접 연동",
        "key_url": "https://aistudio.google.com/apikey",
        "default_models": {
            "lyrics": "gemini-2.5-flash",
            "prompt": "gemini-2.5-flash",
            "instruments": "gemini-2.5-flash",
            "analyze": "gemini-2.5-flash",
        },
    },
}

API_KEY_FIELDS = {
    "openrouter": "openrouter_api_key",
    "openai": "openai_api_key",
    "anthropic": "anthropic_api_key",
    "google": "google_api_key",
}

RECOMMENDED_MODELS: dict[str, list[dict[str, str]]] = {
    "openrouter": [
        {"id": "~deepseek/deepseek-v4-flash-latest", "name": "DeepSeek V4 Flash Latest (가사)"},
        {"id": "google/gemini-2.5-flash-lite", "name": "Gemini 2.5 Flash Lite (프롬프트)"},
        {"id": "google/gemini-2.5-flash-lite", "name": "Gemini 2.5 Flash Lite (악기)"},
        {"id": "deepseek/deepseek-v3.2", "name": "DeepSeek V3.2 (분석)"},
        {"id": "qwen/qwen3.7-flash", "name": "Qwen 3.7 Flash"},
        {"id": "xiaomi/mimo-v2.5", "name": "MiMo V2.5"},
        {"id": "deepseek/deepseek-v4-flash", "name": "DeepSeek V4 Flash"},
        {"id": "google/gemini-3.7-flash", "name": "Gemini 3.7 Flash"},
    ],
    "openai": [
        {"id": "gpt-5.5", "name": "GPT-5.5"},
        {"id": "gpt-5.4", "name": "GPT-5.4"},
        {"id": "gpt-5.4-mini", "name": "GPT-5.4 Mini"},
        {"id": "gpt-4o", "name": "GPT-4o"},
        {"id": "gpt-4o-mini", "name": "GPT-4o Mini"},
    ],
    "anthropic": [
        {"id": "claude-sonnet-4-20250514", "name": "Claude Sonnet 4"},
        {"id": "claude-3-5-sonnet-20241022", "name": "Claude 3.5 Sonnet"},
        {"id": "claude-3-5-haiku-20241022", "name": "Claude 3.5 Haiku"},
    ],
    "google": [
        {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash"},
        {"id": "gemini-2.5-pro", "name": "Gemini 2.5 Pro"},
        {"id": "gemini-2.0-flash", "name": "Gemini 2.0 Flash"},
    ],
}


def _extract_chat_text(message: dict) -> str:
    """API message.content가 None·배열인 경우도 문자열로 정규화."""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict):
                text = part.get("text")
                if text:
                    parts.append(str(text))
        return "\n".join(parts)
    return ""


def _require_chat_text(text: str) -> str:
    if not text or not str(text).strip():
        raise ValueError("AI 응답이 비어 있습니다. 모델을 바꾸거나 다시 시도해주세요.")
    return str(text)


class AIClient:
    """제공업체별 API를 통일된 chat 인터페이스로 호출."""

    def __init__(self, provider: str, api_key: str):
        if provider not in PROVIDER_INFO:
            raise ValueError(f"지원하지 않는 제공업체: {provider}")
        self.provider = provider
        self.api_key = api_key
        self.name = PROVIDER_INFO[provider]["name"]

    async def chat(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> str:
        if not self.api_key:
            raise ValueError(
                f"{self.name} API 키가 설정되지 않았습니다. "
                "설정 > 사용자 설정에서 API 키를 입력하세요."
            )

        if self.provider == "openrouter":
            return await self._chat_openrouter(
                model, system_prompt, user_prompt, temperature, max_tokens, json_mode
            )
        if self.provider == "openai":
            return await self._chat_openai(
                model, system_prompt, user_prompt, temperature, max_tokens
            )
        if self.provider == "anthropic":
            return await self._chat_anthropic(
                model, system_prompt, user_prompt, temperature, max_tokens
            )
        if self.provider == "google":
            return await self._chat_google(
                model, system_prompt, user_prompt, temperature, max_tokens
            )
        raise ValueError(f"지원하지 않는 제공업체: {self.provider}")

    async def _chat_openrouter(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> str:
        payload: dict = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "http://localhost:8765",
                    "X-Title": "Suno Helper",
                },
                json=payload,
            )
            response.raise_for_status()
            message = response.json()["choices"][0]["message"]
            return _require_chat_text(_extract_chat_text(message))

    async def _chat_openai(
        self, model: str, system_prompt: str, user_prompt: str, temperature: float
    ) -> str:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
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
            message = response.json()["choices"][0]["message"]
            return _require_chat_text(_extract_chat_text(message))

    async def _chat_anthropic(
        self, model: str, system_prompt: str, user_prompt: str, temperature: float
    ) -> str:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": 4096,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": user_prompt}],
                    "temperature": temperature,
                },
            )
            response.raise_for_status()
            data = response.json()
            return _require_chat_text(data["content"][0].get("text") or "")

    async def _chat_google(
        self, model: str, system_prompt: str, user_prompt: str, temperature: float
    ) -> str:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent"
        )
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                url,
                params={"key": self.api_key},
                json={
                    "systemInstruction": {"parts": [{"text": system_prompt}]},
                    "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
                    "generationConfig": {"temperature": temperature},
                },
            )
            response.raise_for_status()
            data = response.json()
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(str(part.get("text") or "") for part in parts)
            return _require_chat_text(text)

    async def test_connection(self, model: str | None = None) -> dict:
        test_model = model or PROVIDER_INFO[self.provider]["default_models"]["analyze"]
        try:
            result = await self.chat(
                test_model,
                "You are a helpful assistant.",
                "Reply with exactly: OK",
                temperature=0,
            )
            return {"ok": True, "provider": self.provider, "response": result.strip()[:50]}
        except httpx.HTTPStatusError as e:
            detail = e.response.text[:200] if e.response else str(e)
            raise ValueError(f"{self.name} 연결 실패: {detail}") from e

    async def list_models(self) -> list[dict]:
        if self.provider == "openrouter" and self.api_key:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    "https://openrouter.ai/api/v1/models",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                response.raise_for_status()
                return response.json().get("data", [])

        return RECOMMENDED_MODELS.get(self.provider, [])

    async def list_models_for_ui(self) -> list[dict[str, str]]:
        """설정 UI용 모델 목록 (id, name). API 키 없으면 추천 목록."""
        raw = await self.list_models()
        if not raw:
            return list(RECOMMENDED_MODELS.get(self.provider, []))

        normalized: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in raw:
            model_id = item.get("id", "")
            if not model_id or model_id in seen:
                continue
            seen.add(model_id)
            normalized.append(
                {
                    "id": model_id,
                    "name": item.get("name") or model_id,
                }
            )

        recommended_ids = {
            m["id"] for m in RECOMMENDED_MODELS.get(self.provider, [])
        }
        normalized.sort(
            key=lambda m: (
                0 if m["id"] in recommended_ids else 1,
                m["name"].lower(),
            )
        )
        return normalized


# 하위 호환
OpenRouterClient = AIClient


def format_model_label(provider: str, model: str) -> str:
    return f"{provider}:{model}"
