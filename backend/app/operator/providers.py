from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ..config import Settings, get_settings


@dataclass(frozen=True)
class Completion:
    text: str
    input_tokens: int
    output_tokens: int
    model: str


class LLMClient(Protocol):
    provider: str
    model: str

    async def complete(self, *, system: str, user: str, schema: dict[str, Any]) -> Completion: ...


@dataclass(frozen=True)
class ProviderPreset:
    base_url: str | None
    model: str
    key_field: str | None
    label: str
    signup: str = ""


# Every entry except `anthropic` speaks the OpenAI chat-completions dialect, so one
# client covers them all. Groq is the default because its free tier needs no card.
PRESETS: dict[str, ProviderPreset] = {
    "groq": ProviderPreset(
        base_url="https://api.groq.com/openai/v1",
        model="llama-3.3-70b-versatile",
        key_field="groq_api_key",
        label="Groq",
        signup="https://console.groq.com/keys",
    ),
    "openrouter": ProviderPreset(
        base_url="https://openrouter.ai/api/v1",
        model="meta-llama/llama-3.3-70b-instruct:free",
        key_field="openrouter_api_key",
        label="OpenRouter",
        signup="https://openrouter.ai/keys",
    ),
    "together": ProviderPreset(
        base_url="https://api.together.xyz/v1",
        model="meta-llama/Llama-3.3-70B-Instruct-Turbo",
        key_field="together_api_key",
        label="Together AI",
        signup="https://api.together.ai/settings/api-keys",
    ),
    "ollama": ProviderPreset(
        base_url="http://localhost:11434/v1",
        model="llama3.1",
        key_field=None,
        label="Ollama (local)",
        signup="https://ollama.com/download",
    ),
    "openai": ProviderPreset(
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
        key_field="openai_api_key",
        label="OpenAI",
        signup="https://platform.openai.com/api-keys",
    ),
    "anthropic": ProviderPreset(
        base_url=None,
        model="claude-opus-5",
        key_field="anthropic_api_key",
        label="Anthropic",
        signup="https://console.anthropic.com/settings/keys",
    ),
}

# USD per million tokens. Unlisted models record tokens with a zero cost rather
# than inventing a price.
PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "llama-3.1-8b-instant": (0.05, 0.08),
    "openai/gpt-oss-120b": (0.15, 0.75),
    "meta-llama/Llama-3.3-70B-Instruct-Turbo": (0.88, 0.88),
    "gpt-4o-mini": (0.15, 0.60),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    rate_in, rate_out = PRICING.get(model, (0.0, 0.0))
    return (input_tokens * rate_in + output_tokens * rate_out) / 1_000_000


class ProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderConfig:
    provider: str
    label: str
    model: str
    base_url: str | None
    api_key: str | None
    signup: str

    @property
    def configured(self) -> bool:
        return self.api_key is not None or self.provider == "ollama"


def resolve_provider(settings: Settings | None = None) -> ProviderConfig:
    settings = settings or get_settings()
    name = (settings.llm_provider or "groq").strip().lower()
    preset = PRESETS.get(name)
    if preset is None:
        raise ProviderError(
            f"unknown LLM_PROVIDER '{name}'; expected one of {sorted(PRESETS)}"
        )

    key = settings.llm_api_key
    if not key and preset.key_field:
        key = getattr(settings, preset.key_field, None)

    return ProviderConfig(
        provider=name,
        label=preset.label,
        model=settings.planner_model or preset.model,
        base_url=settings.llm_base_url or preset.base_url,
        api_key=key or None,
        signup=preset.signup,
    )


class OpenAICompatibleClient:
    """Chat-completions client for Groq, OpenRouter, Together, Ollama and OpenAI.

    JSON-object mode plus prompt-carried schema is used rather than provider-native
    structured outputs, because schema support varies across these providers while
    JSON mode is near-universal. The planner validates and repairs the result.
    """

    def __init__(self, config: ProviderConfig) -> None:
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise ProviderError("the 'openai' package is required for this provider") from exc

        self.provider = config.provider
        self.model = config.model
        self._client = AsyncOpenAI(
            api_key=config.api_key or "not-needed",
            base_url=config.base_url,
            max_retries=2,
        )

    async def complete(self, *, system: str, user: str, schema: dict[str, Any]) -> Completion:
        response = await self._client.chat.completions.create(
            model=self.model,
            max_tokens=1200,
            temperature=0.2,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        usage = response.usage
        return Completion(
            text=response.choices[0].message.content or "",
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
            model=self.model,
        )


class AnthropicClient:
    """Claude client using native structured outputs."""

    def __init__(self, config: ProviderConfig) -> None:
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise ProviderError("the 'anthropic' package is required for this provider") from exc

        self.provider = config.provider
        self.model = config.model
        self._client = anthropic.AsyncAnthropic(api_key=config.api_key)

    async def complete(self, *, system: str, user: str, schema: dict[str, Any]) -> Completion:
        response = await self._client.messages.create(
            model=self.model,
            max_tokens=1500,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": user}],
        )
        if response.stop_reason == "refusal":
            raise ProviderError("the model declined to plan this step")

        return Completion(
            text=next((b.text for b in response.content if b.type == "text"), ""),
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=self.model,
        )


def build_client(settings: Settings | None = None) -> LLMClient:
    config = resolve_provider(settings)
    if not config.configured:
        raise ProviderError(
            f"No API key for {config.label}. Add it to backend/.env "
            f"(get one at {config.signup}), or set LLM_PROVIDER to a provider you have a key for."
        )
    if config.provider == "anthropic":
        return AnthropicClient(config)
    return OpenAICompatibleClient(config)
