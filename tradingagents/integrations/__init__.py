"""Optional third-party platform integrations, kept as thin REST clients.

Nothing in this package is vendored code -- see ai_trader_client.py's
docstring for why (HKUDS/AI-Trader has no LICENSE file and its own
service/README.md calls itself "proprietary").
"""

from .ai_trader_client import AITraderClient

__all__ = ["AITraderClient"]
