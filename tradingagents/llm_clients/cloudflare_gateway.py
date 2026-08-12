"""Cloudflare AI Gateway integration for TradingAgents.

Provides URL transformation and BYOK (Bring Your Own Key) header resolution
for routing LLM requests through Cloudflare AI Gateway.
"""

from __future__ import annotations

import os
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Cloudflare provider mapping
_CLOUDFLARE_PROVIDER_MAP = {
    "openai": "openai",
    "anthropic": "anthropic",
    "google": "google-ai-studio",
    "groq": "groq",
    "mistral": "mistral",
    "aws-bedrock": "aws-bedrock",
    "azure-openai": "azure-openai",
}


class CloudflareAIGateway:
    """Helper for constructing Cloudflare AI Gateway URLs and headers."""

    def __init__(
        self,
        account_id: str | None = None,
        gateway_id: str | None = None,
        byok_alias: str | None = None,
        base_gateway_url: str | None = None,
    ):
        self.account_id = account_id or os.environ.get("CLOUDFLARE_ACCOUNT_ID")
        self.gateway_id = gateway_id or os.environ.get("CLOUDFLARE_GATEWAY_ID")
        self.byok_alias = byok_alias or os.environ.get("CLOUDFLARE_BYOK_ALIAS")
        self.base_gateway_url = base_gateway_url or os.environ.get("CLOUDFLARE_AI_GATEWAY_URL")

    @property
    def is_configured(self) -> bool:
        """Return True if enough config exists to route through Cloudflare AI Gateway."""
        if self.base_gateway_url and self.base_gateway_url.strip():
            return True
        return bool(self.account_id and self.gateway_id)

    def get_provider_url(self, provider: str) -> str | None:
        """Resolve the Cloudflare AI Gateway URL for a given provider.

        Example:
            https://gateway.ai.cloudflare.com/v1/{account_id}/{gateway_id}/openai
        """
        if not self.is_configured:
            return None

        cf_provider = _CLOUDFLARE_PROVIDER_MAP.get(provider.lower(), provider.lower())

        if self.base_gateway_url:
            base = self.base_gateway_url.rstrip("/")
            if base.endswith(cf_provider):
                return base
            return f"{base}/{cf_provider}"

        return f"https://gateway.ai.cloudflare.com/v1/{self.account_id}/{self.gateway_id}/{cf_provider}"

    def get_extra_headers(self) -> dict[str, str]:
        """Return headers for Cloudflare AI Gateway, e.g. BYOK alias header."""
        headers = {}
        if self.byok_alias:
            headers["cf-aig-byok-alias"] = self.byok_alias
        cf_token = os.environ.get("CLOUDFLARE_AI_GATEWAY_TOKEN")
        if cf_token:
            headers["cf-aig-authorization"] = f"Bearer {cf_token}"
        return headers

    def apply_to_kwargs(self, provider: str, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Apply Cloudflare base URL and headers into LLM client kwargs in-place."""
        if not self.is_configured:
            return kwargs

        cf_url = self.get_provider_url(provider)
        if cf_url:
            kwargs["base_url"] = cf_url
            logger.info("Routed provider '%s' through Cloudflare AI Gateway: %s", provider, cf_url)

        headers = self.get_extra_headers()
        if headers:
            existing_headers = kwargs.get("default_headers") or kwargs.get("extra_headers") or {}
            existing_headers.update(headers)
            kwargs["default_headers"] = existing_headers

        return kwargs
