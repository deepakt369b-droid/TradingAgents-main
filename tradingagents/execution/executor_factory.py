"""Factory for creating execution platform drivers."""

from __future__ import annotations

import logging
from .base_executor import BaseExecutor
from .live_gate import is_live_trading_enabled
from .paper_executor import PaperExecutor

logger = logging.getLogger(__name__)


def create_executor(platform: str, config: dict | None = None) -> BaseExecutor:
    """Create an execution driver based on platform string.

    Supported platforms: 'paper', 'alpaca', 'ibkr', 'ccxt', 'binance', 'coinbase'.
    Every platform other than 'paper' resolves to that platform's
    paper/sandbox mode unless ``TRADINGAGENTS_LIVE_TRADING_ENABLED`` is set
    (see live_gate.py) -- this is the single choke point that makes the
    paper-first promotion gate hold regardless of what platform string a
    caller passes.
    """
    platform_lower = platform.lower()
    live = is_live_trading_enabled()
    logger.info(
        "create_executor(platform=%s): live trading %s.",
        platform_lower, "ENABLED" if live else "disabled (paper/sandbox)",
    )

    if platform_lower == "paper":
        return PaperExecutor(config=config)

    if platform_lower == "alpaca":
        from .alpaca_executor import AlpacaExecutor
        return AlpacaExecutor(paper=not live, config=config)

    if platform_lower == "ibkr":
        from .ibkr_executor import IBKRExecutor
        return IBKRExecutor(config=config)

    if platform_lower in ("ccxt", "binance", "coinbase", "kucoin", "bybit"):
        from .ccxt_executor import CCXTExecutor
        exchange_id = platform_lower if platform_lower != "ccxt" else "binance"
        return CCXTExecutor(exchange_id=exchange_id, config=config)

    # Falling back to PaperExecutor here is the safe direction, but a
    # misconfigured platform string silently landing in a completely
    # different execution mode is a real misconfiguration -- log it loud
    # enough to show up in default-level Coolify logs, not just debug output.
    logger.error(
        "Unknown execution platform '%s'. Falling back to PaperExecutor -- "
        "no orders will reach a real broker/exchange until this is fixed.",
        platform,
    )
    return PaperExecutor(config=config)
