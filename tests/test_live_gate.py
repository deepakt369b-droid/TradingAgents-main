"""Tests for the paper-first gate (Phase 4a)."""

import pytest

from tradingagents.execution.live_gate import (
    is_kill_switch_active,
    is_live_trading_enabled,
    kill_switch_path,
)


@pytest.mark.unit
class TestIsLiveTradingEnabled:
    def test_unset_defaults_to_false(self, monkeypatch):
        monkeypatch.delenv("TRADINGAGENTS_LIVE_TRADING_ENABLED", raising=False)
        assert is_live_trading_enabled() is False

    def test_empty_string_is_false(self, monkeypatch):
        monkeypatch.setenv("TRADINGAGENTS_LIVE_TRADING_ENABLED", "")
        assert is_live_trading_enabled() is False

    @pytest.mark.parametrize("value", ["true", "True", "TRUE", "1", "yes", "on"])
    def test_true_values(self, monkeypatch, value):
        monkeypatch.setenv("TRADINGAGENTS_LIVE_TRADING_ENABLED", value)
        assert is_live_trading_enabled() is True

    @pytest.mark.parametrize("value", ["false", "0", "no", "off", "garbage"])
    def test_false_and_unrecognized_values(self, monkeypatch, value):
        monkeypatch.setenv("TRADINGAGENTS_LIVE_TRADING_ENABLED", value)
        assert is_live_trading_enabled() is False


@pytest.mark.unit
class TestKillSwitch:
    def test_inactive_by_default(self, tmp_path):
        assert is_kill_switch_active(tmp_path) is False

    def test_active_when_file_present(self, tmp_path):
        kill_switch_path(tmp_path).touch()
        assert is_kill_switch_active(tmp_path) is True

    def test_inactive_after_file_removed(self, tmp_path):
        path = kill_switch_path(tmp_path)
        path.touch()
        assert is_kill_switch_active(tmp_path) is True
        path.unlink()
        assert is_kill_switch_active(tmp_path) is False
