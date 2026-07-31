from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = f"sqlite+aiosqlite:///{BASE_DIR / 'sentinel.db'}"

    # Which LLM plans the agent's actions. See app/operator/providers.py for the
    # supported names; every one except `anthropic` is OpenAI-chat-compatible.
    llm_provider: str = "groq"
    planner_model: str | None = None
    llm_api_key: str | None = None
    llm_base_url: str | None = None

    groq_api_key: str | None = None
    openrouter_api_key: str | None = None
    together_api_key: str | None = None
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None

    max_steps_per_run: int = 25
    cors_origins: str = "*"

    browser_headless: bool = True
    # Chromium refuses to start as root with its sandbox on, which is the usual
    # situation inside a container. Prefer running as a non-root user; set this
    # only if your host forces root.
    browser_no_sandbox: bool = False

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
