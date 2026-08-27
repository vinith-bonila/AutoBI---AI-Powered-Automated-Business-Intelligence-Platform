"""Provider-agnostic LLM interface.

Adding a provider means implementing `LLMProvider.complete` and registering the
class in `ai/client.py`. Nothing else in the codebase imports a vendor SDK, and
no API key ever leaves the backend process.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field


class AIError(RuntimeError):
    """Raised when a provider call fails in a way the caller should handle."""


class AIUnavailable(AIError):
    """Raised when no provider is configured — never an error condition.

    The pipeline treats this as "run deterministically", not as a failure.
    """


@dataclass
class LLMRequest:
    system: str
    prompt: str
    max_tokens: int = 4096
    temperature: float = 0.2
    # A JSON Schema the provider should enforce where it supports structured
    # output. Providers that cannot enforce it fall back to prompt-level
    # instruction plus our own validation.
    json_schema: dict | None = None


@dataclass
class LLMResponse:
    text: str
    model: str
    provider: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    raw: dict = field(default_factory=dict)


class LLMProvider(abc.ABC):
    """The single method every provider must implement."""

    name: str = "base"

    def __init__(self, *, model: str, api_key: str, base_url: str = "", timeout: float = 90.0):
        self.model = model
        self._api_key = api_key
        self._base_url = base_url
        self._timeout = timeout

    @abc.abstractmethod
    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Send one completion request and return the raw text response."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{type(self).__name__} model={self.model!r}>"
