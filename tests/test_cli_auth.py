"""Tests for app.cli_auth -- OAuth login for CLI coding agents.

Covers the login-command map, URL/code capture from the CLI's stdout, the
non-fatal errors (missing binary / unknown tool), and the running -> done
status transition.
"""

import threading
import time

import pytest

from app.cli_auth import TOOL_LOGIN_COMMANDS, _strip_ansi, login_status, start_login


class FakeProc:
    """Minimal stand-in for a subprocess.Popen handle."""

    def __init__(self, lines=(), code=0):
        self.stdout = iter(lines)
        self._code = code

    def wait(self, timeout=None):
        return self._code

    def poll(self):
        return self._code


class BlockingProc(FakeProc):
    """FakeProc whose stdout keeps waiting after its lines, like a real login
    CLI that polls for the user to authorize in the browser."""

    def __init__(self, lines=(), code=0):
        self._inner = iter(lines)
        self._code = code
        self.stdout = self
        self.release = threading.Event()

    def __iter__(self):
        return self

    def __next__(self):
        try:
            return next(self._inner)
        except StopIteration:
            # Simulate the CLI polling for authorization (never finishes in-test).
            self.release.wait(timeout=30)
            raise StopIteration from None


@pytest.fixture(autouse=True)
def _clean_logins():
    from app import cli_auth

    cli_auth._LOGINS.clear()
    yield
    cli_auth._LOGINS.clear()


@pytest.mark.unit
def test_login_commands_cover_polling_based_tools():
    # These use device-code style flows (URL + code, CLI polls), which
    # is what makes the container-side login flow possible.
    for tool in ("claude", "codex", "opencode", "kimi"):
        assert tool in TOOL_LOGIN_COMMANDS


@pytest.mark.unit
def test_start_login_captures_url_and_code(monkeypatch):
    monkeypatch.setattr("app.cli_runner.shutil.which", lambda name: "/usr/bin/codex")
    monkeypatch.setattr(
        "app.cli_auth.subprocess.Popen",
        lambda *a, **k: BlockingProc(
            lines=[
                "Open this URL to authorize ChatGPT: https://chatgpt.com/auth/login?code=abc\n",
                "Enter this code: ABCD-EFGH\n",
                "Waiting for authorization..\n",
            ],
            code=0,
        ),
    )
    result = start_login("codex")
    assert result["success"] is True
    assert "chatgpt.com" in result["url"]
    assert result["code"] == "ABCD-EFGH"
    assert result["running"] is True


@pytest.mark.unit
def test_start_login_missing_binary_errors(monkeypatch):
    monkeypatch.setattr("app.cli_runner.shutil.which", lambda name: None)
    result = start_login("claude")
    assert result["success"] is False
    assert "not installed" in result["error"]


@pytest.mark.unit
def test_start_login_unknown_tool_errors():
    result = start_login("freebuff")
    assert result["success"] is False
    assert "No login command" in result["error"]


@pytest.mark.unit
def test_login_status_reaches_done(monkeypatch):
    monkeypatch.setattr("app.cli_runner.shutil.which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr(
        "app.cli_auth.subprocess.Popen",
        lambda *a, **k: FakeProc(lines=["Opening authorization page\n"], code=0),
    )
    start = start_login("claude")
    assert start["success"] is True

    deadline = time.monotonic() + 2.0
    status = None
    while time.monotonic() < deadline:
        status = login_status("claude")
        if status["done"]:
            break
        time.sleep(0.05)
    assert status is not None and status["done"] is True
    assert status["exit_code"] == 0


@pytest.mark.unit
def test_strip_ansi():
    assert _strip_ansi("\x1b[32mOpen\x1b[0m https://example.com") == "Open https://example.com"
    # Cursor-hide / move-cursor codes used by spinner UIs
    assert _strip_ansi("\x1b[?25lWaiting\x1b[999D\x1b[J") == "Waiting"
    assert _strip_ansi("plain line") == "plain line"
