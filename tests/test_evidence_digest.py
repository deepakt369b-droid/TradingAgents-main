"""Tests for the Evidence Digest schema, render function, and node (Phase 3
token reduction: compress the four analyst reports into one digest instead of
re-sending them in full on every debate/risk turn).
"""

from unittest.mock import MagicMock

import pytest

from tradingagents.agents.evidence_digest import create_evidence_digest
from tradingagents.agents.schemas import EvidenceDigest, render_evidence_digest

# ---------------------------------------------------------------------------
# Schema / render
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEvidenceDigestSchema:
    def test_minimal_required_fields(self):
        d = EvidenceDigest(bull_points=["Revenue +12% YoY"], bear_points=["Valuation stretched"])
        assert d.key_figures == []
        assert d.catalysts == []
        assert d.risks == []
        assert d.data_gaps == []


@pytest.mark.unit
class TestRenderEvidenceDigest:
    def test_all_sections_present_when_populated(self):
        d = EvidenceDigest(
            bull_points=["Bull point A", "Bull point B"],
            bear_points=["Bear point A"],
            key_figures=["P/E 24.3"],
            catalysts=["Earnings on 2026-05-01"],
            risks=["Regulatory scrutiny in EU"],
            data_gaps=["No insider transaction data"],
        )
        md = render_evidence_digest(d)
        assert "**Bull points:**" in md
        assert "- Bull point A" in md
        assert "- Bull point B" in md
        assert "**Bear points:**" in md
        assert "- Bear point A" in md
        assert "**Key figures:**" in md
        assert "- P/E 24.3" in md
        assert "**Catalysts:**" in md
        assert "**Risks:**" in md
        assert "**Data gaps:**" in md

    def test_empty_optional_sections_omitted(self):
        d = EvidenceDigest(bull_points=["A"], bear_points=["B"])
        md = render_evidence_digest(d)
        assert "**Key figures:**" not in md
        assert "**Catalysts:**" not in md
        assert "**Risks:**" not in md
        assert "**Data gaps:**" not in md
        assert "**Bull points:**" in md
        assert "**Bear points:**" in md

    def test_render_is_substantially_smaller_than_four_full_reports(self):
        # The whole point of this node: the digest must not just be the four
        # reports concatenated back together.
        d = EvidenceDigest(
            bull_points=["Point " + "x" * 20 for _ in range(4)],
            bear_points=["Point " + "y" * 20 for _ in range(4)],
        )
        four_reports_len = 4 * 3000  # a realistic full analyst report is ~3000 chars
        assert len(render_evidence_digest(d)) < four_reports_len / 5


# ---------------------------------------------------------------------------
# Node factory: structured happy path + fallback
# ---------------------------------------------------------------------------


def _make_state():
    return {
        "company_of_interest": "NVDA",
        "asset_type": "stock",
        "instrument_context": "NVDA (NVIDIA Corporation), a US-listed stock.",
        "market_report": "RSI 71, overbought. 50DMA above 200DMA.",
        "sentiment_report": "StockTwits 75% bullish.",
        "news_report": "Earnings beat announced.",
        "fundamentals_report": "P/E 24.3 vs sector 19.1.",
    }


def _structured_digest_llm(captured: dict, digest: EvidenceDigest | None = None):
    if digest is None:
        digest = EvidenceDigest(
            bull_points=["Earnings beat", "StockTwits 75% bullish"],
            bear_points=["RSI 71 overbought", "P/E above sector"],
            key_figures=["P/E 24.3 vs sector 19.1", "RSI 71"],
        )
    structured = MagicMock()
    structured.invoke.side_effect = lambda prompt: (
        captured.__setitem__("prompt", prompt) or digest
    )
    llm = MagicMock()
    llm.with_structured_output.return_value = structured
    return llm


@pytest.mark.unit
class TestEvidenceDigestNode:
    def test_structured_path_produces_rendered_markdown(self):
        captured = {}
        node = create_evidence_digest(_structured_digest_llm(captured))
        result = node(_make_state())
        digest = result["evidence_digest"]
        assert "**Bull points:**" in digest
        assert "Earnings beat" in digest
        assert "**Bear points:**" in digest
        assert "RSI 71 overbought" in digest
        assert "**Key figures:**" in digest

    def test_prompt_includes_all_four_reports_and_instrument_context(self):
        captured = {}
        create_evidence_digest(_structured_digest_llm(captured))(_make_state())
        prompt = captured["prompt"]
        assert "RSI 71, overbought" in prompt
        assert "StockTwits 75% bullish" in prompt
        assert "Earnings beat announced" in prompt
        assert "P/E 24.3 vs sector 19.1" in prompt
        assert "NVDA (NVIDIA Corporation)" in prompt

    def test_crypto_asset_uses_crypto_fundamentals_label(self):
        captured = {}
        state = _make_state()
        state["asset_type"] = "crypto"
        create_evidence_digest(_structured_digest_llm(captured))(state)
        assert "may be unavailable for crypto" in captured["prompt"]

    def test_falls_back_to_freetext_when_structured_unavailable(self):
        plain = "Bulls cite earnings beat; bears cite overbought RSI."
        llm = MagicMock()
        llm.with_structured_output.side_effect = NotImplementedError("provider unsupported")
        llm.invoke.return_value = MagicMock(content=plain)
        node = create_evidence_digest(llm)
        assert node(_make_state())["evidence_digest"] == plain

    def test_falls_back_to_freetext_when_structured_call_fails(self):
        plain = "Fallback free-text digest."
        structured = MagicMock()
        structured.invoke.side_effect = ValueError("bad JSON from model")
        llm = MagicMock()
        llm.with_structured_output.return_value = structured
        llm.invoke.return_value = MagicMock(content=plain)
        node = create_evidence_digest(llm)
        assert node(_make_state())["evidence_digest"] == plain
