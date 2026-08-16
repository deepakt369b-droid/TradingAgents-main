"""Tests for the scheduled worker's testable logic (Phase 4d).

app.worker.main() itself (the APScheduler wiring) is intentionally not
covered here -- same convention as cli/main.py's run_analysis(): the
scheduler/CLI glue stays thin and untested, the underlying pure functions
are tested directly.
"""

from datetime import date
from unittest.mock import MagicMock

import pytest

import app.worker as worker


@pytest.mark.unit
class TestGetWatchlist:
    def test_empty_by_default(self, monkeypatch):
        monkeypatch.delenv("TRADINGAGENTS_WATCHLIST", raising=False)
        assert worker.get_watchlist() == []

    def test_parses_comma_separated(self, monkeypatch):
        monkeypatch.setenv("TRADINGAGENTS_WATCHLIST", "aapl, msft ,BTC-USD")
        assert worker.get_watchlist() == ["AAPL", "MSFT", "BTC-USD"]

    def test_ignores_blank_entries(self, monkeypatch):
        monkeypatch.setenv("TRADINGAGENTS_WATCHLIST", "AAPL,,MSFT,")
        assert worker.get_watchlist() == ["AAPL", "MSFT"]


@pytest.mark.unit
class TestBuildWorkerConfig:
    def test_forces_checkpoint_enabled(self, monkeypatch):
        monkeypatch.setattr("app.config_store.apply_to_environment", lambda: None)
        config = worker.build_worker_config()
        assert config["checkpoint_enabled"] is True

    def test_forces_checkpoint_even_if_default_config_has_it_off(self, monkeypatch):
        monkeypatch.setattr("app.config_store.apply_to_environment", lambda: None)
        import tradingagents.default_config as dc
        assert dc.DEFAULT_CONFIG["checkpoint_enabled"] is False  # sanity: default is off
        config = worker.build_worker_config()
        assert config["checkpoint_enabled"] is True  # worker forces it on regardless


@pytest.mark.unit
class TestIsTradingDay:
    def test_weekday_true_without_exchange_calendars(self, monkeypatch):
        # exchange_calendars isn't installed in this environment -- exercise
        # the fallback path directly.
        monkeypatch.setattr(worker, "is_trading_day", worker.is_trading_day)  # no-op, just documents intent
        monday = date(2026, 4, 20)
        assert worker.is_trading_day(monday) is True

    def test_weekend_false_without_exchange_calendars(self):
        saturday = date(2026, 4, 18)
        sunday = date(2026, 4, 19)
        assert worker.is_trading_day(saturday) is False
        assert worker.is_trading_day(sunday) is False


@pytest.mark.unit
class TestRunTick:
    def test_empty_watchlist_returns_empty_and_does_not_construct_executor(self, tmp_path, monkeypatch):
        create_executor_mock = MagicMock()
        monkeypatch.setattr("tradingagents.execution.create_executor", create_executor_mock)
        config = {"data_cache_dir": str(tmp_path), "execution_platform": "paper"}
        outcomes = worker.run_tick(config, [], trade_date="2026-04-20")
        assert outcomes == {}
        create_executor_mock.assert_not_called()

    def test_successful_ticker_bridges_signal_and_records_ok(self, tmp_path, monkeypatch):
        config = {"data_cache_dir": str(tmp_path), "execution_platform": "paper"}

        fake_graph = MagicMock()
        fake_graph.propagate.return_value = ({"final_trade_decision": "..."}, "Buy")
        fake_graph._run_signature.return_value = "sig"
        monkeypatch.setattr(
            "tradingagents.graph.trading_graph.TradingAgentsGraph",
            MagicMock(return_value=fake_graph),
        )
        monkeypatch.setattr(
            "tradingagents.dataflows.market_data_validator.get_reference_price",
            lambda ticker, date: 150.0,
        )

        outcomes = worker.run_tick(config, ["AAPL"], trade_date="2026-04-20")
        assert outcomes == {"AAPL": "ok"}
        fake_graph.propagate.assert_called_once()

    def test_run_parked_error_isolated_as_parked_outcome(self, tmp_path, monkeypatch):
        from tradingagents.llm_clients.llm_errors import RunParkedError

        config = {"data_cache_dir": str(tmp_path), "execution_platform": "paper"}
        fake_graph = MagicMock()
        fake_graph.propagate.side_effect = RunParkedError(
            "AAPL", "2026-04-20", "tid", "quick", "ollama", RuntimeError("429")
        )
        monkeypatch.setattr(
            "tradingagents.graph.trading_graph.TradingAgentsGraph",
            MagicMock(return_value=fake_graph),
        )

        outcomes = worker.run_tick(config, ["AAPL"], trade_date="2026-04-20")
        assert outcomes == {"AAPL": "parked"}

    def test_one_ticker_failure_does_not_stop_the_rest(self, tmp_path, monkeypatch):
        config = {"data_cache_dir": str(tmp_path), "execution_platform": "paper"}

        good_graph = MagicMock()
        good_graph.propagate.return_value = ({"final_trade_decision": "..."}, "Hold")
        good_graph._run_signature.return_value = "sig"

        def graph_factory(*args, **kwargs):
            return good_graph

        call_count = {"n": 0}

        def flaky_propagate(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("simulated crash for AAPL")
            return ({"final_trade_decision": "..."}, "Hold")

        good_graph.propagate.side_effect = flaky_propagate
        monkeypatch.setattr(
            "tradingagents.graph.trading_graph.TradingAgentsGraph",
            MagicMock(side_effect=graph_factory),
        )
        monkeypatch.setattr(
            "tradingagents.dataflows.market_data_validator.get_reference_price",
            lambda ticker, date: 150.0,
        )

        outcomes = worker.run_tick(config, ["AAPL", "MSFT"], trade_date="2026-04-20")
        assert outcomes["AAPL"] == "error:RuntimeError"
        assert outcomes["MSFT"] == "ok"

    def test_no_reference_price_skips_order_but_records_outcome(self, tmp_path, monkeypatch):
        config = {"data_cache_dir": str(tmp_path), "execution_platform": "paper"}
        fake_graph = MagicMock()
        fake_graph.propagate.return_value = ({"final_trade_decision": "..."}, "Buy")
        monkeypatch.setattr(
            "tradingagents.graph.trading_graph.TradingAgentsGraph",
            MagicMock(return_value=fake_graph),
        )
        monkeypatch.setattr(
            "tradingagents.dataflows.market_data_validator.get_reference_price",
            lambda ticker, date: None,
        )

        outcomes = worker.run_tick(config, ["AAPL"], trade_date="2026-04-20")
        assert outcomes == {"AAPL": "no_price"}
