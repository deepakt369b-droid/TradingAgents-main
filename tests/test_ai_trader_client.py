"""Tests for the AI-Trader REST client (Phase 4e -- REST integration only,
never a vendored dependency; see ai_trader_client.py's docstring)."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from tradingagents.integrations.ai_trader_client import AITraderClient


@pytest.mark.unit
class TestIsConfigured:
    def test_unconfigured_by_default(self):
        assert AITraderClient().is_configured is False

    def test_requires_both_base_url_and_token(self):
        assert AITraderClient(base_url="https://api.ai4trade.ai").is_configured is False
        assert AITraderClient(agent_token="tok").is_configured is False
        assert AITraderClient(base_url="https://api.ai4trade.ai", agent_token="tok").is_configured is True


@pytest.mark.unit
class TestPostSignal:
    def test_noop_when_unconfigured(self):
        client = AITraderClient()
        with patch.object(requests, "post") as mock_post:
            result = client.post_signal("AAPL", "buy", 150.0, 10.0)
        assert result is None
        mock_post.assert_not_called()

    def test_posts_expected_payload(self):
        client = AITraderClient(base_url="https://api.ai4trade.ai/", agent_token="tok123")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "ok"}
        with patch.object(requests, "post", return_value=mock_resp) as mock_post:
            result = client.post_signal("AAPL", "buy", 150.0, 10.0, asset_type="stock", content="rating: Buy")

        assert result == {"status": "ok"}
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        # Trailing slash on base_url must not produce a double slash.
        assert call_args.args[0] == "https://api.ai4trade.ai/api/signals/realtime"
        assert call_args.kwargs["json"] == {
            "symbol": "AAPL", "action": "buy", "price": 150.0, "quantity": 10.0,
            "market": "us-stock", "content": "rating: Buy",
        }
        assert call_args.kwargs["headers"]["Authorization"] == "Bearer tok123"

    def test_crypto_asset_type_maps_to_crypto_market(self):
        client = AITraderClient(base_url="https://api.ai4trade.ai", agent_token="tok")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {}
        with patch.object(requests, "post", return_value=mock_resp) as mock_post:
            client.post_signal("BTC-USD", "buy", 60000.0, 0.1, asset_type="crypto")
        assert mock_post.call_args.kwargs["json"]["market"] == "crypto"

    def test_request_failure_returns_none_not_raises(self):
        client = AITraderClient(base_url="https://api.ai4trade.ai", agent_token="tok")
        with patch.object(requests, "post", side_effect=requests.ConnectionError("boom")):
            result = client.post_signal("AAPL", "buy", 150.0, 10.0)
        assert result is None

    def test_http_error_status_returns_none_not_raises(self):
        client = AITraderClient(base_url="https://api.ai4trade.ai", agent_token="tok")
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("500")
        with patch.object(requests, "post", return_value=mock_resp):
            result = client.post_signal("AAPL", "buy", 150.0, 10.0)
        assert result is None


@pytest.mark.unit
class TestHeartbeat:
    def test_noop_when_unconfigured(self):
        client = AITraderClient()
        with patch.object(requests, "post") as mock_post:
            assert client.send_heartbeat() is None
        mock_post.assert_not_called()

    def test_posts_to_heartbeat_endpoint(self):
        client = AITraderClient(base_url="https://api.ai4trade.ai", agent_token="tok")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"replies": []}
        with patch.object(requests, "post", return_value=mock_resp) as mock_post:
            result = client.send_heartbeat()
        assert result == {"replies": []}
        assert mock_post.call_args.args[0] == "https://api.ai4trade.ai/api/claw/agents/heartbeat"
