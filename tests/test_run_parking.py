"""Integration-level tests: a quota error during _run_graph parks the run;
other errors propagate unchanged; success after a park marks it resolved.

Builds a bare TradingAgentsGraph instance (mirroring the pattern already
used by TestCheckpointSignature.test_run_signature_captures_graph_shape in
test_checkpoint_resume.py) with the graph/memory_log/propagator collaborators
stubbed out, so this exercises the real _run_graph exception-handling path
without constructing real LLM clients.
"""

import tempfile

import httpx
import openai
import pytest

from tradingagents.graph import run_registry
from tradingagents.graph.checkpointer import checkpoint_step
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.llm_clients.llm_errors import RunParkedError


def _rate_limit_error(url):
    req = httpx.Request("POST", url)
    resp = httpx.Response(429, request=req)
    return openai.RateLimitError("rate limited", response=resp, body=None)


class _StubMemoryLog:
    def get_past_context(self, ticker):
        return ""

    def store_decision(self, **kwargs):
        pass


class _StubPropagator:
    def create_initial_state(self, *a, **kw):
        return {"count": 0}

    def get_graph_args(self):
        return {"stream_mode": "values", "config": {}}


class _StubGraph:
    """Raises on the first N invoke() calls, then succeeds."""

    def __init__(self, exc, fail_times=1):
        self.exc = exc
        self.fail_times = fail_times
        self.calls = 0

    def invoke(self, *a, **kw):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return {
            "company_of_interest": "AAPL",
            "trade_date": "2026-04-20",
            "market_report": "",
            "sentiment_report": "",
            "news_report": "",
            "fundamentals_report": "",
            "investment_debate_state": {
                "bull_history": "", "bear_history": "", "history": "",
                "current_response": "", "judge_decision": "",
            },
            "trader_investment_plan": "",
            "risk_debate_state": {
                "aggressive_history": "", "conservative_history": "",
                "neutral_history": "", "history": "", "judge_decision": "",
            },
            "investment_plan": "",
            "final_trade_decision": "FINAL TRANSACTION PROPOSAL: **HOLD**",
        }


def _bare_graph(tmpdir, exc, fail_times=1, checkpoint_enabled=True):
    g = object.__new__(TradingAgentsGraph)
    g.config = {
        "checkpoint_enabled": checkpoint_enabled,
        "data_cache_dir": tmpdir,
        "results_dir": tmpdir,
        "max_debate_rounds": 1,
        "max_risk_discuss_rounds": 1,
    }
    g.debug = False
    # propagate() sets self.ticker before calling _run_graph; these tests
    # call _run_graph directly, so mirror that here.
    g.ticker = "AAPL"
    g.selected_analysts = ("market",)
    g.memory_log = _StubMemoryLog()
    g.propagator = _StubPropagator()
    g.log_states_dict = {}
    g._role_hosts = {
        "deep": ("kimi", "api.moonshot.ai"),
        "quick": ("ollama", "localhost"),
    }
    g.graph = _StubGraph(exc, fail_times=fail_times)
    g.resolve_instrument_context = lambda *a, **k: ""
    g.process_signal = lambda full_signal: "Hold"
    return g


@pytest.mark.unit
class TestRunParking:
    def test_quota_error_parks_run_and_raises_run_parked_error(self):
        tmpdir = tempfile.mkdtemp()
        exc = _rate_limit_error("http://localhost:11434/v1/chat/completions")
        g = _bare_graph(tmpdir, exc, fail_times=99)  # always fails

        with pytest.raises(RunParkedError) as excinfo:
            g._run_graph("AAPL", "2026-04-20")

        err = excinfo.value
        assert err.ticker == "AAPL"
        assert err.failed_role == "quick"  # matched the "localhost" host
        assert err.failed_provider == "ollama"

        parked = run_registry.list_parked_runs(tmpdir)
        assert len(parked) == 1
        assert parked[0]["ticker"] == "AAPL"
        assert parked[0]["failed_role"] == "quick"

        # Checkpoint step lookup must not itself have crashed even though no
        # real checkpointer ever wrote anything for this stubbed graph.
        assert checkpoint_step(tmpdir, "AAPL", "2026-04-20", g._run_signature("stock")) is None

    def test_non_quota_error_propagates_and_does_not_park(self):
        tmpdir = tempfile.mkdtemp()
        exc = ValueError("malformed schema")
        g = _bare_graph(tmpdir, exc, fail_times=99)

        with pytest.raises(ValueError):
            g._run_graph("AAPL", "2026-04-20")

        assert run_registry.list_parked_runs(tmpdir) == []

    def test_quota_error_without_checkpointing_propagates_and_does_not_park(self):
        tmpdir = tempfile.mkdtemp()
        exc = _rate_limit_error("http://localhost:11434/v1/chat/completions")
        g = _bare_graph(tmpdir, exc, fail_times=99, checkpoint_enabled=False)

        with pytest.raises(openai.RateLimitError):
            g._run_graph("AAPL", "2026-04-20")

        assert run_registry.list_parked_runs(tmpdir) == []

    def test_success_after_park_marks_registry_resolved(self):
        tmpdir = tempfile.mkdtemp()
        exc = _rate_limit_error("https://api.moonshot.ai/v1/chat/completions")
        g = _bare_graph(tmpdir, exc, fail_times=1)  # fails once, then succeeds

        with pytest.raises(RunParkedError):
            g._run_graph("AAPL", "2026-04-20")
        assert len(run_registry.list_parked_runs(tmpdir)) == 1
        assert run_registry.list_parked_runs(tmpdir)[0]["failed_role"] == "deep"

        # Second call succeeds (StubGraph.calls now > fail_times).
        final_state, signal = g._run_graph("AAPL", "2026-04-20")
        assert final_state["final_trade_decision"].startswith("FINAL")
        assert run_registry.list_parked_runs(tmpdir) == []
        assert len(run_registry.list_parked_runs(tmpdir, status="resumed")) == 1

    def test_ambiguous_host_falls_back_to_unknown_role(self):
        tmpdir = tempfile.mkdtemp()
        exc = _rate_limit_error("https://api.somewhere-else.example/v1/chat/completions")
        g = _bare_graph(tmpdir, exc, fail_times=99)

        with pytest.raises(RunParkedError) as excinfo:
            g._run_graph("AAPL", "2026-04-20")
        assert excinfo.value.failed_role == "unknown"
