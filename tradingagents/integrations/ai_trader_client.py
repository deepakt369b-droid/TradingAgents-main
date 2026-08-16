"""Thin REST client for posting completed decisions to an AI-Trader instance.

Deliberately a REST client, not a vendored dependency. HKUDS/AI-Trader was
evaluated for a fuller integration and rejected: its repository has no
LICENSE file (the README's MIT badge links to a dead path, GitHub reports
`license: null`, and `service/README.md` -- the directory that would be
copied -- calls itself "the proprietary server implementation"), so
vendoring any of its code would be a real legal exposure. It also has no
Python agent/plugin architecture to integrate with: a "skill" there is a
Markdown file read by an external agent over HTTP, and an "agent" is a
database row identified by a bearer token. The entire integration surface
is REST, which is exactly what this client uses -- against either the
hosted ai4trade.ai service or a self-run instance, never imported into this
codebase.

This is optional and additive: nothing else in the pipeline depends on it.
Unconfigured (no base_url/agent_token), every method is a no-op.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 10.0

# AI-Trader's MARKET_ALIASES normalizes exchange/venue names to one of these
# three buckets (see routes_shared.py in the upstream repo) -- mirrored here
# so callers pass a familiar asset_type and this client maps it correctly.
_ASSET_TYPE_TO_MARKET = {
    "stock": "us-stock",
    "crypto": "crypto",
}


class AITraderClient:
    """Posts trade signals to an AI-Trader instance's REST API.

    ``base_url`` and ``agent_token`` come from registering an agent via
    ``POST {base_url}/api/claw/agents/selfRegister`` (a one-time manual step
    -- this client does not perform registration). Both unset (the default)
    makes every method a documented no-op, so this integration is safe to
    leave unconfigured.
    """

    def __init__(
        self,
        base_url: str | None = None,
        agent_token: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ):
        self.base_url = (base_url or "").rstrip("/")
        self.agent_token = agent_token
        self.timeout = timeout

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.agent_token)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.agent_token}", "Content-Type": "application/json"}

    def post_signal(
        self,
        ticker: str,
        action: str,
        reference_price: float,
        quantity: float,
        asset_type: str = "stock",
        content: str = "",
    ) -> dict[str, Any] | None:
        """POST a completed trade decision to /api/signals/realtime.

        Returns the parsed JSON response, or None if unconfigured or the
        request failed (logged, never raised -- a social/visibility
        integration failing must never take down the actual trading pipeline
        it's reporting on).
        """
        if not self.is_configured:
            logger.debug("AITraderClient not configured; skipping signal post for %s.", ticker)
            return None

        payload = {
            "symbol": ticker,
            "action": action.lower(),
            "price": reference_price,
            "quantity": quantity,
            "market": _ASSET_TYPE_TO_MARKET.get(asset_type, "us-stock"),
            "content": content,
        }
        try:
            resp = requests.post(
                f"{self.base_url}/api/signals/realtime",
                json=payload, headers=self._headers(), timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            logger.warning("AITraderClient: failed to post signal for %s: %s", ticker, exc)
            return None

    def send_heartbeat(self) -> dict[str, Any] | None:
        """POST /api/claw/agents/heartbeat -- required polling for replies/mentions/followers."""
        if not self.is_configured:
            return None
        try:
            resp = requests.post(
                f"{self.base_url}/api/claw/agents/heartbeat",
                headers=self._headers(), timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            logger.warning("AITraderClient: heartbeat failed: %s", exc)
            return None
