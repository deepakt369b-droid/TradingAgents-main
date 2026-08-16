"""Evidence Digest: compresses the four analyst reports for the debate layer.

Inserted between the last analyst and the Bull/Bear researchers (see
graph/setup.py). One quick-model call replaces four full reports being
re-sent, in full, on every one of the five debate/risk nodes' turns -- the
single largest token cost in the pipeline (see Phase 3 of the project plan).
The full reports are untouched everywhere else: disk logs, the markdown
report tree, and the CLI/web report display all still show them in full.
"""

from __future__ import annotations

from tradingagents.agents.schemas import EvidenceDigest, render_evidence_digest
from tradingagents.agents.utils.agent_utils import (
    get_instrument_context_from_state,
    get_language_instruction,
)
from tradingagents.agents.utils.structured import (
    bind_structured,
    invoke_structured_or_freetext,
)


def create_evidence_digest(llm):
    structured_llm = bind_structured(llm, EvidenceDigest, "Evidence Digest")

    def evidence_digest_node(state) -> dict:
        instrument_context = get_instrument_context_from_state(state)
        asset_type = state.get("asset_type", "stock")
        fundamentals_label = (
            "Company fundamentals report"
            if asset_type == "stock"
            else "Asset fundamentals report (may be unavailable for crypto)"
        )

        prompt = f"""You are compressing four analyst reports into a compact evidence digest for a bull/bear debate and a risk-management debate that follow. Extract only concrete, citable evidence -- specific numbers, dates, named events, and factual claims. Do not add analysis, opinions, or a recommendation of your own; that happens in the debates that read your digest.

{instrument_context}

Market research report: {state["market_report"]}
Social media sentiment report: {state["sentiment_report"]}
Latest world affairs news: {state["news_report"]}
{fundamentals_label}: {state["fundamentals_report"]}

Extract bull points and bear points as separate lists -- the same underlying report often contains evidence useful to both sides (e.g. high growth is bullish, high valuation from that growth is bearish); include a fact in both lists if it genuinely supports both arguments. List named risks and catalysts separately from the bear/bull points if the reports call any out specifically. Note in data_gaps anything a report says is missing, stale, or unavailable, so the debaters don't overstate confidence in thin evidence.
""" + get_language_instruction()

        digest = invoke_structured_or_freetext(
            structured_llm,
            llm,
            prompt,
            render_evidence_digest,
            "Evidence Digest",
        )

        return {"evidence_digest": digest}

    return evidence_digest_node
