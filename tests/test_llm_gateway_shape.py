"""Regression tests: a ResilientLLMGateway must behave like a BaseChatModel.

``TradingAgentsGraph`` and the agent factories call ``.get_llm()`` at
construction, then ``.bind_tools()`` (analysts) or
``.with_structured_output()`` (trader/PM/research manager) on the result.
Before this fix, a gateway-wrapped client (``fallback_providers`` set)
returned an object with none of those methods -- the first analyst node
would raise ``AttributeError`` the moment it tried to bind tools.
"""

import pytest

from tradingagents.llm_clients.factory import create_llm_client
from tradingagents.llm_clients.llm_gateway import ResilientLLMGateway


@pytest.mark.unit
class TestGatewayShape:
    def _gateway(self):
        client = create_llm_client(
            provider="openai",
            model="gpt-4.1",
            api_key="placeholder",
            fallback_providers=["deepseek"],
        )
        assert isinstance(client, ResilientLLMGateway)
        return client

    def test_get_llm_returns_self(self):
        gateway = self._gateway()
        assert gateway.get_llm() is gateway

    def test_bind_tools_returns_a_gateway_with_bound_members(self):
        from langchain_core.tools import tool

        @tool
        def noop() -> str:
            """A no-op tool."""
            return "ok"

        gateway = self._gateway()
        bound = gateway.bind_tools([noop])
        assert isinstance(bound, ResilientLLMGateway)
        # The bound primary/fallback are runnables, not BaseLLMClient wrappers.
        assert not hasattr(bound.primary_client, "get_llm")
        assert len(bound.fallback_clients) == 1

    def test_with_structured_output_returns_a_gateway_with_bound_members(self):
        from pydantic import BaseModel

        class Schema(BaseModel):
            answer: str

        gateway = self._gateway()
        structured = gateway.with_structured_output(Schema)
        assert isinstance(structured, ResilientLLMGateway)
        assert not hasattr(structured.primary_client, "get_llm")
