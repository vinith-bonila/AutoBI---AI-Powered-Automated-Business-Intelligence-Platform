"""AI layer: JSON recovery, schema validation, retries and grounding.

No network calls. A fake provider returns scripted responses so the retry and
fallback paths can be exercised deterministically.
"""

from __future__ import annotations

import pytest

from app.ai import json_repair
from app.ai.base import AIError, LLMProvider, LLMRequest, LLMResponse
from app.ai.client import AIService
from app.config import Settings
from app.insights.generator import build_evidence_index, generate
from app.schemas.analysis import AnalysisResult
from app.schemas.dashboard import (
    KPI,
    LLMInsightResponse,
    LLMSemanticResponse,
)
from app.schemas.enums import ValueFormat
from app.schemas.quality import DataQualityReport


class FakeProvider(LLMProvider):
    """Returns queued responses, or raises when a response is an exception."""

    name = "fake"

    def __init__(self, responses: list):
        super().__init__(model="fake-1", api_key="test")
        self.responses = list(responses)
        self.calls: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        if not self.responses:
            raise AIError("no more scripted responses")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return LLMResponse(text=item, model=self.model, provider=self.name)


def service(responses: list) -> AIService:
    return AIService(Settings(ai_provider="fake", ai_api_key="x"), FakeProvider(responses))


class TestJSONRepair:
    def test_plain_json(self):
        assert json_repair.loads('{"a": 1}') == {"a": 1}

    def test_markdown_fence(self):
        assert json_repair.loads('```json\n{"a": 1}\n```') == {"a": 1}

    def test_unlabelled_fence(self):
        assert json_repair.loads('```\n{"a": 1}\n```') == {"a": 1}

    def test_prose_around_json(self):
        text = 'Sure! Here is the result:\n{"a": 1}\nLet me know if you need more.'
        assert json_repair.loads(text) == {"a": 1}

    def test_trailing_commas(self):
        assert json_repair.loads('{"a": 1, "b": [1, 2,],}') == {"a": 1, "b": [1, 2]}

    def test_truncated_object_is_balanced(self):
        result = json_repair.loads('{"a": 1, "b": {"c": 2')
        assert result == {"a": 1, "b": {"c": 2}}

    def test_truncated_array_is_balanced(self):
        result = json_repair.loads('{"items": [1, 2, 3')
        assert result == {"items": [1, 2, 3]}

    def test_python_literals(self):
        assert json_repair.loads('{"a": True, "b": None}') == {"a": True, "b": None}

    def test_no_json_returns_none(self):
        assert json_repair.loads("I cannot help with that.") is None

    def test_empty_string_returns_none(self):
        assert json_repair.loads("") is None


