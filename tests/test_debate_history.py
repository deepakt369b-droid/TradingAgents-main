"""Tests for bounded debate-history accumulation (Phase 3 token reduction)."""

import pytest

from tradingagents.agents.utils.debate_history import DEFAULT_MAX_TURNS, append_turn


@pytest.mark.unit
class TestAppendTurn:
    def test_starts_empty(self):
        assert append_turn("", "Bull Analyst: First argument.") == "Bull Analyst: First argument."

    def test_appends_below_limit_unchanged(self):
        history = "Bull Analyst: One."
        result = append_turn(history, "Bear Analyst: Two.", max_turns=6)
        assert result == "Bull Analyst: One.\nBear Analyst: Two."

    def test_truncates_beyond_limit(self):
        # append_turn truncates on every call (bounding growth as it goes,
        # not just at the end), so only the tail of the transcript survives.
        history = ""
        speakers = ["Bull Analyst", "Bear Analyst"] * 5  # 10 turns
        for i, speaker in enumerate(speakers):
            history = append_turn(history, f"{speaker}: Turn {i}.", max_turns=4)
        assert "omitted for brevity" in history
        assert "Turn 9." in history
        assert "Turn 6." in history
        assert "Turn 5." not in history
        assert "Turn 0." not in history

    def test_single_call_reports_correct_omitted_count(self):
        # A single call given a long pre-existing history (the realistic
        # shape: history accumulated so far, one new argument appended)
        # reports the true number of turns dropped by that call.
        history = "\n".join(f"Bull Analyst: Turn {i}." for i in range(6))
        result = append_turn(history, "Bear Analyst: Turn 6.", max_turns=4)
        assert "[3 earlier debate turns omitted for brevity]" in result
        assert "Turn 6." in result
        assert "Turn 3." in result
        assert "Turn 2." not in result

    def test_singular_omitted_note(self):
        history = ""
        for i in range(3):
            history = append_turn(history, f"Bull Analyst: Turn {i}.", max_turns=2)
        assert "[1 earlier debate turn omitted for brevity]" in history

    def test_risk_debate_speakers_also_split_correctly(self):
        history = ""
        turns = [
            "Aggressive Analyst: Push hard.",
            "Conservative Analyst: Be careful.",
            "Neutral Analyst: Middle ground.",
            "Aggressive Analyst: Counter.",
            "Conservative Analyst: Counter.",
        ]
        for t in turns:
            history = append_turn(history, t, max_turns=3)
        assert "Neutral Analyst: Middle ground." in history
        assert "Aggressive Analyst: Counter." in history
        assert "Conservative Analyst: Counter." in history
        assert "Push hard." not in history

    def test_multiline_argument_content_preserved(self):
        # A turn's own content may span multiple lines; only lines starting
        # with an exact speaker prefix are treated as new turn boundaries.
        history = append_turn(
            "",
            "Bull Analyst: First point.\nSecond point, still bull.\nThird point.",
        )
        assert "First point.\nSecond point, still bull.\nThird point." in history

    def test_default_max_turns_never_truncates_default_round_counts(self):
        # max_debate_rounds=1 -> 2 turns; max_risk_discuss_rounds=1 -> 3
        # turns. Both are well under DEFAULT_MAX_TURNS, so a default-config
        # run must never see the omission note.
        assert DEFAULT_MAX_TURNS > 3
        history = ""
        for i in range(3):
            history = append_turn(history, f"Aggressive Analyst: Turn {i}.")
        assert "omitted" not in history
