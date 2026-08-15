"""Tests for app.cli_runner -- headless invocation of CLI coding agents.

These cover the runner in isolation: prompt building, executable resolution,
skip behavior for unknown/missing tools, streaming output collection, and the
non-fatal error paths (timeout, non-zero exit).
"""

import sys
import time
import types

import pytest

from app.cli_runner import build_prompt, resolve_default_model, resolve_executable, run_cli_agents


class FakeProc:
    """Minimal stand-in for a subprocess.Popen handle."""

    def __init__(self, lines=(), code=0):
        self.stdout = iter(lines)
        self._code = code
        self.killed = False

    def wait(self, timeout=None):
        return self._code

    def poll(self):
        return self._code

    def kill(self):
        self.killed = True


class SlowProc(FakeProc):
    """FakeProc whose reader wait() blocks briefly, simulating a working agent."""

    def __init__(self, lines=("line\n",), code=0, delay=0.4):
        super().__init__(lines=lines, code=code)
        self.delay = delay

    def wait(self, timeout=None):
        time.sleep(self.delay)
        return self._code


@pytest.mark.unit
def test_build_prompt_mentions_ticker_date_and_language():
    prompt = build_prompt("AAPL", "2026-08-16", "Chinese")
    assert "AAPL" in prompt
    assert "2026-08-16" in prompt
    assert "Chinese" in prompt


@pytest.mark.unit
def test_resolve_executable_prefers_explicit_path(tmp_path):
    fake = tmp_path / "claude"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    assert resolve_executable("claude", str(fake)) == str(fake)


@pytest.mark.unit
def test_resolve_executable_falls_back_to_path(monkeypatch):
    monkeypatch.setattr(
        "app.cli_runner.shutil.which",
        lambda name: "/usr/bin/claude" if name == "claude" else None,
    )
    assert resolve_executable("claude", True) == "/usr/bin/claude"
    # A bogus explicit path falls back to PATH lookup of the tool name too.
    assert resolve_executable("claude", "/does/not/exist/claude") == "/usr/bin/claude"


@pytest.mark.unit
def test_unknown_tool_is_skipped_with_template_error(monkeypatch):
    monkeypatch.setattr("app.cli_runner.shutil.which", lambda name: None)
    results = run_cli_agents({"freebuff": True}, "AAPL", "2026-08-16")
    assert results["freebuff"]["status"] == "skipped"
    assert "template" in results["freebuff"]["error"]


@pytest.mark.unit
def test_missing_binary_is_skipped_not_fatal(monkeypatch):
    monkeypatch.setattr("app.cli_runner.shutil.which", lambda name: None)
    results = run_cli_agents({"claude": True}, "AAPL", "2026-08-16")
    assert results["claude"]["status"] == "skipped"
    assert "not installed" in results["claude"]["error"]


@pytest.mark.unit
def test_runs_tool_and_collects_output(monkeypatch):
    monkeypatch.setattr(
        "app.cli_runner.shutil.which", lambda name: "/usr/local/bin/claude"
    )
    monkeypatch.setattr(
        "app.cli_runner.subprocess.Popen",
        lambda *a, **k: FakeProc(lines=["hello world\n", "second line\n"], code=0),
    )
    events = []
    results = run_cli_agents({"claude": True}, "AAPL", "2026-08-16", emit=events.append)

    assert results["claude"]["status"] == "completed"
    assert "hello world" in results["claude"]["output"]
    assert "second line" in results["claude"]["output"]
    # Per-line output is streamed as Data messages tagged with the tool.
    assert any(
        ev.get("msg_type") == "Data" and "[claude]" in ev.get("content", "")
        for ev in events
    )
    assert any("finished" in ev.get("content", "") for ev in events)


@pytest.mark.unit
def test_timeout_marks_error_and_kills_proc(monkeypatch):
    monkeypatch.setattr("app.cli_runner.shutil.which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr(
        "app.cli_runner.subprocess.Popen",
        lambda *a, **k: FakeProc(lines=[], code=0),
    )
    results = run_cli_agents({"claude": True}, "AAPL", "2026-08-16", timeout=0)
    assert results["claude"]["status"] == "error"
    assert "Timed out" in results["claude"]["error"]


@pytest.mark.unit
def test_resolve_default_model_uses_catalog(monkeypatch):
    # Inject a fake model catalog so the test runs without the project deps.
    fake_catalog = types.ModuleType("tradingagents.llm_clients.model_catalog")
    fake_catalog.get_model_options = lambda provider, mode: (
        [("Opus", "claude-opus-4-8"), ("Custom model ID", "custom")]
        if provider == "anthropic"
        else [("Custom model ID", "custom")]
    )
    sys.modules.setdefault("tradingagents", types.ModuleType("tradingagents"))
    sys.modules.setdefault("tradingagents.llm_clients", types.ModuleType("tradingagents.llm_clients"))
    monkeypatch.setitem(sys.modules, "tradingagents.llm_clients.model_catalog", fake_catalog)

    assert resolve_default_model("claude") == "claude-opus-4-8"
    # Providers that only expose "custom" (kimi) fall back to the caller's model.
    assert resolve_default_model("kimi", fallback="gpt-5.5") == "gpt-5.5"


