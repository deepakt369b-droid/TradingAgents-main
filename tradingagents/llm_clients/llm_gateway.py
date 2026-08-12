"""Resilient LLM Gateway Router for TradingAgents.

Provides:
- Multi-provider fallback chain (e.g. OpenAI -> Anthropic -> Google)
- Circuit breaker protection against consecutive API failures
- Integration with KeyPoolManager and CloudflareAIGateway
- Transparent LangChain LLM wrapper
"""

from __future__ import annotations

import time
import logging
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage

from .key_pool import global_key_pool
from .cloudflare_gateway import CloudflareAIGateway

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """Circuit breaker for an individual provider."""

    def __init__(self, failure_threshold: int = 3, cooldown: float = 300.0):
        self.failure_threshold = failure_threshold
        self.cooldown = cooldown
        self.failure_count = 0
        self.state = "CLOSED"  # CLOSED, OPEN, HALF-OPEN
        self.opened_at = 0.0

    def is_available(self) -> bool:
        """Check if provider circuit is available."""
        if self.state == "CLOSED":
            return True
        if self.state == "OPEN":
            if time.time() - self.opened_at >= self.cooldown:
                self.state = "HALF-OPEN"
                logger.info("Circuit breaker entering HALF-OPEN state to test provider recovery.")
                return True
            return False
        # HALF-OPEN
        return True

    def record_success(self):
        """Record success and reset circuit."""
        self.failure_count = 0
        self.state = "CLOSED"

    def record_failure(self):
        """Record failure and trip circuit if threshold exceeded."""
        self.failure_count += 1
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            self.opened_at = time.time()
            logger.warning(
                "Circuit breaker TRIPPED! Opened for %d seconds due to %d consecutive failures.",
                int(self.cooldown),
                self.failure_count,
            )


class ResilientLLMGateway:
    """Wrapper that tries primary LLM and falls back to secondary clients if failures occur."""

    def __init__(
        self,
        primary_client: Any,
        fallback_clients: list[Any] | None = None,
        circuit_threshold: int = 3,
        cooldown: float = 300.0,
    ):
        self.primary_client = primary_client
        self.fallback_clients = fallback_clients or []
        self.circuits: dict[str, CircuitBreaker] = {}
        self.circuit_threshold = circuit_threshold
        self.cooldown = cooldown

    def _get_circuit(self, provider: str) -> CircuitBreaker:
        if provider not in self.circuits:
            self.circuits[provider] = CircuitBreaker(
                failure_threshold=self.circuit_threshold,
                cooldown=self.cooldown,
            )
        return self.circuits[provider]

    def invoke(self, input_: Any, config: Any = None, **kwargs: Any) -> Any:
        """Invoke primary LLM client, failing over to backup clients if primary fails."""
        clients = [self.primary_client] + self.fallback_clients
        last_exception = None

        for client in clients:
            provider = getattr(client, "provider", "default")
            circuit = self._get_circuit(provider)

            if not circuit.is_available():
                logger.warning("Skipping provider '%s' (Circuit breaker is OPEN)", provider)
                continue

            try:
                # Rotate key if key pool configured
                active_key = global_key_pool.get_active_key(provider)
                if active_key and hasattr(client, "api_key"):
                    setattr(client, "api_key", active_key)

                # Execute invoke
                target_llm = client.get_llm() if hasattr(client, "get_llm") else client
                response = target_llm.invoke(input_, config=config, **kwargs)

                circuit.record_success()
                if active_key:
                    global_key_pool.report_success(provider, active_key)

                return response

            except Exception as exc:
                last_exception = exc
                logger.error(
                    "LLM call to provider '%s' failed: %s. Attempting failover if available.",
                    provider,
                    exc,
                )
                circuit.record_failure()

                active_key = global_key_pool.get_active_key(provider)
                if active_key:
                    global_key_pool.report_failure(provider, active_key)

        # If all fail, raise the last exception
        if last_exception:
            raise last_exception
        raise RuntimeError("All LLM gateway providers are currently unavailable or circuit-broken.")
