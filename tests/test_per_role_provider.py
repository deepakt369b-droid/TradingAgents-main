"""Tests for per-role (deep/quick) LLM provider routing.

Deep-thinking and quick-thinking calls can now be routed to different
providers (e.g. Kimi for deep, Ollama for quick) via
``deep_think_provider``/``quick_think_provider`` in config. When unset
(None), both roles fall back to the shared ``llm_provider`` -- the
pre-existing single-provider behavior must be unaffected.
"""

import importlib

import pytest

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph


@pytest.mark.unit
class TestPerRoleProviderDefaults:
    def test_new_keys_default_to_none(self):
        assert DEFAULT_CONFIG["deep_think_provider"] is None
        assert DEFAULT_CONFIG["deep_think_base_url"] is None
        assert DEFAULT_CONFIG["quick_think_provider"] is None
        assert DEFAULT_CONFIG["quick_think_base_url"] is None


@pytest.mark.unit
class TestPerRoleProviderKwargs:
    """_get_provider_kwargs(provider) keys the reasoning knob off the passed role."""

    def _graph(self, config):
        graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
        graph.config = config
        return graph

    def test_defaults_to_llm_provider_when_role_omitted(self):
        graph = self._graph({"llm_provider": "openai", "openai_reasoning_effort": "high"})
        kwargs = TradingAgentsGraph._get_provider_kwargs(graph)
        assert kwargs["reasoning_effort"] == "high"

    def test_explicit_role_overrides_shared_provider(self):
        # Shared provider is openai (would set reasoning_effort), but the
        # role passed in is google -- must apply the google knob instead,
        # and must NOT leak the openai knob.
        graph = self._graph({
            "llm_provider": "openai",
            "openai_reasoning_effort": "high",
            "google_thinking_level": "high",
        })
        kwargs = TradingAgentsGraph._get_provider_kwargs(graph, "google")
        assert kwargs.get("thinking_level") == "high"
        assert "reasoning_effort" not in kwargs

    def test_kimi_role_gets_no_reasoning_knob_leak(self):
        # A provider with no matching branch in _get_provider_kwargs (e.g.
        # kimi, which is OpenAI-compatible but not "openai") must not pick
        # up another role's reasoning knob.
        graph = self._graph({
            "llm_provider": "google",
            "google_thinking_level": "high",
            "anthropic_effort": "high",
        })
        kwargs = TradingAgentsGraph._get_provider_kwargs(graph, "kimi")
        assert "thinking_level" not in kwargs
        assert "effort" not in kwargs


@pytest.mark.unit
class TestPerRoleProviderEnvOverrides:
    def test_env_vars_set_per_role_provider(self, monkeypatch):
        import tradingagents.default_config as dc

        monkeypatch.setenv("TRADINGAGENTS_DEEP_PROVIDER", "kimi")
        monkeypatch.setenv("TRADINGAGENTS_QUICK_PROVIDER", "ollama")
        monkeypatch.setenv("TRADINGAGENTS_DEEP_BASE_URL", "https://api.moonshot.ai/v1")
        monkeypatch.setenv("TRADINGAGENTS_QUICK_BASE_URL", "http://host.docker.internal:11434/v1")
        try:
            importlib.reload(dc)
            assert dc.DEFAULT_CONFIG["deep_think_provider"] == "kimi"
            assert dc.DEFAULT_CONFIG["quick_think_provider"] == "ollama"
            assert dc.DEFAULT_CONFIG["deep_think_base_url"] == "https://api.moonshot.ai/v1"
            assert dc.DEFAULT_CONFIG["quick_think_base_url"] == "http://host.docker.internal:11434/v1"
        finally:
            monkeypatch.delenv("TRADINGAGENTS_DEEP_PROVIDER", raising=False)
            monkeypatch.delenv("TRADINGAGENTS_QUICK_PROVIDER", raising=False)
            monkeypatch.delenv("TRADINGAGENTS_DEEP_BASE_URL", raising=False)
            monkeypatch.delenv("TRADINGAGENTS_QUICK_BASE_URL", raising=False)
            importlib.reload(dc)


@pytest.mark.unit
class TestKimiCapabilities:
    def test_kimi_k2_rejects_tool_choice(self):
        from tradingagents.llm_clients.capabilities import get_capabilities

        caps = get_capabilities("kimi-k2.6")
        assert caps.supports_tool_choice is False
        assert caps.preferred_structured_method == "function_calling"

    def test_kimi_k3_keeps_default_capabilities(self):
        from tradingagents.llm_clients.capabilities import get_capabilities

        caps = get_capabilities("kimi-k3")
        assert caps.supports_tool_choice is True


@pytest.mark.unit
class TestKimiTemperatureClamp:
    def test_temperature_above_one_is_clamped(self):
        from tradingagents.llm_clients.factory import create_llm_client

        llm = create_llm_client(
            provider="kimi", model="kimi-k2.6", temperature=1.8, api_key="placeholder"
        ).get_llm()
        assert llm.temperature == 1.0

    def test_temperature_within_range_is_untouched(self):
        from tradingagents.llm_clients.factory import create_llm_client

        llm = create_llm_client(
            provider="kimi", model="kimi-k2.6", temperature=0.6, api_key="placeholder"
        ).get_llm()
        assert llm.temperature == 0.6

    def test_other_providers_unaffected_by_kimi_clamp(self):
        from tradingagents.llm_clients.factory import create_llm_client

        llm = create_llm_client(
            provider="openai", model="gpt-4.1", temperature=1.8, api_key="placeholder"
        ).get_llm()
        assert llm.temperature == 1.8
