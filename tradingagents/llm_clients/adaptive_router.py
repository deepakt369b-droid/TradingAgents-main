"""Performance-Based Adaptive Model Escalation Router.

Routes standard tasks to fast cost-effective models (e.g. gpt-5.4-mini, gemini-3.5-flash)
and escalates high-impact decisions (portfolio manager decisions, volatile signals, high historical return targets)
to top-tier frontier deep-thinking models (e.g. gpt-5.5, claude-opus-4-8).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class AdaptiveModelRouter:
    """Dynamically chooses model tier based on task complexity and earnings impact."""

    def __init__(self, high_performance_mode: bool = True):
        self.high_performance_mode = high_performance_mode

    def select_model_tier(
        self,
        agent_role: str,
        volatility_index: float | None = None,
        account_profit_streak: int = 0,
    ) -> str:
        """Return 'deep' for high-stakes tasks or 'quick' for routine steps.

        Args:
            agent_role: e.g. "portfolio_manager", "trader", "market_analyst", "sentiment_analyst"
            volatility_index: market volatility metric if available
            account_profit_streak: consecutive profitable trade runs
        """
        # Always use deep frontier models for final allocation decisions
        if agent_role in ("portfolio_manager", "trader", "research_manager"):
            logger.info("AdaptiveRouter: Role '%s' assigned to 'deep' frontier model.", agent_role)
            return "deep"

        # Escalate analyst roles if market is highly volatile or profit streak is active
        if volatility_index and volatility_index > 25.0:
            logger.info("AdaptiveRouter: High market volatility (%.1f) detected. Escalating '%s' to 'deep'.", volatility_index, agent_role)
            return "deep"

        if account_profit_streak >= 3 and self.high_performance_mode:
            logger.info("AdaptiveRouter: Active profit streak (%d trades). Escalating '%s' to 'deep'.", account_profit_streak, agent_role)
            return "deep"

        # Default routine data collection to quick model
        return "quick"


global_adaptive_router = AdaptiveModelRouter()
