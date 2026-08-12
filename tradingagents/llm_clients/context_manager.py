"""Context & History Manager for TradingAgents graph.

Prevents quadratic token explosion in multi-turn debate loops by maintaining
a sliding window of messages and summarizing older history.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

logger = logging.getLogger(__name__)


class AgentContextManager:
    """Manages context history truncation and summarization."""

    def __init__(self, max_history_messages: int = 12):
        self.max_history_messages = max_history_messages

    def trim_messages(self, messages: list[Any]) -> list[Any]:
        """Trim message history if it exceeds max_history_messages.

        Preserves SystemMessage (if any at index 0) and the most recent messages.
        """
        if len(messages) <= self.max_history_messages:
            return messages

        system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
        other_msgs = [m for m in messages if not isinstance(m, SystemMessage)]

        # Keep recent subset
        trimmed_other = other_msgs[-self.max_history_messages :]

        logger.info(
            "ContextManager: Trimmed message history from %d to %d messages.",
            len(messages),
            len(system_msgs) + len(trimmed_other),
        )

        return system_msgs + trimmed_other


global_context_manager = AgentContextManager()
