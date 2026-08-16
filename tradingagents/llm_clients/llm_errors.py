"""Classify LLM call failures that should PARK a checkpointed run instead of
crashing it outright.

A quota/rate-limit/billing failure is recoverable -- retrying the same
request later, or on a different provider, can succeed. A malformed prompt,
a bug in agent code, or a genuine provider outage is not something a resume
under a different model fixes, so those are left to propagate and crash the
run as before (the checkpoint is still intact either way -- LangGraph only
clears it on success -- but only a classified quota error gets a parked-run
record and a clear "swap providers and resume" message).

Duck-typed rather than importing every provider SDK: this module must not
force-import openai/anthropic/google-genai just to classify an exception
that arrived from whichever ones happen to be installed.
"""

from __future__ import annotations

import re
from typing import Any

# HTTP status codes providers use for "you cannot make this call right now
# for account/billing/quota reasons" -- 429 (rate limit) is the common case;
# 402 (payment required) and some providers' overloaded-401/403 billing
# responses are included as well since we treat all of them the same way
# here (park and let the user swap providers or wait).
_QUOTA_STATUS_CODES = {402, 429}

# Fallback substring match for exception shapes without a reliable status
# code attribute (generic OpenAI-compatible endpoints, raw HTTP errors,
# provider-specific wrappers). Matched case-insensitively against str(exc).
_QUOTA_MESSAGE_PATTERNS = (
    re.compile(r"\binsufficient[_ ]quota\b", re.I),
    re.compile(r"\binsufficient[_ ]credits?\b", re.I),
    re.compile(r"\binsufficient[_ ]balance\b", re.I),
    re.compile(r"\bquota[_ ]exceeded\b", re.I),
    re.compile(r"\brate[_ ]limit", re.I),
    re.compile(r"\btoo many requests\b", re.I),
    re.compile(r"\bbilling\b", re.I),
    re.compile(r"\b429\b"),
)


def _status_code(exc: BaseException) -> int | None:
    """Best-effort extraction of an HTTP status code from an SDK exception.

    Covers openai/anthropic (``.status_code``), google-genai
    (``.code``), and generic ``requests``/``httpx`` wrappers that expose a
    ``.response.status_code``.
    """
    for attr in ("status_code", "code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    if isinstance(value, int):
        return value
    return None


class TokenBudgetExceededError(RuntimeError):
    """Raised by StatsCallbackHandler when a run's configured token budget is exceeded.

    Not an HTTP/provider error -- a local, deliberate stop -- but it is
    treated the same way a quota error is: the run parks with an intact
    checkpoint rather than either being killed outright or (worse) silently
    continuing to spend past the configured ceiling. See
    ``is_quota_error``'s isinstance check.
    """

    def __init__(self, tokens_used: int, token_budget: int):
        self.tokens_used = tokens_used
        self.token_budget = token_budget
        super().__init__(
            f"Token budget exceeded: used {tokens_used} of {token_budget} tokens for this run."
        )


def is_quota_error(exc: BaseException) -> bool:
    """Whether ``exc`` represents a quota/rate-limit/billing failure.

    Walks the exception's ``__cause__``/``__context__`` chain (LangChain and
    provider SDKs frequently wrap the underlying HTTP error), classifying by
    status code first and falling back to a message substring match.
    ``TokenBudgetExceededError`` -- a local, deliberate stop rather than a
    provider error -- is classified the same way so it parks instead of
    crashing the run.
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))

        if isinstance(current, TokenBudgetExceededError):
            return True

        code = _status_code(current)
        if code in _QUOTA_STATUS_CODES:
            return True

        text = str(current)
        if any(pattern.search(text) for pattern in _QUOTA_MESSAGE_PATTERNS):
            return True

        current = current.__cause__ or current.__context__
    return False


class RunParkedError(RuntimeError):
    """Raised when a run is parked after a classified quota/rate-limit failure.

    The checkpoint is intact and the failure has been recorded in the run
    registry; carries enough context for a caller to report a clear
    "resumable, swap providers or wait" message instead of a bare traceback.
    """

    def __init__(
        self, ticker: str, trade_date: str, thread_id: str, failed_role: str,
        failed_provider: str, cause: BaseException,
    ):
        self.ticker = ticker
        self.trade_date = trade_date
        self.thread_id = thread_id
        self.failed_role = failed_role
        self.failed_provider = failed_provider
        super().__init__(
            f"Run for {ticker} on {trade_date} parked: {failed_role}-thinking "
            f"provider '{failed_provider}' hit a quota/rate-limit error "
            f"({cause}). The checkpoint is intact -- resume this run, "
            f"optionally with a different provider for {failed_role}-thinking."
        )
        self.__cause__ = cause


def describe_error(exc: BaseException) -> dict[str, Any]:
    """Return a small JSON-safe summary of ``exc`` for a parked-run record."""
    return {
        "type": type(exc).__name__,
        "message": str(exc)[:500],
        "status_code": _status_code(exc),
        "is_quota_error": is_quota_error(exc),
    }
