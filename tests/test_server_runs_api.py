"""Tests for the parked-run discovery/clear endpoints (/api/runs, /api/runs/clear)."""

import tempfile

import pytest
from fastapi.testclient import TestClient

from app.server import create_app
from tradingagents.graph import run_registry
from tradingagents.graph.checkpointer import has_checkpoint, thread_id


@pytest.fixture
def client(monkeypatch):
    # Import lazily (not at module top) and patch whatever
    # tradingagents.default_config.DEFAULT_CONFIG currently points to. Other
    # test modules elsewhere in the suite call importlib.reload(default_config)
    # mid-run, which rebinds that module attribute to a brand-new dict object
    # -- a module-top `from ... import DEFAULT_CONFIG` here would capture a
    # stale reference decoupled from the dict app/server.py's handlers
    # freshly re-import at request time, silently patching the wrong object.
    import tradingagents.default_config as dc
    tmpdir = tempfile.mkdtemp()
    monkeypatch.setitem(dc.DEFAULT_CONFIG, "data_cache_dir", tmpdir)
    app = create_app()
    return TestClient(app), tmpdir


@pytest.mark.unit
class TestListRuns:
    def test_empty_by_default(self, client):
        c, _tmpdir = client
        resp = c.get("/api/runs")
        assert resp.status_code == 200
        assert resp.json() == {"runs": []}

    def test_lists_parked_runs(self, client):
        c, tmpdir = client
        run_registry.park_run(
            tmpdir, "AAPL", "2026-04-20", "", "tid-1",
            step=2, failed_role="quick", failed_provider="ollama",
            error_info={"type": "RateLimitError", "message": "boom", "status_code": 429},
        )
        resp = c.get("/api/runs")
        assert resp.status_code == 200
        runs = resp.json()["runs"]
        assert len(runs) == 1
        assert runs[0]["ticker"] == "AAPL"
        assert runs[0]["failed_provider"] == "ollama"

    def test_status_filter(self, client):
        c, tmpdir = client
        run_registry.park_run(
            tmpdir, "MSFT", "2026-04-20", "", "tid-2",
            step=1, failed_role="deep", failed_provider="kimi",
            error_info={"type": "RateLimitError", "message": "boom", "status_code": 429},
        )
        run_registry.mark_run_resolved(tmpdir, "MSFT", "2026-04-20", "", status="resumed")

        assert c.get("/api/runs?status=parked").json()["runs"] == []
        resolved = c.get("/api/runs?status=resumed").json()["runs"]
        assert len(resolved) == 1


@pytest.mark.unit
class TestClearRun:
    def test_requires_ticker_and_date(self, client):
        c, _tmpdir = client
        resp = c.post("/api/runs/clear", json={})
        assert resp.status_code == 400

    def test_clears_checkpoint_and_marks_resolved(self, client):
        c, tmpdir = client
        tid = thread_id("AAPL", "2026-04-20")
        # Seed a checkpoint the same way the graph would (via the sqlite
        # saver), and a parked-run record.
        from tradingagents.graph.checkpointer import get_checkpointer
        with get_checkpointer(tmpdir, "AAPL") as saver:
            saver.put(
                {"configurable": {"thread_id": tid, "checkpoint_ns": ""}},
                {
                    "v": 1, "id": "1", "ts": "2026-04-20T00:00:00",
                    "channel_values": {}, "channel_versions": {}, "versions_seen": {},
                },
                {"step": 1},
                {},
            )
        assert has_checkpoint(tmpdir, "AAPL", "2026-04-20")

        run_registry.park_run(
            tmpdir, "AAPL", "2026-04-20", "", tid,
            step=1, failed_role="quick", failed_provider="ollama",
            error_info={"type": "RateLimitError", "message": "boom", "status_code": 429},
        )

        resp = c.post("/api/runs/clear", json={"ticker": "AAPL", "trade_date": "2026-04-20"})
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        assert not has_checkpoint(tmpdir, "AAPL", "2026-04-20")
        assert run_registry.list_parked_runs(tmpdir) == []
        assert len(run_registry.list_parked_runs(tmpdir, status="cleared")) == 1
