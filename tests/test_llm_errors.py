"""Tests for quota/rate-limit failure classification (llm_clients.llm_errors)."""

import httpx
import pytest

from tradingagents.llm_clients.llm_errors import (
    RunParkedError,
    describe_error,
    is_quota_error,
)


def _http_error(cls, status_code, url="https://api.example.com/v1/chat/completions"):
    req = httpx.Request("POST", url)
    resp = httpx.Response(status_code, request=req)
    return cls("boom", response=resp, body=None)


@pytest.mark.unit
class TestIsQuotaError:
    def test_openai_rate_limit_error(self):
        import openai
        assert is_quota_error(_http_error(openai.RateLimitError, 429)) is True

    def test_anthropic_rate_limit_error(self):
        import anthropic
        assert is_quota_error(_http_error(anthropic.RateLimitError, 429)) is True

    def test_google_client_error_429(self):
        import google.genai.errors as gerrors
        exc = gerrors.ClientError(429, {"error": {"message": "quota exceeded"}})
        assert is_quota_error(exc) is True

    def test_google_client_error_402(self):
        import google.genai.errors as gerrors
        exc = gerrors.ClientError(402, {"error": {"message": "payment required"}})
        assert is_quota_error(exc) is True

    def test_message_substring_fallback(self):
        assert is_quota_error(RuntimeError("insufficient_quota: please add funds")) is True
        assert is_quota_error(RuntimeError("Rate limit reached for requests")) is True
        assert is_quota_error(RuntimeError("Too Many Requests")) is True

    def test_unrelated_error_is_not_quota(self):
        assert is_quota_error(ValueError("malformed JSON in response")) is False
        assert is_quota_error(RuntimeError("connection reset by peer")) is False

    def test_server_error_status_is_not_quota(self):
        import openai
        # 500s are real outages, not a quota/billing condition -- must not
        # be misclassified as recoverable-by-swapping-providers-and-waiting.
        assert is_quota_error(_http_error(openai.APIStatusError, 500)) is False

    def test_walks_exception_cause_chain(self):
        import openai
        inner = _http_error(openai.RateLimitError, 429)
        wrapper = RuntimeError("LLM call failed")
        wrapper.__cause__ = inner
        assert is_quota_error(wrapper) is True

    def test_no_infinite_loop_on_self_referential_chain(self):
        exc = RuntimeError("boom")
        exc.__cause__ = exc  # pathological but must not hang
        assert is_quota_error(exc) is False


@pytest.mark.unit
class TestDescribeError:
    def test_describe_error_shape(self):
        import openai
        exc = _http_error(openai.RateLimitError, 429)
        info = describe_error(exc)
        assert info["type"] == "RateLimitError"
        assert info["status_code"] == 429
        assert info["is_quota_error"] is True
        assert "boom" in info["message"]

    def test_describe_error_truncates_long_messages(self):
        info = describe_error(RuntimeError("x" * 2000))
        assert len(info["message"]) <= 500


@pytest.mark.unit
class TestRunParkedError:
    def test_carries_context_and_cause(self):
        cause = RuntimeError("rate limited")
        err = RunParkedError("AAPL", "2026-04-20", "abc123", "quick", "ollama", cause)
        assert err.ticker == "AAPL"
        assert err.trade_date == "2026-04-20"
        assert err.thread_id == "abc123"
        assert err.failed_role == "quick"
        assert err.failed_provider == "ollama"
        assert err.__cause__ is cause
        assert "quick-thinking" in str(err)
        assert "ollama" in str(err)
