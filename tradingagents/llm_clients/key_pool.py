"""API Key Pool Manager for multi-key rotation and failover.

Supports comma-separated API keys in environment variables (e.g. OPENAI_API_KEY="key1,key2,key3").
Provides round-robin or least-used rotation, automatic key quarantine on 401/429/403,
and recovery after a configurable cooldown period.
"""

from __future__ import annotations

import os
import time
import logging
from typing import NamedTuple

logger = logging.getLogger(__name__)


class KeyStatus(NamedTuple):
    key: str
    failures: int
    quarantined_until: float


class KeyPoolManager:
    """Manages a pool of API keys per provider for load balancing and resilience."""

    def __init__(self, quarantine_cooldown: float = 300.0):
        # provider -> list of key strings
        self._keys: dict[str, list[str]] = {}
        # (provider, key) -> index of current pointer
        self._pointers: dict[str, int] = {}
        # (provider, key) -> KeyStatus
        self._status: dict[tuple[str, str], KeyStatus] = {}
        self.quarantine_cooldown = quarantine_cooldown

    def register_provider_keys(self, provider: str, raw_key_str: str | None = None) -> None:
        """Parse and register keys for a provider from string or env var."""
        provider = provider.lower()
        if raw_key_str is None:
            from .api_key_env import get_api_key_env
            env_var = get_api_key_env(provider)
            raw_key_str = os.environ.get(env_var) if env_var else None

        if not raw_key_str:
            self._keys[provider] = []
            return

        # Split on commas or whitespace
        keys = [k.strip() for k in raw_key_str.split(",") if k.strip()]
        self._keys[provider] = keys
        self._pointers[provider] = 0
        for k in keys:
            self._status[(provider, k)] = KeyStatus(key=k, failures=0, quarantined_until=0.0)

    def get_active_key(self, provider: str) -> str | None:
        """Get the next active, non-quarantined API key for provider."""
        provider = provider.lower()
        if provider not in self._keys or not self._keys[provider]:
            # Auto-register if not yet registered
            self.register_provider_keys(provider)

        keys = self._keys.get(provider, [])
        if not keys:
            return None

        if len(keys) == 1:
            # Single key setup
            key = keys[0]
            st = self._status.get((provider, key))
            if st and st.quarantined_until > time.time():
                logger.warning("Single API key for '%s' is quarantined until %f", provider, st.quarantined_until)
            return key

        now = time.time()
        start_idx = self._pointers.get(provider, 0)
        num_keys = len(keys)

        for i in range(num_keys):
            idx = (start_idx + i) % num_keys
            key = keys[idx]
            st = self._status.get((provider, key))

            # If not quarantined, pick this key
            if not st or st.quarantined_until <= now:
                self._pointers[provider] = (idx + 1) % num_keys
                return key

        # If all keys quarantined, pick the key with the earliest expiration
        logger.warning("All %d API keys for provider '%s' are quarantined! Returning earliest expiring key.", num_keys, provider)
        earliest_key = min(keys, key=lambda k: self._status.get((provider, k), KeyStatus(k, 0, 0)).quarantined_until)
        return earliest_key

    def report_failure(self, provider: str, key: str, status_code: int | None = None) -> None:
        """Report a failure (e.g. 401, 403, 429) for a key to quarantine it."""
        provider = provider.lower()
        st = self._status.get((provider, key))
        failures = (st.failures + 1) if st else 1
        quarantined_until = time.time() + self.quarantine_cooldown

        self._status[(provider, key)] = KeyStatus(
            key=key,
            failures=failures,
            quarantined_until=quarantined_until,
        )
        logger.warning(
            "API key for '%s' (end %s...) reported failure (HTTP %s). Quarantining for %ds. Total failures: %d",
            provider,
            key[-4:] if len(key) >= 4 else key,
            status_code or "Unknown",
            int(self.quarantine_cooldown),
            failures,
        )

    def report_success(self, provider: str, key: str) -> None:
        """Reset failure counter on successful request."""
        provider = provider.lower()
        if (provider, key) in self._status:
            self._status[(provider, key)] = KeyStatus(key=key, failures=0, quarantined_until=0.0)


# Global default key pool instance
global_key_pool = KeyPoolManager()
