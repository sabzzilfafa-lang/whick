"""앱 설정 관리 - DB 우선, .env는 폴백."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import AppSetting
from app.services.ai_client import AIClient, API_KEY_FIELDS, PROVIDER_INFO, RECOMMENDED_MODELS

TASKS = ("lyrics", "prompt", "instruments", "analyze", "thumbnail")

# DB에 남아 있는 잘못된 모델 ID → 현재 권장 모델
DEPRECATED_MODEL_MAP: dict[str, str] = {
    "z-ai/glm-5.3-flash": "google/gemini-2.5-flash-lite",
}


def _resolve_model(task: str, model: str) -> str:
    return DEPRECATED_MODEL_MAP.get(model, model) or DEFAULTS[f"model_{task}"]

DEFAULTS = {
    "openrouter_api_key": "",
    "openai_api_key": "",
    "anthropic_api_key": "",
    "google_api_key": "",
    "provider_lyrics": "openrouter",
    "provider_prompt": "openrouter",
    "provider_instruments": "openrouter",
    "provider_analyze": "openrouter",
    "model_lyrics": "~deepseek/deepseek-v4-flash-latest",
    "model_prompt": "google/gemini-2.5-flash-lite",
    "model_instruments": "google/gemini-2.5-flash-lite",
    "model_analyze": "deepseek/deepseek-v3.2",
    # 썸네일 3종 생성: 텍스트 프롬프트 생성 AI + 이미지 생성 AI 지정 (2026-09-10)
    "provider_thumbnail": "openrouter",
    "model_thumbnail": "google/gemini-2.5-flash-lite",
    "image_provider": "openrouter",
    "image_model": "google/gemini-2.5-flash-image",
    "temperature_lyrics": "0.8",
    "temperature_prompt": "0.5",
    "temperature_instruments": "0.4",
    "temperature_analyze": "0.6",
    "youtube_client_id": "",
    "youtube_client_secret": "",
}

API_KEY_SETTING_KEYS = set(API_KEY_FIELDS.values()) | {
    "youtube_client_secret",
    "youtube_refresh_token",
    "youtube_access_token",
}


def _mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 4:
        return "****"
    return "****" + key[-4:]


async def get_setting(db: AsyncSession, key: str) -> str:
    result = await db.execute(select(AppSetting).where(AppSetting.key == key))
    row = result.scalar_one_or_none()
    if row and row.value:
        return row.value

    env_map = {
        "openrouter_api_key": settings.openrouter_api_key,
        "model_lyrics": settings.model_lyrics,
        "model_prompt": settings.model_prompt,
        "model_instruments": settings.model_instruments,
    }
    return env_map.get(key, DEFAULTS.get(key, ""))


async def set_setting(db: AsyncSession, key: str, value: str) -> None:
    result = await db.execute(select(AppSetting).where(AppSetting.key == key))
    row = result.scalar_one_or_none()
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))
    await db.flush()


async def get_all_settings(db: AsyncSession) -> dict[str, str]:
    result = await db.execute(select(AppSetting))
    stored = {r.key: r.value for r in result.scalars().all()}
    merged = {**DEFAULTS, **stored}

    if not merged.get("openrouter_api_key"):
        merged["openrouter_api_key"] = settings.openrouter_api_key

    return merged


async def get_public_settings(db: AsyncSession) -> dict:
    all_settings = await get_all_settings(db)

    api_keys_status = {}
    for provider, field in API_KEY_FIELDS.items():
        key = all_settings.get(field, "")
        api_keys_status[f"{field}_set"] = bool(key)
        api_keys_status[f"{field}_masked"] = _mask_key(key)

    public = {
        k: v for k, v in all_settings.items() if k not in API_KEY_SETTING_KEYS
    }
    # model_thumbnail 빈 값(구버전 저장 결함) → 기본 모델로 치유해 반환 (2026-09-10).
    # 빈 값 그대로면 UI select가 첫 항목(딥시크)을 표시해 '저장하면 딥시크로 돌아간다'로 보임.
    if not (public.get("model_thumbnail") or "").strip():
        public["model_thumbnail"] = DEFAULTS["model_thumbnail"]
    public.update(api_keys_status)

    # 하위 호환
    public["openrouter_api_key_set"] = api_keys_status.get("openrouter_api_key_set", False)
    public["openrouter_api_key_masked"] = api_keys_status.get("openrouter_api_key_masked", "")

    return public


async def update_settings(db: AsyncSession, updates: dict[str, str]) -> dict:
    allowed = set(DEFAULTS.keys()) | API_KEY_SETTING_KEYS
    for key, value in updates.items():
        if key not in allowed:
            continue
        if key in API_KEY_SETTING_KEYS and value == "":
            continue
        if key.startswith("provider_") and value not in PROVIDER_INFO:
            continue
        result = await db.execute(select(AppSetting).where(AppSetting.key == key))
        row = result.scalar_one_or_none()
        if row:
            row.value = value
        else:
            db.add(AppSetting(key=key, value=value))
    await db.flush()
    return await get_public_settings(db)


async def get_ai_config(db: AsyncSession) -> dict:
    all_settings = await get_all_settings(db)
    api_keys = {
        provider: all_settings.get(field, "")
        for provider, field in API_KEY_FIELDS.items()
    }
    tasks = {}
    for task in TASKS:
        provider = all_settings.get(f"provider_{task}", DEFAULTS[f"provider_{task}"])
        raw_model = all_settings.get(f"model_{task}", DEFAULTS[f"model_{task}"])
        tasks[task] = {
            "provider": provider,
            "model": _resolve_model(task, raw_model),
            "temperature": float(
                all_settings.get(f"temperature_{task}", DEFAULTS.get(f"temperature_{task}", "0.5"))
            ),
        }
    return {"api_keys": api_keys, "tasks": tasks}


async def get_client_for_task(db: AsyncSession, task: str) -> tuple[AIClient, str, float, str]:
    """task별 AI 클라이언트, 모델, temperature, provider 반환."""
    config = await get_ai_config(db)
    task_cfg = config["tasks"][task]
    provider = task_cfg["provider"]
    api_key = config["api_keys"].get(provider, "")
    client = AIClient(provider, api_key)
    return client, task_cfg["model"], task_cfg["temperature"], provider


# 하위 호환 alias
async def get_openrouter_config(db: AsyncSession) -> dict:
    config = await get_ai_config(db)
    lyrics = config["tasks"]["lyrics"]
    return {
        "api_key": config["api_keys"].get(lyrics["provider"], ""),
        "model_lyrics": config["tasks"]["lyrics"]["model"],
        "model_prompt": config["tasks"]["prompt"]["model"],
        "model_instruments": config["tasks"]["instruments"]["model"],
        "model_analyze": config["tasks"]["analyze"]["model"],
        "temperature_lyrics": config["tasks"]["lyrics"]["temperature"],
        "temperature_prompt": config["tasks"]["prompt"]["temperature"],
        "temperature_instruments": config["tasks"]["instruments"]["temperature"],
        "temperature_analyze": config["tasks"]["analyze"]["temperature"],
    }


def list_providers() -> list[dict]:
    return [
        {
            "id": pid,
            "name": info["name"],
            "description": info["description"],
            "key_url": info["key_url"],
            "key_field": API_KEY_FIELDS[pid],
            "default_models": info["default_models"],
            "recommended_models": RECOMMENDED_MODELS.get(pid, []),
        }
        for pid, info in PROVIDER_INFO.items()
    ]


async def list_provider_models(db: AsyncSession, provider: str) -> list[dict[str, str]]:
    if provider not in PROVIDER_INFO:
        raise ValueError(f"지원하지 않는 제공업체: {provider}")
    config = await get_ai_config(db)
    api_key = config["api_keys"].get(provider, "")
    client = AIClient(provider, api_key)
    try:
        models = await client.list_models_for_ui()
        if models:
            return models
    except Exception:
        pass
    return list(RECOMMENDED_MODELS.get(provider, []))
