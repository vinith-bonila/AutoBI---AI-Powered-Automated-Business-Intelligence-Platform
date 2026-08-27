"""Anthropic Claude provider (Messages API over plain HTTP)."""

from __future__ import annotations

import httpx

from ..base import AIError, LLMProvider, LLMRequest, LLMResponse

API_VERSION = "2023-06-01"
DEFAULT_BASE_URL = "https://api.anthropic.com"


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    async def complete(self, request: LLMRequest) -> LLMResponse:
        base = (self._base_url or DEFAULT_BASE_URL).rstrip("/")
        payload: dict = {
            "model": self.model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "system": request.system,
            "messages": [{"role": "user", "content": request.prompt}],
        }

        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": API_VERSION,
            "content-type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{base}/v1/messages", json=payload, headers=headers
                )
        except httpx.HTTPError as exc:
            raise AIError(f"Anthropic request failed: {exc}") from exc

        if response.status_code >= 400:
            raise AIError(
                f"Anthropic returned {response.status_code}: {response.text[:400]}"
            )

        data = response.json()
        blocks = data.get("content") or []
        text = "".join(
            block.get("text", "") for block in blocks if block.get("type") == "text"
        )
        usage = data.get("usage") or {}
        return LLMResponse(
            text=text,
            model=data.get("model", self.model),
            provider=self.name,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            raw=data,
        )