class TestAIService:
    def test_disabled_without_a_key(self):
        assert not AIService(Settings(ai_provider="anthropic", ai_api_key="")).is_enabled

    def test_disabled_when_provider_is_none(self):
        assert not AIService(Settings(ai_provider="none", ai_api_key="k")).is_enabled

    def test_unknown_provider_degrades_instead_of_crashing(self):
        assert not AIService(Settings(ai_provider="wat", ai_api_key="k")).is_enabled

    @pytest.mark.asyncio
    async def test_structured_returns_none_when_disabled(self):
        disabled = AIService(Settings(ai_provider="none"))
        result = await disabled.structured(
            system="s", prompt="p", schema=LLMSemanticResponse
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_valid_response_is_parsed(self):
        ai = service(['{"domain": "sales", "dataset_title": "Sales Overview"}'])
        result = await ai.structured(
            system="s", prompt="p", schema=LLMSemanticResponse
        )
        assert result is not None
        assert result.domain == "sales"

    @pytest.mark.asyncio
    async def test_invalid_json_triggers_a_repair_retry(self):
        provider = FakeProvider(
            ["not json at all", '{"domain": "hr", "dataset_title": "People"}']
        )
        ai = AIService(Settings(ai_provider="fake", ai_api_key="x"), provider)
        result = await ai.structured(
            system="s", prompt="p", schema=LLMSemanticResponse
        )
        assert result is not None
        assert result.domain == "hr"
        assert len(provider.calls) == 2
        assert "could not be parsed" in provider.calls[1].prompt

    @pytest.mark.asyncio
    async def test_gives_up_after_the_retry_budget(self):
        settings = Settings(ai_provider="fake", ai_api_key="x", ai_max_retries=1)
        provider = FakeProvider(["garbage", "still garbage"])
        ai = AIService(settings, provider)
        assert await ai.structured(
            system="s", prompt="p", schema=LLMSemanticResponse
        ) is None
        assert len(provider.calls) == 2
        assert ai.last_error

    @pytest.mark.asyncio
    async def test_transport_error_does_not_retry(self):
        """A 401 will not be fixed by asking again more politely."""
        provider = FakeProvider([AIError("401 unauthorized")])
        ai = AIService(Settings(ai_provider="fake", ai_api_key="x"), provider)
        assert await ai.structured(
            system="s", prompt="p", schema=LLMSemanticResponse
        ) is None
        assert len(provider.calls) == 1

    @pytest.mark.asyncio
    async def test_schema_violation_is_rejected(self):
        ai = service(['{"insights": "should be a list"}'])
        assert await ai.structured(
            system="s", prompt="p", schema=LLMInsightResponse
        ) is None


class TestInsightGrounding:
    def _fixtures(self):
        kpis = [
            KPI(
                id="total_revenue",
                name="Total Revenue",
                value=1000.0,
                formatted_value="$1.0K",
                format=ValueFormat.CURRENCY,
                calculation="SUM(revenue)",
                why_it_matters="Top line.",
            )
        ]
        analysis = AnalysisResult(dataset_id="d", row_count=100)
        quality = DataQualityReport(
            dataset_id="d", rows_before=100, rows_after=100,
            columns_before=3, columns_after=3,
        )
        return kpis, analysis, quality

    def test_evidence_index_contains_kpis(self):
        kpis, analysis, quality = self._fixtures()
        index = build_evidence_index(kpis, analysis, quality)
        assert "total revenue" in index
        assert index["total revenue"].value == "$1.0K"

    @pytest.mark.asyncio
    async def test_ungrounded_insight_is_discarded(self):
        """An insight citing a metric we never computed is a hallucination."""
        kpis, analysis, quality = self._fixtures()
        payload = (
            '{"insights": [{"title": "Churn is spiking", '
            '"body": "Customer churn rose sharply this quarter across every '
            'segment we measured.", "category": "trend", "severity": "warning", '
            '"evidence_refs": ["Quarterly Churn Rate"]}]}'
        )
        insights, notes = await generate(
            _profile(), analysis, kpis, quality,
            ai=service([payload]), title="T", domain="sales",
        )
        assert not any(i.title == "Churn is spiking" for i in insights)
        assert any("never computed" in n for n in notes)

    @pytest.mark.asyncio
    async def test_grounded_insight_is_kept_with_its_evidence(self):
        kpis, analysis, quality = self._fixtures()
        payload = (
            '{"insights": [{"title": "Revenue reached one thousand", '
            '"body": "Total revenue for the period came to $1.0K across the '
            'rows that carried a value.", "category": "summary", '
            '"severity": "positive", "evidence_refs": ["Total Revenue"]}]}'
        )
        insights, _ = await generate(
            _profile(), analysis, kpis, quality,
            ai=service([payload]), title="T", domain="sales",
        )
        kept = next(i for i in insights if i.title.startswith("Revenue reached"))
        assert kept.evidence[0].metric == "Total Revenue"
        assert kept.evidence[0].value == "$1.0K"

    @pytest.mark.asyncio
    async def test_falls_back_to_rules_when_ai_fails(self):
        kpis, analysis, quality = self._fixtures()
        insights, notes = await generate(
            _profile(), analysis, kpis, quality,
            ai=service(["nonsense", "more nonsense", "still nonsense"]),
            title="T", domain="sales",
        )
        assert any("rule-based" in n for n in notes)

    @pytest.mark.asyncio
    async def test_works_with_no_ai_at_all(self):
        kpis, analysis, quality = self._fixtures()
        insights, notes = await generate(
            _profile(), analysis, kpis, quality,
            ai=AIService(Settings(ai_provider="none")),
            title="T", domain="sales",
        )
        assert notes == []
        assert isinstance(insights, list)


def _profile():
    from app.schemas.profile import DatasetProfile

    return DatasetProfile(
        dataset_id="d", name="t.csv", n_rows=100, n_columns=3,
        n_duplicate_rows=0, memory_bytes=1000, columns=[],
    )
