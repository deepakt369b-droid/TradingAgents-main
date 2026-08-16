"""Tests for TF-IDF cross-ticker lesson relevance ranking (Phase 3 memory addition)."""

import pytest

from tradingagents.agents.utils.lesson_similarity import rank_by_relevance


@pytest.mark.unit
class TestRankByRelevance:
    def test_empty_query_returns_empty(self):
        assert rank_by_relevance("", [(0, "some text about semiconductors")], top_n=3) == []

    def test_empty_candidates_returns_empty(self):
        assert rank_by_relevance("semiconductor AI capex", [], top_n=3) == []

    def test_query_with_only_stopwords_returns_empty(self):
        assert rank_by_relevance("the a is are", [(0, "semiconductor AI capex")], top_n=3) == []

    def test_more_relevant_candidate_ranked_first(self):
        query = "Semiconductor AI capex cycle intact, overbought RSI risk."
        candidates = [
            (0, "Airline fuel cost headwinds; unrelated to chip demand."),
            (1, "Semiconductor supply chain tight; AI capex accelerating."),
            (2, "Retail holiday sales beat expectations for consumer goods."),
        ]
        ranked = rank_by_relevance(query, candidates, top_n=3)
        assert ranked[0] == 1  # the semiconductor/AI capex entry

    def test_top_n_limits_results(self):
        query = "Semiconductor AI capex cycle intact."
        candidates = [(i, f"Semiconductor note number {i}.") for i in range(10)]
        ranked = rank_by_relevance(query, candidates, top_n=3)
        assert len(ranked) == 3

    def test_all_zero_relevance_still_returns_top_n_by_recency(self):
        # No token overlap at all with the query -- similarity is 0 for
        # every candidate, so the tiebreaker (recency / candidate order)
        # must still produce a stable, non-empty result rather than an
        # arbitrary or empty one.
        query = "xyzxyzxyz uniquetoken"
        candidates = [(0, "completely unrelated alpha"), (1, "completely unrelated beta")]
        ranked = rank_by_relevance(query, candidates, top_n=2)
        assert ranked == [0, 1]  # falls back to original (newest-first) order

    def test_identical_text_scores_highest(self):
        query = "Regulatory scrutiny in EU semiconductor exports intensifying."
        candidates = [
            (0, "Regulatory scrutiny in EU semiconductor exports intensifying."),
            (1, "Completely different topic about consumer retail spending."),
        ]
        ranked = rank_by_relevance(query, candidates, top_n=1)
        assert ranked == [0]
