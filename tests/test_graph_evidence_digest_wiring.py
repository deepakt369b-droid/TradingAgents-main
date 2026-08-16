"""Structural test: the Evidence Digest node sits between the last analyst's
message-clear node and Bull Researcher (Phase 3 token reduction), for every
analyst-selection subset. Uses mock LLMs/tool nodes since this only checks
graph structure, never invokes a node.
"""

from unittest.mock import MagicMock

import pytest
from langgraph.prebuilt import ToolNode

from tradingagents.graph.conditional_logic import ConditionalLogic
from tradingagents.graph.setup import GraphSetup

_LAST_CLEAR_NODE = {
    "market": "Msg Clear Market",
    "social": "Msg Clear Sentiment",
    "news": "Msg Clear News",
    "fundamentals": "Msg Clear Fundamentals",
}


def _build_compiled_graph(selected_analysts):
    tool_nodes = {k: ToolNode([]) for k in ("market", "social", "news", "fundamentals")}
    cl = ConditionalLogic(max_debate_rounds=1, max_risk_discuss_rounds=1)
    gs = GraphSetup(MagicMock(), MagicMock(), tool_nodes, cl)
    return gs.setup_graph(selected_analysts).compile()


def _edge_set(compiled_graph):
    g = compiled_graph.get_graph()
    return {(e.source, e.target) for e in g.edges}, set(g.nodes.keys())


@pytest.mark.unit
class TestEvidenceDigestWiring:
    def test_node_present_for_full_analyst_selection(self):
        compiled = _build_compiled_graph(("market", "social", "news", "fundamentals"))
        edges, nodes = _edge_set(compiled)
        assert "Evidence Digest" in nodes
        assert ("Msg Clear Fundamentals", "Evidence Digest") in edges
        assert ("Evidence Digest", "Bull Researcher") in edges
        # The old direct edge must be gone -- Evidence Digest sits strictly
        # between the last analyst and Bull Researcher, not alongside it.
        assert ("Msg Clear Fundamentals", "Bull Researcher") not in edges

    @pytest.mark.parametrize("selected", [
        ("market",),
        ("market", "news"),
        ("social", "fundamentals"),
        ("market", "social", "news"),
    ])
    def test_node_present_for_partial_analyst_selection(self, selected):
        compiled = _build_compiled_graph(selected)
        edges, nodes = _edge_set(compiled)
        assert "Evidence Digest" in nodes
        assert ("Evidence Digest", "Bull Researcher") in edges
        last_clear = _LAST_CLEAR_NODE[selected[-1]]
        assert (last_clear, "Evidence Digest") in edges
        assert (last_clear, "Bull Researcher") not in edges

    def test_only_one_edge_into_bull_researcher(self):
        # Bull Researcher must be reachable only via Evidence Digest (plus
        # its own self-loop for debate rounds) -- not directly from any
        # analyst's clear node.
        compiled = _build_compiled_graph(("market", "social", "news", "fundamentals"))
        edges, _nodes = _edge_set(compiled)
        into_bull = {src for src, dst in edges if dst == "Bull Researcher"}
        assert into_bull == {"Evidence Digest", "Bear Researcher", "Bull Researcher"}
