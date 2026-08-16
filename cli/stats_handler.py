import threading
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage
from langchain_core.outputs import LLMResult

from tradingagents.llm_clients.llm_errors import TokenBudgetExceededError


class StatsCallbackHandler(BaseCallbackHandler):
    """Callback handler that tracks LLM calls, tool calls, and token usage.

    Optionally enforces a per-run token budget: once ``tokens_in +
    tokens_out`` exceeds ``token_budget``, the next completed LLM call raises
    ``TokenBudgetExceededError`` instead of letting the run keep spending.
    ``is_quota_error`` classifies that exception the same way it does a
    provider quota error, so a checkpointed run parks cleanly (see
    ``TradingAgentsGraph.park_or_raise``) rather than either being killed
    outright or silently blowing past the configured ceiling.

    ``raise_error = True`` is required for this to work at all: LangChain's
    callback manager swallows exceptions raised from callback methods by
    default (logs them, keeps going) unless the handler opts in.
    """

    raise_error = True

    def __init__(self, token_budget: int | None = None) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self.llm_calls = 0
        self.tool_calls = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self.token_budget = token_budget

    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        **kwargs: Any,
    ) -> None:
        """Increment LLM call counter when an LLM starts."""
        with self._lock:
            self.llm_calls += 1

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[Any]],
        **kwargs: Any,
    ) -> None:
        """Increment LLM call counter when a chat model starts."""
        with self._lock:
            self.llm_calls += 1

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        """Extract token usage from LLM response."""
        try:
            generation = response.generations[0][0]
        except (IndexError, TypeError):
            return

        usage_metadata = None
        if hasattr(generation, "message"):
            message = generation.message
            if isinstance(message, AIMessage) and hasattr(message, "usage_metadata"):
                usage_metadata = message.usage_metadata

        if usage_metadata:
            with self._lock:
                self.tokens_in += usage_metadata.get("input_tokens", 0)
                self.tokens_out += usage_metadata.get("output_tokens", 0)
                total = self.tokens_in + self.tokens_out
                if self.token_budget and total > self.token_budget:
                    raise TokenBudgetExceededError(total, self.token_budget)

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        **kwargs: Any,
    ) -> None:
        """Increment tool call counter when a tool starts."""
        with self._lock:
            self.tool_calls += 1

    def get_stats(self) -> dict[str, Any]:
        """Return current statistics."""
        with self._lock:
            return {
                "llm_calls": self.llm_calls,
                "tool_calls": self.tool_calls,
                "tokens_in": self.tokens_in,
                "tokens_out": self.tokens_out,
            }
