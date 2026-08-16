"""Test checkpoint resume: crash mid-analysis, re-run resumes from last node."""

import tempfile
import unittest
from typing import TypedDict

from langgraph.graph import END, StateGraph

from tradingagents.graph.checkpointer import (
    checkpoint_step,
    clear_checkpoint,
    get_checkpointer,
    has_checkpoint,
    thread_id,
)

# Mutable flag to simulate crash on first run
_should_crash = False


class _SimpleState(TypedDict):
    count: int


def _node_a(state: _SimpleState) -> dict:
    return {"count": state["count"] + 1}


def _node_b(state: _SimpleState) -> dict:
    if _should_crash:
        raise RuntimeError("simulated mid-analysis crash")
    return {"count": state["count"] + 10}


def _build_graph() -> StateGraph:
    builder = StateGraph(_SimpleState)
    builder.add_node("analyst", _node_a)
    builder.add_node("trader", _node_b)
    builder.set_entry_point("analyst")
    builder.add_edge("analyst", "trader")
    builder.add_edge("trader", END)
    return builder


class TestCheckpointResume(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.ticker = "TEST"
        self.date = "2026-04-20"

    def test_crash_and_resume(self):
        """Crash at 'trader' node, then resume from checkpoint."""
        global _should_crash
        builder = _build_graph()
        tid = thread_id(self.ticker, self.date)
        cfg = {"configurable": {"thread_id": tid}}

        # Run 1: crash at trader node
        _should_crash = True
        with get_checkpointer(self.tmpdir, self.ticker) as saver:
            graph = builder.compile(checkpointer=saver)
            with self.assertRaises(RuntimeError):
                graph.invoke({"count": 0}, config=cfg)

        # Checkpoint should exist at step 1 (analyst completed)
        self.assertTrue(has_checkpoint(self.tmpdir, self.ticker, self.date))
        step = checkpoint_step(self.tmpdir, self.ticker, self.date)
        self.assertEqual(step, 1)

        # Run 2: resume — trader succeeds this time
        _should_crash = False
        with get_checkpointer(self.tmpdir, self.ticker) as saver:
            graph = builder.compile(checkpointer=saver)
            result = graph.invoke(None, config=cfg)

        # analyst added 1, trader added 10 → 11
        self.assertEqual(result["count"], 11)

    def test_clear_checkpoint_allows_fresh_start(self):
        """After clearing, the graph starts from scratch."""
        global _should_crash
        builder = _build_graph()
        tid = thread_id(self.ticker, self.date)
        cfg = {"configurable": {"thread_id": tid}}

        # Create a checkpoint by crashing
        _should_crash = True
        with get_checkpointer(self.tmpdir, self.ticker) as saver:
            graph = builder.compile(checkpointer=saver)
            with self.assertRaises(RuntimeError):
                graph.invoke({"count": 0}, config=cfg)

        self.assertTrue(has_checkpoint(self.tmpdir, self.ticker, self.date))

        # Clear it
        clear_checkpoint(self.tmpdir, self.ticker, self.date)
        self.assertFalse(has_checkpoint(self.tmpdir, self.ticker, self.date))

        # Fresh run succeeds from scratch
        _should_crash = False
        with get_checkpointer(self.tmpdir, self.ticker) as saver:
            graph = builder.compile(checkpointer=saver)
            result = graph.invoke({"count": 0}, config=cfg)

        self.assertEqual(result["count"], 11)


    def test_different_date_starts_fresh(self):
        """A different date must NOT resume from an existing checkpoint."""
        global _should_crash
        builder = _build_graph()
        date2 = "2026-04-21"

        # Run with date1 — crash to leave a checkpoint
        _should_crash = True
        tid1 = thread_id(self.ticker, self.date)
        with get_checkpointer(self.tmpdir, self.ticker) as saver:
            graph = builder.compile(checkpointer=saver)
            with self.assertRaises(RuntimeError):
                graph.invoke({"count": 0}, config={"configurable": {"thread_id": tid1}})

        self.assertTrue(has_checkpoint(self.tmpdir, self.ticker, self.date))

        # date2 should have no checkpoint
        self.assertFalse(has_checkpoint(self.tmpdir, self.ticker, date2))

        # Run with date2 — should start fresh and succeed
        _should_crash = False
        tid2 = thread_id(self.ticker, date2)
        self.assertNotEqual(tid1, tid2)

        with get_checkpointer(self.tmpdir, self.ticker) as saver:
            graph = builder.compile(checkpointer=saver)
            result = graph.invoke({"count": 0}, config={"configurable": {"thread_id": tid2}})

        # Fresh run: analyst +1, trader +10 = 11
        self.assertEqual(result["count"], 11)

        # Original date checkpoint still exists (untouched)
        self.assertTrue(has_checkpoint(self.tmpdir, self.ticker, self.date))


class TestCheckpointSignature(unittest.TestCase):
    """A different graph shape (analyst selection / depth / asset mode) must not
    resume the previous run's checkpoint (#1089)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.ticker = "TEST"
        self.date = "2026-04-20"

    def test_empty_signature_is_legacy_id(self):
        self.assertEqual(
            thread_id(self.ticker, self.date),
            thread_id(self.ticker, self.date, ""),
        )

    def test_signature_changes_thread_id(self):
        legacy = thread_id(self.ticker, self.date)
        sig_a = thread_id(self.ticker, self.date, "analysts=market,news|asset=stock")
        sig_b = thread_id(self.ticker, self.date, "analysts=market|asset=stock")
        self.assertNotEqual(sig_a, sig_b)          # different graph shapes differ
        self.assertNotEqual(legacy, sig_a)         # signature-keyed differs from legacy
        self.assertEqual(                          # same inputs are stable
            sig_a, thread_id(self.ticker, self.date, "analysts=market,news|asset=stock")
        )

    def test_different_signature_starts_fresh(self):
        global _should_crash
        builder = _build_graph()
        sig1 = "analysts=market,news,fundamentals|asset=stock"
        sig2 = "analysts=market|asset=stock"       # dropped analysts -> different graph

        _should_crash = True
        tid1 = thread_id(self.ticker, self.date, sig1)
        with get_checkpointer(self.tmpdir, self.ticker) as saver:
            graph = builder.compile(checkpointer=saver)
            with self.assertRaises(RuntimeError):
                graph.invoke({"count": 0}, config={"configurable": {"thread_id": tid1}})

        self.assertTrue(has_checkpoint(self.tmpdir, self.ticker, self.date, sig1))
        # A different graph shape has no checkpoint to resume from.
        self.assertFalse(has_checkpoint(self.tmpdir, self.ticker, self.date, sig2))

        _should_crash = False
        tid2 = thread_id(self.ticker, self.date, sig2)
        self.assertNotEqual(tid1, tid2)
        with get_checkpointer(self.tmpdir, self.ticker) as saver:
            graph = builder.compile(checkpointer=saver)
            result = graph.invoke({"count": 0}, config={"configurable": {"thread_id": tid2}})
        self.assertEqual(result["count"], 11)
        # sig1's checkpoint remains untouched.
        self.assertTrue(has_checkpoint(self.tmpdir, self.ticker, self.date, sig1))

    def test_run_signature_captures_graph_shape(self):
        from tradingagents.graph.trading_graph import TradingAgentsGraph

        # Build a bare instance to exercise the pure helper without heavy __init__.
        g = object.__new__(TradingAgentsGraph)
        g.selected_analysts = ("market", "news")
        g.config = {"max_debate_rounds": 1, "max_risk_discuss_rounds": 1}
        base = g._run_signature("stock")

        self.assertNotEqual(base, g._run_signature("crypto"))     # asset mode
        g.selected_analysts = ("market",)
        self.assertNotEqual(base, g._run_signature("stock"))      # analyst selection
        g.selected_analysts = ("market", "news")
        g.config = {"max_debate_rounds": 3, "max_risk_discuss_rounds": 1}
        self.assertNotEqual(base, g._run_signature("stock"))      # debate depth
        g.config = {"max_debate_rounds": 1, "max_risk_discuss_rounds": 5}
        self.assertNotEqual(base, g._run_signature("stock"))      # risk depth
        # Stable for identical inputs.
        g.config = {"max_debate_rounds": 1, "max_risk_discuss_rounds": 1}
        self.assertEqual(base, g._run_signature("stock"))


class TestSmartResumeSkipsCompletedNodes(unittest.TestCase):
    """Resume must pass ``None`` as input, not a fresh initial state.

    LangGraph only skips already-completed nodes when the resuming
    ``invoke``/``stream`` call receives ``input=None`` on a thread with an
    existing checkpoint. A non-None input -- even one identical to the
    original -- causes LangGraph to re-execute every node from START,
    silently re-invoking every already-completed LLM call. This mirrors the
    resume pattern ``TradingAgentsGraph._run_graph`` uses: gate on
    ``checkpoint_step(...) is not None`` to decide whether to pass the fresh
    state or ``None``.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.ticker = "TEST"
        self.date = "2026-04-20"

    def _resolve_graph_input(self, fresh_state, tid, sig=""):
        """Mirrors the gating logic in TradingAgentsGraph._run_graph."""
        resuming = checkpoint_step(self.tmpdir, self.ticker, self.date, sig) is not None
        return None if resuming else fresh_state

    def test_node_a_does_not_rerun_on_resume(self):
        global _should_crash
        builder = _build_graph()
        tid = thread_id(self.ticker, self.date)
        cfg = {"configurable": {"thread_id": tid}}
        calls = {"a": 0, "b": 0}

        def counted_node_a(state):
            calls["a"] += 1
            return _node_a(state)

        def counted_node_b(state):
            calls["b"] += 1
            return _node_b(state)

        counted_builder = StateGraph(_SimpleState)
        counted_builder.add_node("analyst", counted_node_a)
        counted_builder.add_node("trader", counted_node_b)
        counted_builder.set_entry_point("analyst")
        counted_builder.add_edge("analyst", "trader")
        counted_builder.add_edge("trader", END)

        _should_crash = True
        with get_checkpointer(self.tmpdir, self.ticker) as saver:
            graph = counted_builder.compile(checkpointer=saver)
            fresh_input = self._resolve_graph_input({"count": 0}, tid)
            with self.assertRaises(RuntimeError):
                graph.invoke(fresh_input, config=cfg)

        self.assertEqual(calls, {"a": 1, "b": 1})

        _should_crash = False
        with get_checkpointer(self.tmpdir, self.ticker) as saver:
            graph = counted_builder.compile(checkpointer=saver)
            resumed_input = self._resolve_graph_input({"count": 0}, tid)
            self.assertIsNone(resumed_input)  # a checkpoint exists -> resume, not restart
            result = graph.invoke(resumed_input, config=cfg)

        # analyst must NOT have re-run; only trader (the failed node) reruns.
        self.assertEqual(calls, {"a": 1, "b": 2})
        self.assertEqual(result["count"], 11)

    def test_fresh_thread_gets_the_initial_state_not_none(self):
        # A thread with no prior checkpoint must get the fresh state --
        # passing None here would raise EmptyInputError.
        tid = thread_id(self.ticker, self.date)
        resolved = self._resolve_graph_input({"count": 0}, tid)
        self.assertEqual(resolved, {"count": 0})


if __name__ == "__main__":
    unittest.main()
