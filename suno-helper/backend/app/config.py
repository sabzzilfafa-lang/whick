from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openrouter_api_key: str = ""
    host: str = "127.0.0.1"
    port: int = 8765

    model_lyrics: str = "~deepseek/deepseek-v4-flash-latest"
    model_prompt: str = "google/gemini-2.5-flash-lite"
    model_instruments: str = "google/gemini-2.5-flash-lite"

    @property
    def data_dir(self) -> Path:
        return _ROOT / "data"

    database_url: str = f"sqlite+aiosqlite:///{_ROOT / 'data' / 'suno_helper.db'}"


settings = Settings()
