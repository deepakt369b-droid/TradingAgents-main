"""Tests for the parked-run registry (graph.run_registry)."""

import tempfile

import pytest

from tradingagents.graph import run_registry


@pytest.mark.unit
class TestRunRegistry:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_park_then_list(self):
        run_registry.park_run(
            self.tmpdir, "AAPL", "2026-04-20", "sig1", "thread-abc",
            step=3, failed_role="quick", failed_provider="ollama",
            error_info={"type": "RateLimitError", "message": "boom", "status_code": 429},
        )
        parked = run_registry.list_parked_runs(self.tmpdir)
        assert len(parked) == 1
        row = parked[0]
        assert row["ticker"] == "AAPL"
        assert row["trade_date"] == "2026-04-20"
        assert row["failed_role"] == "quick"
        assert row["failed_provider"] == "ollama"
        assert row["status"] == "parked"
        assert row["status_code"] == 429

    def test_get_parked_run(self):
        run_registry.park_run(
            self.tmpdir, "MSFT", "2026-04-21", "", "thread-xyz",
            step=None, failed_role="deep", failed_provider="kimi",
            error_info={"type": "RateLimitError", "message": "boom", "status_code": 429},
        )
        row = run_registry.get_parked_run(self.tmpdir, "msft", "2026-04-21", "")
        assert row is not None
        assert row["ticker"] == "MSFT"  # normalized to upper

        assert run_registry.get_parked_run(self.tmpdir, "MSFT", "2026-04-22", "") is None

    def test_repeated_park_upserts_not_duplicates(self):
        for step in (1, 2, 3):
            run_registry.park_run(
                self.tmpdir, "TSLA", "2026-04-20", "sig", "thread-1",
                step=step, failed_role="quick", failed_provider="ollama",
                error_info={"type": "RateLimitError", "message": "boom", "status_code": 429},
            )
        parked = run_registry.list_parked_runs(self.tmpdir)
        assert len(parked) == 1
        assert parked[0]["step"] == 3

    def test_mark_resolved_removes_from_parked_list(self):
        run_registry.park_run(
            self.tmpdir, "NVDA", "2026-04-20", "", "thread-1",
            step=1, failed_role="deep", failed_provider="kimi",
            error_info={"type": "RateLimitError", "message": "boom", "status_code": 429},
        )
        assert len(run_registry.list_parked_runs(self.tmpdir)) == 1

        run_registry.mark_run_resolved(self.tmpdir, "NVDA", "2026-04-20", "", status="resumed")
        assert run_registry.list_parked_runs(self.tmpdir) == []
        assert len(run_registry.list_parked_runs(self.tmpdir, status="resumed")) == 1

    def test_reparking_a_resolved_run_reopens_it(self):
        run_registry.park_run(
            self.tmpdir, "AMD", "2026-04-20", "", "thread-1",
            step=1, failed_role="deep", failed_provider="kimi",
            error_info={"type": "RateLimitError", "message": "boom", "status_code": 429},
        )
        run_registry.mark_run_resolved(self.tmpdir, "AMD", "2026-04-20", "", status="resumed")
        assert run_registry.list_parked_runs(self.tmpdir) == []

        # Fails again on the swapped-to provider -- must reopen as parked.
        run_registry.park_run(
            self.tmpdir, "AMD", "2026-04-20", "", "thread-1",
            step=2, failed_role="quick", failed_provider="deepseek",
            error_info={"type": "RateLimitError", "message": "boom again", "status_code": 429},
        )
        parked = run_registry.list_parked_runs(self.tmpdir)
        assert len(parked) == 1
        assert parked[0]["failed_provider"] == "deepseek"

    def test_rejects_path_unsafe_ticker(self):
        with pytest.raises(ValueError):
            run_registry.park_run(
                self.tmpdir, "../../etc", "2026-04-20", "", "thread-1",
                step=1, failed_role="deep", failed_provider="kimi",
                error_info={"type": "RateLimitError", "message": "boom", "status_code": 429},
            )
