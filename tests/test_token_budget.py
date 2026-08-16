"""Tests for the per-run token budget guard (Phase 3 token reduction).

A configured budget must trip the same park-on-quota-error path a provider
429 does, rather than either being killed outright mid-node or silently
running unbounded.
"""

import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from cli.stats_handler import StatsCallbackHandler
from tradingagents.llm_clients.llm_errors import TokenBudgetExceededError, is_quota_error


def _llm_result(input_tokens: int, output_tokens: int) -> LLMResult:
    msg = AIMessage(
        content="response",
        usage_metadata={
            "input_tokens": input_tokens, "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    )
    return LLMResult(generations=[[ChatGeneration(message=msg)]])


@pytest.mark.unit
class TestStatsCallbackHandlerBudget:
    def test_raise_error_is_enabled(self):
        # Required for LangChain's callback manager to actually propagate
        # the exception instead of swallowing it (verified empirically:
        # the default BaseCallbackHandler.raise_error is False).
        assert StatsCallbackHandler().raise_error is True

    def test_no_budget_never_raises(self):
        handler = StatsCallbackHandler(token_budget=None)
        for _ in range(10):
            handler.on_llm_end(_llm_result(10_000, 10_000))  # must not raise
        assert handler.tokens_in == 100_000
        assert handler.tokens_out == 100_000

    def test_within_budget_does_not_raise(self):
        handler = StatsCallbackHandler(token_budget=1000)
        handler.on_llm_end(_llm_result(400, 400))
        assert handler.tokens_in == 400
        assert handler.tokens_out == 400

    def test_exceeding_budget_raises(self):
        handler = StatsCallbackHandler(token_budget=1000)
        handler.on_llm_end(_llm_result(400, 400))  # 800, under budget
        with pytest.raises(TokenBudgetExceededError) as excinfo:
            handler.on_llm_end(_llm_result(300, 0))  # 1100, over budget
        assert excinfo.value.tokens_used == 1100
        assert excinfo.value.token_budget == 1000
        # Tokens from the call that tripped the budget are still counted --
        # the caller needs to know the real total, not a value frozen before
        # the tripping call.
        assert handler.tokens_in == 700
        assert handler.tokens_out == 400

    def test_stats_still_readable_after_budget_exceeded(self):
        handler = StatsCallbackHandler(token_budget=100)
        with pytest.raises(TokenBudgetExceededError):
            handler.on_llm_end(_llm_result(60, 60))
        stats = handler.get_stats()
        assert stats["tokens_in"] == 60
        assert stats["tokens_out"] == 60


@pytest.mark.unit
class TestTokenBudgetErrorClassifiedAsQuotaError:
    def test_is_quota_error_true(self):
        assert is_quota_error(TokenBudgetExceededError(1100, 1000)) is True

    def test_is_quota_error_true_when_wrapped(self):
        wrapper = RuntimeError("LLM call failed")
        wrapper.__cause__ = TokenBudgetExceededError(1100, 1000)
        assert is_quota_error(wrapper) is True

    def test_message_is_informative(self):
        err = TokenBudgetExceededError(1100, 1000)
        assert "1100" in str(err)
        assert "1000" in str(err)


@pytest.mark.unit
class TestCallbackManagerPropagation:
    """Regression check: raise_error must actually cause LangChain's
    callback manager to propagate the exception out of an LLM invocation,
    not just out of the handler method itself in isolation."""

    def test_langchain_propagates_when_raise_error_true(self):
        # FakeListChatModel doesn't populate usage_metadata, so drive this
        # through a subclass that raises unconditionally from on_llm_end --
        # isolates "does raise_error=True actually propagate through
        # LangChain's callback manager" from "does the token-counting logic
        # trip correctly" (covered by the tests above).
        from langchain_core.language_models.fake_chat_models import FakeListChatModel

        class _AlwaysOverBudget(StatsCallbackHandler):
            def on_llm_end(self, response, **kwargs):
                raise TokenBudgetExceededError(999, 1)

        llm = FakeListChatModel(responses=["a response"])
        with pytest.raises(TokenBudgetExceededError):
            llm.invoke("hello", config={"callbacks": [_AlwaysOverBudget()]})
