"""OpenAI-compatible provider.

Works with the OpenAI Chat Completions API and any service exposing the same
shape (Azure OpenAI, Together, Groq, a local vLLM server) by pointing
`AI_BASE_URL` at it.
"""

from __future__ import annotations

import httpx

from ..base import AIError, LLMProvider, LLMRequest, LLMResponse

DEFAULT_BASE_URL = "https://api.openai.com/v1"


class OpenAIProvider(LLMProvider):
    name = "openai"

    async def complete(self, request: LLMRequest) -> LLMResponse:
        base = (self._base_url or DEFAULT_BASE_URL).rstrip("/")
        payload: dict = {
            "model": self.model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.prompt},
            ],
        }
        if request.json_schema is not None:
            payload["response_format"] = {"type": "json_object"}

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{base}/chat/completions", json=payload, headers=headers
                )
        except httpx.HTTPError as exc:
            raise AIError(f"OpenAI request failed: {exc}") from exc

        if response.status_code >= 400:
            raise AIError(
                f"OpenAI returned {response.status_code}: {response.text[:400]}"
            )

        data = response.json()
        choices = data.get("choices") or []
        text = choices[0].get("message", {}).get("content", "") if choices else ""
        usage = data.get("usage") or {}
        return LLMResponse(
            text=text,
            model=data.get("model", self.model),
            provider=self.name,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            raw=data,
        )
