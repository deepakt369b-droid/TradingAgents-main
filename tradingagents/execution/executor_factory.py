"""Factory for creating execution platform drivers."""

from __future__ import annotations

import logging
from .base_executor import BaseExecutor
from .paper_executor import PaperExecutor

logger = logging.getLogger(__name__)


def create_executor(platform: str, config: dict | None = None) -> BaseExecutor:
    """Create an execution driver based on platform string.

    Supported platforms: 'paper', 'alpaca', 'ibkr', 'ccxt', 'binance', 'coinbase'.
    """
    platform_lower = platform.lower()

    if platform_lower == "paper":
        return PaperExecutor(config=config)

    if platform_lower == "alpaca":
        from .alpaca_executor import AlpacaExecutor
        return AlpacaExecutor(config=config)

    if platform_lower == "ibkr":
        from .ibkr_executor import IBKRExecutor
        return IBKRExecutor(config=config)

    if platform_lower in ("ccxt", "binance", "coinbase", "kucoin", "bybit"):
        from .ccxt_executor import CCXTExecutor
        exchange_id = platform_lower if platform_lower != "ccxt" else "binance"
        return CCXTExecutor(exchange_id=exchange_id, config=config)

    logger.warning("Unknown execution platform '%s'. Falling back to PaperExecutor.", platform)
    return PaperExecutor(config=config)
