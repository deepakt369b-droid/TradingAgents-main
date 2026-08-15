"""OAuth / account login for CLI coding agents (the "Agent Skills" section).

Several agent CLIs can authenticate with a provider account instead of an API
key (``claude auth login``, ``codex login --device-auth``,
``opencode auth login``). Those flows print a URL (and often a code) and then
*poll* until the user authorizes in their browser -- which works fine inside
a headless container: the URL is surfaced to the web UI, the user approves
with their subscribed account, and the CLI stores the credentials in its
config folder on the server. The analysis runner then uses those credentials
automatically when no API key is provided (it only injects a key env var when
one is set).

Not every agent supports a login command: the gemini CLI (0.53+) has no
``auth login`` subcommand (use ``GEMINI_API_KEY`` or gcloud ADC instead), and
tools not installed in the container report an error rather than pretending
to log in.
"""

from __future__ import annotations

import contextlib
import logging
import re
import subprocess
import threading
import time
from collections import deque

from app import cli_runner

logger = logging.getLogger(__name__)

# Non-interactive login command per tool. The CLI prints a URL (+ code) and
# waits for the user to authorize; we capture and surface that to the UI.
TOOL_LOGIN_COMMANDS: dict[str, list[str]] = {
    "claude": ["auth", "login"],
    # Plain `codex login` starts a localhost callback server (only works with
    # SSH port forwarding); --device-auth prints a URL + code and polls, which
    # is what works inside a container.
    "codex": ["login", "--device-auth"],
    # --provider skips opencode's interactive provider picker and --method
    # its method picker; the headless method prints a URL + code and polls.
    "opencode": ["auth", "login", "--provider", "openai", "--method", "ChatGPT Pro/Plus (headless)"],
    # Kimi Code CLI authenticates via a built-in device-code flow (URL + code).
    "kimi": ["login"],
    # gemini CLI 0.53+ has no `auth login` subcommand — authenticate via
    # GEMINI_API_KEY or gcloud ADC instead.
}

URL_RE = re.compile(r"https?://[^\s\"'<>\]\)]+")
CODE_RE = re.compile(r"([A-Z0-9]{4,}(?:-[A-Z0-9]{4,})+)")
ANSI_RE = re.compile(r"\x1b\[[?0-9;]*[A-Za-z]")

# Seconds to wait in start_login() for the CLI to print its authorization URL
# before returning (the response includes the URL when available).
URL_WAIT_SECONDS = 10
MAX_LINES = 200
MAX_LINE_CHARS = 300
# Output markers that confirm a successful login even when the process exits
# non-zero (e.g. some CLIs crash on teardown on Windows after confirming).
SUCCESS_MARKERS = ("login successful", "logged in")


def _looks_successful(state: LoginState) -> bool:
    if state.exit_code == 0:
        return True
    tail = "\n".join(state.lines).lower()
    return any(marker in tail for marker in SUCCESS_MARKERS)


class LoginState:
    """Live state of one running login process."""

    def __init__(self, tool: str, exe: str, cmd: list[str], proc: subprocess.Popen):
        self.tool = tool
        self.exe = exe
        self.cmd = cmd
        self.proc = proc
        self.lines: deque[str] = deque(maxlen=MAX_LINES)
        self.url: str | None = None
        self.code: str | None = None
        self.done = False
        self.exit_code: int | None = None
        self.started = time.time()


_LOGINS: dict[str, LoginState] = {}
_LOCK = threading.Lock()


def _strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def _reader(state: LoginState) -> None:
    """Drain the login process stdout, capturing the URL and code."""
    for raw in state.proc.stdout:  # type: ignore[union-attr]
        line = _strip_ansi(raw).strip()
        if not line:
            continue
        state.lines.append(line[:MAX_LINE_CHARS])
        if not state.url:
            match = URL_RE.search(line)
            if match:
                # Trim trailing sentence punctuation (e.g. "http://x:1455.")
                state.url = match.group(0).rstrip(".,;:!?")
        if not state.code:
            match = CODE_RE.search(line)
            if match:
                state.code = match.group(0)
    with contextlib.suppress(Exception):
        state.exit_code = state.proc.wait(timeout=10)
    state.done = True


def login_status(tool: str) -> dict:
    """Return the current state of a login started via :func:`start_login`."""
    with _LOCK:
        state = _LOGINS.get(tool)
    if state is None:
        return {"tool": tool, "running": False, "done": False, "error": f"No login started for '{tool}'"}
    return {
        "tool": tool,
        "running": not state.done,
        "done": state.done,
        "success": _looks_successful(state) if state.done else None,
        "url": state.url,
        "code": state.code,
        "exit_code": state.exit_code,
        "output": list(state.lines)[-10:],
        "elapsed": round(time.time() - state.started, 1),
    }


def start_login(tool: str) -> dict:
    """Start an OAuth login for ``tool`` and return the authorization URL.

    The process keeps running in the background; poll :func:`login_status`
    until ``done`` is true.
    """
    tool = tool.strip().lower()
    with _LOCK:
        existing = _LOGINS.get(tool)
        if existing is not None and not existing.done:
            return {"success": True, "running": True, "url": existing.url, "code": existing.code}

    command = TOOL_LOGIN_COMMANDS.get(tool)
    if command is None:
        return {"success": False, "error": f"No login command configured for '{tool}'"}
    exe = cli_runner.resolve_executable(tool, True)
    if not exe:
        return {"success": False, "error": f"'{tool}' is not installed in this environment"}

    cmd = [exe] + list(command)
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, ValueError) as exc:
        return {"success": False, "error": str(exc)}

    state = LoginState(tool, exe, cmd, proc)
    threading.Thread(target=_reader, args=(state,), daemon=True).start()
    with _LOCK:
        _LOGINS[tool] = state

    # Wait briefly so the response can include the URL the CLI prints.
    deadline = time.monotonic() + URL_WAIT_SECONDS
    while time.monotonic() < deadline and not (state.url or state.done):
        time.sleep(0.2)

    return {
        "success": True,
        "tool": tool,
        "running": not state.done,
        "url": state.url,
        "code": state.code,
        "done": state.done,
    }
