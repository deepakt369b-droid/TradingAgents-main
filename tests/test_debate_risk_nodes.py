"""Tests for the 5 debate/risk nodes after Phase 3 token-reduction changes:
they must read `state["evidence_digest"]` (not the 4 raw reports) and must
append to history via `append_turn` (bounded, not unbounded concatenation).
"""

from unittest.mock import MagicMock

import pytest

from tradingagents.agents.researchers.bear_researcher import create_bear_researcher
from tradingagents.agents.researchers.bull_researcher import create_bull_researcher
from tradingagents.agents.risk_mgmt.aggressive_debator import create_aggressive_debator
from tradingagents.agents.risk_mgmt.conservative_debator import create_conservative_debator
from tradingagents.agents.risk_mgmt.neutral_debator import create_neutral_debator


def _llm_returning(text):
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content=text)
    return llm


def _debate_state(**overrides):
    state = {
        "company_of_interest": "NVDA",
        "asset_type": "stock",
        "instrument_context": "NVDA (NVIDIA Corporation).",
        "evidence_digest": "**Bull points:**\n- Earnings beat\n**Bear points:**\n- Overbought RSI",
        "investment_debate_state": {
            "history": "",
            "bull_history": "",
            "bear_history": "",
            "current_response": "",
            "judge_decision": "",
            "count": 0,
        },
    }
    state.update(overrides)
    return state


def _risk_state(**overrides):
    state = {
        "company_of_interest": "NVDA",
        "asset_type": "stock",
        "instrument_context": "NVDA (NVIDIA Corporation).",
        "evidence_digest": "**Bull points:**\n- Earnings beat\n**Bear points:**\n- Overbought RSI",
        "trader_investment_plan": "**Action**: Buy\nFINAL TRANSACTION PROPOSAL: **BUY**",
        "risk_debate_state": {
            "history": "",
            "aggressive_history": "",
            "conservative_history": "",
            "neutral_history": "",
            "latest_speaker": "",
            "current_aggressive_response": "",
            "current_conservative_response": "",
            "current_neutral_response": "",
            "judge_decision": "",
            "count": 0,
        },
    }
    state.update(overrides)
    return state


@pytest.mark.unit
class TestBullBearReadEvidenceDigest:
    def test_bull_prompt_contains_evidence_digest_not_raw_reports(self):
        llm = _llm_returning("Bull argument text.")
        node = create_bull_researcher(llm)
        node(_debate_state())
        prompt = llm.invoke.call_args[0][0]
        assert "Earnings beat" in prompt
        assert "Overbought RSI" in prompt

    def test_bear_prompt_contains_evidence_digest(self):
        llm = _llm_returning("Bear argument text.")
        node = create_bear_researcher(llm)
        node(_debate_state())
        prompt = llm.invoke.call_args[0][0]
        assert "Earnings beat" in prompt

    def test_bull_appends_bounded_history(self):
        # Seed history at the truncation limit; one more turn must trigger
        # the omission note, proving append_turn (not raw concatenation) is
        # wired in.
        from tradingagents.agents.utils.debate_history import DEFAULT_MAX_TURNS

        seeded = "\n".join(f"Bull Analyst: Turn {i}." for i in range(DEFAULT_MAX_TURNS))
        llm = _llm_returning("New bull argument.")
        node = create_bull_researcher(llm)
        result = node(_debate_state(
            investment_debate_state={
                "history": seeded, "bull_history": seeded, "bear_history": "",
                "current_response": "", "judge_decision": "", "count": DEFAULT_MAX_TURNS,
            }
        ))
        assert "omitted for brevity" in result["investment_debate_state"]["history"]


@pytest.mark.unit
class TestRiskNodesReadEvidenceDigest:
    @pytest.mark.parametrize("factory,key", [
        (create_aggressive_debator, "current_aggressive_response"),
        (create_conservative_debator, "current_conservative_response"),
        (create_neutral_debator, "current_neutral_response"),
    ])
    def test_prompt_contains_evidence_digest(self, factory, key):
        llm = _llm_returning("Argument text.")
        node = factory(llm)
        result = node(_risk_state())
        prompt = llm.invoke.call_args[0][0]
        assert "Earnings beat" in prompt
        assert result["risk_debate_state"][key]

    def test_aggressive_appends_bounded_history(self):
        from tradingagents.agents.utils.debate_history import DEFAULT_MAX_TURNS

        seeded = "\n".join(f"Aggressive Analyst: Turn {i}." for i in range(DEFAULT_MAX_TURNS))
        llm = _llm_returning("New argument.")
        node = create_aggressive_debator(llm)
        result = node(_risk_state(
            risk_debate_state={
                "history": seeded, "aggressive_history": seeded,
                "conservative_history": "", "neutral_history": "",
                "latest_speaker": "", "current_aggressive_response": "",
                "current_conservative_response": "", "current_neutral_response": "",
                "judge_decision": "", "count": DEFAULT_MAX_TURNS,
            }
        ))
        assert "omitted for brevity" in result["risk_debate_state"]["history"]
