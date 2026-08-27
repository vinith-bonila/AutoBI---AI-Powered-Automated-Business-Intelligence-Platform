"""Recovering JSON from imperfect model output.

Models wrap JSON in prose, fence it in markdown, add trailing commas, or
truncate mid-object. These helpers extract and repair the payload before
Pydantic validation, which keeps the retry budget for genuine failures rather
than spending it on formatting noise.
"""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")


def _balance(text: str) -> str:
    """Close unterminated objects/arrays from a truncated response."""
    in_string = False
    escaped = False
    stack: list[str] = []

    for char in text:
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char in "{[":
            stack.append(char)
        elif char in "}]":
            if stack:
                stack.pop()

    if in_string:
        text += '"'
    for opener in reversed(stack):
        text += "}" if opener == "{" else "]"
    return text


def extract_json(text: str) -> str | None:
    """Pull the most plausible JSON object out of a model response."""
    if not text:
        return None
    candidate = text.strip()

    fenced = _FENCE_RE.search(candidate)
    if fenced:
        candidate = fenced.group(1).strip()

    start = candidate.find("{")
    if start == -1:
        start = candidate.find("[")
    if start == -1:
        return None

    end = max(candidate.rfind("}"), candidate.rfind("]"))
    if end > start:
        candidate = candidate[start : end + 1]
    else:
        candidate = candidate[start:]

    return candidate or None


def loads(text: str) -> Any | None:
    """Parse model output into Python, repairing common defects."""
    candidate = extract_json(text)
    if candidate is None:
        return None

    attempts = (
        candidate,
        _TRAILING_COMMA_RE.sub(r"\1", candidate),
        _balance(_TRAILING_COMMA_RE.sub(r"\1", candidate)),
        # Some models emit single quotes or Python literals.
        _balance(
            _TRAILING_COMMA_RE.sub(r"\1", candidate)
            .replace("True", "true")
            .replace("False", "false")
            .replace("None", "null")
        ),
    )

    for attempt in attempts:
        try:
            return json.loads(attempt)
        except (json.JSONDecodeError, ValueError):
            continue
    return None
