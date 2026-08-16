"""Relevance ranking for cross-ticker memory-log lessons.

``TradingMemoryLog.get_past_context()`` previously picked its cross-ticker
"lessons learned" slice by pure recency -- the most recently resolved
entries for OTHER tickers, regardless of whether they have anything to do
with the ticker currently being analyzed. This ranks a larger recency-window
candidate pool by relevance to the current ticker's own history instead.

Deliberately NOT a neural embedding model: a sentence-transformers-class
dependency would pull in torch (hundreds of MB) for a personal, few-hundred-
entry markdown ledger, which is exactly the kind of heavy, LLM-call-on-write
dependency Phase 3 rejected for the agent-memory question in general (see the
project plan's "agent memory" section) and for ``token_optimizer``'s
LLMLingua-2 dependency specifically. TF-IDF cosine similarity over the
ledger's own short financial reflections is a lightweight, honest
approximation of "relevance" -- word-overlap on recurring terms (sector
names, catalysts, risk factors) -- computed in pure Python with zero new
dependencies, zero LLM calls, and zero new services.
"""

from __future__ import annotations

import math
import re
from collections import Counter

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Common English words plus generic finance-report boilerplate that would
# otherwise dominate every document's vector without discriminating between
# them (every reflection mentions "stock"/"price"/"market").
_STOPWORDS = frozenset("""
a an the this that these those is are was were be been being have has had
do does did will would could should may might must can shall
of in on at to for with by from as it its it's and or but not no nor
i you he she we they them his her our your their
stock price market trade traded trading buy sell hold position
""".split())


def _tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS and len(t) > 2]


def _tf(tokens: list[str]) -> Counter:
    return Counter(tokens)


def rank_by_relevance(
    query_text: str,
    candidates: list[tuple[int, str]],
    top_n: int,
) -> list[int]:
    """Return up to ``top_n`` candidate indices, most relevant to ``query_text`` first.

    ``candidates`` is a list of ``(index, text)`` pairs (the index is
    whatever the caller uses to look the original item back up -- here, a
    position in the loaded entry list). Ties fall back to candidate order
    (which the caller passes newest-first), so relevance strictly refines
    recency rather than replacing it outright.

    Returns an empty list when ``query_text`` has no usable tokens (nothing
    to compare against) or ``candidates`` is empty -- the caller falls back
    to its existing recency-based behavior in that case.
    """
    query_tokens = _tokenize(query_text)
    if not query_tokens or not candidates:
        return []

    doc_tokens = [_tokenize(text) for _, text in candidates]
    all_docs = [query_tokens] + doc_tokens

    # Document frequency across query + candidates, for IDF.
    df: Counter = Counter()
    for tokens in all_docs:
        df.update(set(tokens))
    n_docs = len(all_docs)
    idf = {term: math.log((n_docs + 1) / (count + 1)) + 1.0 for term, count in df.items()}

    def _vector(tokens: list[str]) -> dict[str, float]:
        tf = _tf(tokens)
        return {term: count * idf.get(term, 0.0) for term, count in tf.items()}

    query_vec = _vector(query_tokens)
    query_norm = math.sqrt(sum(v * v for v in query_vec.values()))
    if query_norm == 0:
        return []

    scored: list[tuple[float, int, int]] = []  # (similarity, -order, index)
    for order, ((idx, _text), tokens) in enumerate(zip(candidates, doc_tokens)):
        doc_vec = _vector(tokens)
        doc_norm = math.sqrt(sum(v * v for v in doc_vec.values()))
        if doc_norm == 0:
            similarity = 0.0
        else:
            dot = sum(v * doc_vec.get(term, 0.0) for term, v in query_vec.items())
            similarity = dot / (query_norm * doc_norm)
        # -order as a tiebreaker so equal-similarity candidates keep their
        # original (newest-first) relative order rather than an arbitrary
        # sort-stability accident.
        scored.append((similarity, -order, idx))

    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return [idx for _sim, _order, idx in scored[:top_n]]
