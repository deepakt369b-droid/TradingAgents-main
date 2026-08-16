"""Tests for the row caps on agent-controlled date-range tool calls (Phase 3
token reduction). Caps must cut by ROW COUNT (most recent kept), never by
truncating the serialized string -- a string-length cut would silently drop
rows from the middle while leaving output that still parses.
"""

import pandas as pd
import pytest

import tradingagents.dataflows.y_finance as yfin
from tradingagents.dataflows.config import set_config


def _fake_ohlcv_ticker(num_rows: int):
    class FakeTicker:
        def __init__(self, symbol):
            pass

        def history(self, start, end):
            idx = pd.date_range("2020-01-01", periods=num_rows, freq="D")
            return pd.DataFrame(
                {
                    "Open": range(num_rows), "High": range(num_rows),
                    "Low": range(num_rows), "Close": range(num_rows),
                    "Volume": range(num_rows),
                },
                index=idx,
            )
    return FakeTicker


@pytest.mark.unit
class TestOhlcvRowCap:
    def test_within_cap_untouched(self, monkeypatch):
        set_config({"max_ohlcv_rows": 250})
        monkeypatch.setattr(yfin.yf, "Ticker", _fake_ohlcv_ticker(50))
        out = yfin.get_YFin_data_online("AAPL", "2020-01-01", "2020-02-19")
        assert "Total records: 50" in out
        assert "NOTE: requested range" not in out
        # All 50 rows present in the CSV body.
        assert out.count("\n") >= 50

    def test_over_cap_keeps_most_recent_rows_and_notes_truncation(self, monkeypatch):
        set_config({"max_ohlcv_rows": 10})
        monkeypatch.setattr(yfin.yf, "Ticker", _fake_ohlcv_ticker(30))
        out = yfin.get_YFin_data_online("AAPL", "2020-01-01", "2020-01-30")
        assert "Total records: 30" in out
        assert "NOTE: requested range had 30 rows; showing the most recent 10" in out
        # The most recent date (row 29, 2020-01-30) must survive in the CSV
        # body; the earliest (row 0, 2020-01-01) must not -- proves it kept
        # the TAIL, not an arbitrary or head-biased cut. Check the CSV body
        # only (the header line legitimately echoes the requested start
        # date regardless of what got kept).
        csv_body = out.split("\n\n", 1)[1]
        assert "2020-01-30" in csv_body
        assert "2020-01-01" not in csv_body

    def test_zero_or_none_cap_disables_capping(self, monkeypatch):
        set_config({"max_ohlcv_rows": None})
        monkeypatch.setattr(yfin.yf, "Ticker", _fake_ohlcv_ticker(500))
        out = yfin.get_YFin_data_online("AAPL", "2020-01-01", "2021-05-15")
        assert "Total records: 500" in out
        assert "NOTE: requested range" not in out


@pytest.mark.unit
class TestIndicatorDayCap:
    def test_within_cap_untouched(self, monkeypatch):
        set_config({"max_indicator_days": 90})
        monkeypatch.setattr(
            yfin, "_get_stock_stats_bulk", lambda symbol, indicator, curr_date: {}
        )
        out = yfin.get_stock_stats_indicators_window("AAPL", "rsi", "2026-04-20", 30)
        assert "NOTE: requested look_back_days" not in out

    def test_over_cap_clamped_and_noted(self, monkeypatch):
        set_config({"max_indicator_days": 30})
        monkeypatch.setattr(
            yfin, "_get_stock_stats_bulk", lambda symbol, indicator, curr_date: {}
        )
        out = yfin.get_stock_stats_indicators_window("AAPL", "rsi", "2026-04-20", 365)
        assert "NOTE: requested look_back_days=365 was capped to 30" in out
        # The date range header must reflect the CLAMPED window, not the
        # originally requested one.
        assert "from 2026-03-21 to 2026-04-20" in out
