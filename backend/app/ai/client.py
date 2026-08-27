"""AI service facade.

Responsibilities:
  * pick a provider from configuration (never from a request),
  * ask for structured output and validate it against a Pydantic model,
  * retry with a repair prompt when validation fails,
  * give up cleanly so the caller can fall back to deterministic rules.

`is_enabled` is false when no key is configured. Every caller must handle that
path, which is what makes the product fully functional without an LLM.
"""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel, ValidationError

from ..config import Settings
from ..utils.logging import get_logger
from . import json_repair
from .base import AIError, AIUnavailable, LLMProvider, LLMRequest, LLMResponse
from .providers.anthropic_provider import AnthropicProvider
from .providers.openai_provider import OpenAIProvider

log = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

PROVIDERS: dict[str, type[LLMProvider]] = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
}

REPAIR_INSTRUCTION = (
    "Your previous response could not be parsed into the required schema.\n"
    "Error:\n{error}\n\n"
    "Respond again with ONLY a single valid JSON object matching the schema. "
    "No markdown fences, no commentary, no trailing commas."
)


class AIService:
    """Thin, testable wrapper around whichever provider is configured."""

    def __init__(self, settings: Settings, provider: LLMProvider | None = None):
        self._settings = settings
        self._provider = provider
        self.last_error: str | None = None

        if provider is None and settings.ai_configured:
            provider_cls = PROVIDERS.get(settings.ai_provider.lower())
            if provider_cls is None:
                log.warning(
                    "Unknown AI provider %r; falling back to deterministic mode.",
                    settings.ai_provider,
                )
            else:
                self._provider = provider_cls(
                    model=settings.ai_model,
                    api_key=settings.ai_api_key,
                    base_url=settings.ai_base_url,
                    timeout=settings.ai_timeout_seconds,
                )

    @property
    def is_enabled(self) -> bool:
        return self._provider is not None

    @property
    def provider_name(self) -> str | None:
        return self._provider.name if self._provider else None

    @property
    def model_name(self) -> str | None:
        return self._provider.model if self._provider else None

    async def complete(self, request: LLMRequest) -> LLMResponse:
        if self._provider is None:
            raise AIUnavailable("No AI provider is configured.")
        return await self._provider.complete(request)

    async def structured(
        self,
        *,
        system: str,
        prompt: str,
        schema: type[T],
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> T | None:
        """Request JSON and validate it into `schema`, or return None.

        Returning None is a normal outcome, not an exception: the caller
        proceeds with deterministic output.
        """
        if self._provider is None:
            return None

        settings = self._settings
        request = LLMRequest(
            system=system,
            prompt=prompt,
            max_tokens=max_tokens or settings.ai_max_tokens,
            temperature=(
                settings.ai_temperature if temperature is None else temperature
            ),
            json_schema=schema.model_json_schema(),
        )

        last_error = "unknown error"
        for attempt in range(settings.ai_max_retries + 1):
            try:
                response = await self._provider.complete(request)
            except AIError as exc:
                last_error = str(exc)
                log.warning("AI call failed (attempt %d): %s", attempt + 1, exc)
                # A transport/auth failure will not be fixed by a repair
                # prompt, so stop immediately.
                break

            payload = json_repair.loads(response.text)
            if payload is None:
                last_error = "response contained no parsable JSON"
            else:
                try:
                    validated = schema.model_validate(payload)
                except ValidationError as exc:
                    last_error = _summarize_validation_error(exc)
                else:
                    log.info(
                        "AI %s returned valid %s (in=%s out=%s tokens)",
                        self._provider.name,
                        schema.__name__,
                        response.input_tokens,
                        response.output_tokens,
                    )
                    self.last_error = None
                    return validated

            log.warning(
                "AI response invalid (attempt %d/%d): %s",
                attempt + 1, settings.ai_max_retries + 1, last_error,
            )
            if attempt < settings.ai_max_retries:
                request = LLMRequest(
                    system=system,
                    prompt=(
                        f"{prompt}\n\n---\n"
                        + REPAIR_INSTRUCTION.format(error=last_error)
                    ),
                    max_tokens=request.max_tokens,
                    temperature=0.0,
                    json_schema=request.json_schema,
                )

        self.last_error = last_error
        log.warning(
            "Giving up on AI %s after %d attempt(s); using deterministic output.",
            schema.__name__, settings.ai_max_retries + 1,
        )
        return None


def _summarize_validation_error(exc: ValidationError, limit: int = 5) -> str:
    parts = []
    for error in exc.errors()[:limit]:
        location = ".".join(str(p) for p in error.get("loc", ()))
        parts.append(f"{location or '<root>'}: {error.get('msg')}")
    return "; ".join(parts)