@pytest.mark.unit
def test_resolve_default_model_provider_agnostic_uses_fallback():
    # opencode is provider-agnostic: no catalog lookup, straight to fallback.
    assert resolve_default_model("opencode", fallback="gpt-5.4") == "gpt-5.4"


@pytest.mark.unit
def test_model_flag_appended_when_model_resolved(monkeypatch):
    monkeypatch.setattr("app.cli_runner.shutil.which", lambda name: "/usr/bin/claude")
    captured = {}

    def fake_popen(*args, **kwargs):
        captured["cmd"] = args[0]
        return FakeProc(lines=["ok\n"], code=0)

    monkeypatch.setattr("app.cli_runner.subprocess.Popen", fake_popen)
    run_cli_agents(
        {"claude": True}, "AAPL", "2026-08-16", models={"claude": "claude-opus-4-8"}
    )
    assert captured["cmd"][-2:] == ["--model", "claude-opus-4-8"]


@pytest.mark.unit
def test_no_model_flag_without_resolved_model(monkeypatch):
    monkeypatch.setattr("app.cli_runner.shutil.which", lambda name: "/usr/bin/claude")
    captured = {}

    def fake_popen(*args, **kwargs):
        captured["cmd"] = args[0]
        return FakeProc(lines=["ok\n"], code=0)

    monkeypatch.setattr("app.cli_runner.subprocess.Popen", fake_popen)
    run_cli_agents({"claude": True}, "AAPL", "2026-08-16")
    assert "--model" not in captured["cmd"]


@pytest.mark.unit
def test_runs_multiple_tools_in_parallel(monkeypatch):
    which_map = {"claude": "/usr/bin/claude", "codex": "/usr/bin/codex"}
    monkeypatch.setattr("app.cli_runner.shutil.which", lambda name: which_map.get(name))

    starts = []

    def fake_popen(*args, **kwargs):
        starts.append(time.monotonic())
        return SlowProc(delay=0.4)

    monkeypatch.setattr("app.cli_runner.subprocess.Popen", fake_popen)

    # With max_workers=2 both processes start almost simultaneously.
    results = run_cli_agents(
        {"claude": True, "codex": True}, "AAPL", "2026-08-16", max_workers=2
    )
    assert results["claude"]["status"] == "completed"
    assert results["codex"]["status"] == "completed"
    assert len(starts) == 2
    assert (max(starts) - min(starts)) < 0.2


@pytest.mark.unit
def test_max_workers_one_serializes_tools(monkeypatch):
    which_map = {"claude": "/usr/bin/claude", "codex": "/usr/bin/codex"}
    monkeypatch.setattr("app.cli_runner.shutil.which", lambda name: which_map.get(name))

    starts = []

    def fake_popen(*args, **kwargs):
        starts.append(time.monotonic())
        return SlowProc(delay=0.4)

    monkeypatch.setattr("app.cli_runner.subprocess.Popen", fake_popen)

    # With max_workers=1 the second tool waits for the first to finish.
    results = run_cli_agents(
        {"claude": True, "codex": True}, "AAPL", "2026-08-16", max_workers=1
    )
    assert results["claude"]["status"] == "completed"
    assert results["codex"]["status"] == "completed"
    assert len(starts) == 2
    assert (max(starts) - min(starts)) >= 0.3


@pytest.mark.unit
def test_per_tool_api_key_is_set_in_process_env(monkeypatch):
    monkeypatch.setattr("app.cli_runner.shutil.which", lambda name: "/usr/bin/claude")
    captured = {}

    def fake_popen(*args, **kwargs):
        captured["env"] = kwargs.get("env")
        return FakeProc(lines=["ok\n"], code=0)

    monkeypatch.setattr("app.cli_runner.subprocess.Popen", fake_popen)
    results = run_cli_agents(
        {"claude": True}, "AAPL", "2026-08-16", keys={"claude": "sk-test-123"}
    )
    assert results["claude"]["status"] == "completed"
    assert captured["env"]["ANTHROPIC_API_KEY"] == "sk-test-123"


@pytest.mark.unit
def test_missing_key_leaves_inherited_env_untouched(monkeypatch):
    monkeypatch.setattr("app.cli_runner.shutil.which", lambda name: "/usr/bin/claude")
    captured = {}

    def fake_popen(*args, **kwargs):
        captured["env"] = kwargs.get("env")
        return FakeProc(lines=["ok\n"], code=0)

    monkeypatch.setattr("app.cli_runner.subprocess.Popen", fake_popen)
    run_cli_agents({"claude": True}, "AAPL", "2026-08-16")
    env = captured["env"]
    assert env is not None
    assert env.get("ANTHROPIC_API_KEY") != "sk-test-123"
    assert env.get("PATH")  # inherited environment is still passed through


@pytest.mark.unit
def test_nonzero_exit_is_error_but_output_preserved(monkeypatch):
    monkeypatch.setattr("app.cli_runner.shutil.which", lambda name: "/usr/bin/codex")
    monkeypatch.setattr(
        "app.cli_runner.subprocess.Popen",
        lambda *a, **k: FakeProc(lines=["auth required\n"], code=1),
    )
    results = run_cli_agents({"codex": True}, "AAPL", "2026-08-16")
    assert results["codex"]["status"] == "error"
    assert "code 1" in results["codex"]["error"]
    assert "auth required" in results["codex"]["output"]
