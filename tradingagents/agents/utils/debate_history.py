"""Bounded debate-history accumulation for the researcher/risk debate nodes.

``InvestDebateState.history`` and ``RiskDebateState.history`` previously grew
by unbounded string concatenation, and all five debate/risk nodes re-send the
*entire* accumulated history on every one of their turns -- so with
``max_debate_rounds``/``max_risk_discuss_rounds`` raised above the default of
1, the cost compounds quadratically across nodes and rounds (Phase 3 token
reduction). ``append_turn`` caps the transcript actually fed back into the
debate prompts to the most recent turns; nothing else is affected -- the
per-speaker history fields (``bull_history``/``aggressive_history``/etc.),
the saved report tree, and the JSON state log all still accumulate every
turn in full.
"""

from __future__ import annotations

import re

# The five turn-opening prefixes every debate/risk argument is written with
# (see the "argument = f"{Speaker}: {response.content}"" line in each node).
# A turn boundary is recognized only at the start of a line, matching how a
# human reader would parse the same transcript.
_SPEAKER_PREFIXES = (
    "Bull Analyst: ",
    "Bear Analyst: ",
    "Aggressive Analyst: ",
    "Conservative Analyst: ",
    "Neutral Analyst: ",
)
_SPEAKER_SPLIT_RE = re.compile(
    r"(?=^(?:" + "|".join(re.escape(p) for p in _SPEAKER_PREFIXES) + r"))",
    re.MULTILINE,
)

# Generous default: well above what the default max_debate_rounds=1 (2 turns)
# / max_risk_discuss_rounds=1 (3 turns) ever produces, so a default-config run
# never truncates. Only kicks in for runs configured with many more rounds.
DEFAULT_MAX_TURNS = 6


def append_turn(history: str, argument: str, max_turns: int = DEFAULT_MAX_TURNS) -> str:
    """Append ``argument`` to ``history``, keeping only the most recent ``max_turns`` turns.

    Returns the full combined history unchanged when it's still within the
    turn limit -- this is a cap, not a per-turn truncation.
    """
    combined = (history + "\n" + argument).strip("\n")
    turns = [t for t in _SPEAKER_SPLIT_RE.split(combined) if t.strip()]
    if len(turns) <= max_turns:
        return combined

    omitted = len(turns) - max_turns
    kept = turns[-max_turns:]
    note = f"[{omitted} earlier debate turn{'s' if omitted != 1 else ''} omitted for brevity]"
    return note + "\n" + "\n".join(t.rstrip("\n") for t in kept)
