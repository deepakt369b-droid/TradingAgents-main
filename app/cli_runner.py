"""Headless invocation of external CLI coding agents (the app's "Agent Skills").

The web UI's "CLI Integrations (Agent Skills)" section lets the user enable
coding agents (Claude Code, OpenAI Codex, Gemini CLI, OpenCode, ...) so they
contribute a second-opinion research pass to an analysis run.

The agent binaries run on the *server* -- inside the Docker container for a
Coolify deployment -- so they must be installed there (see the Dockerfile's
``INSTALL_AGENT_CLIS`` build arg) and have their provider API key present in
the environment (``ANTHROPIC_API_KEY``, ``OPENAI_API_KEY``,
``GEMINI_API_KEY``, ...).

Every tool is invoked in non-interactive print/exec mode. Failures are
non-fatal: a missing binary, timeout, or non-zero exit produces an error note
instead of aborting the analysis.
"""

from __future__ import annotations

import contextlib
import logging
import os
import queue
import shutil
import subprocess
import threading
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)

# Command templates per tool. ``{prompt}`` is replaced with the research
# prompt; the resulting argument list is passed to the binary directly (no
# shell), so quoting is handled by the OS. Tools without a template can be
# detected but not invoked.
CLI_TEMPLATES: dict[str, list[str]] = {
    "claude": ["-p", "{prompt}", "--output-format", "text"],
    "codex": ["exec", "{prompt}"],
    "gemini": ["-p", "{prompt}"],
    "opencode": ["run", "{prompt}"],
    "kimi": ["-p", "{prompt}"],
    "kimchi": ["-p", "{prompt}"],
}

DEFAULT_TIMEOUT = 240  # seconds per tool
DEFAULT_MAX_WORKERS = 3  # concurrent agent processes (each can be memory-heavy)
MAX_OUTPUT_CHARS = 6000  # per-tool output cap for the report

# Provider each agent authenticates against, used to pick the right default
# model from the app's model catalog. ``opencode`` is provider-agnostic and is
# intentionally absent -- it gets the app's configured deep model instead.
TOOL_PROVIDERS: dict[str, str] = {
    "claude": "anthropic",
    "codex": "openai",
    "gemini": "google",
    "kimi": "kimi",
    "kimchi": "anthropic",
}

# CLI flags used to pin the model per tool. ``{model}`` is the resolved model
# ID from the app's model configuration.
TOOL_MODEL_FLAGS: dict[str, list[str]] = {
    "claude": ["--model", "{model}"],
    "codex": ["--model", "{model}"],
    "gemini": ["-m", "{model}"],
    "opencode": ["--model", "{model}"],
    "kimi": ["-m", "{model}"],
    "kimchi": ["-m", "{model}"],
}

# Provider API key env var per tool. A key entered in the UI is injected into
# that tool's process environment only; tools without an entry (or without a
# UI key) still fall back to the inherited environment.
TOOL_KEY_ENV: dict[str, str] = {
    "claude": "ANTHROPIC_API_KEY",
    "codex": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "opencode": "OPENCODE_API_KEY",
    "kimi": "MOONSHOT_API_KEY",
    "kimchi": "ANTHROPIC_API_KEY",
}

DEFAULT_PROMPT = (
    "You are a financial research assistant contributing a second opinion to a "
    "multi-agent trading analysis of {ticker} on {date}. Give a concise, structured "
    "assessment with these sections: 1) Bull case, 2) Bear case, 3) Key risks, "
    "4) Verdict (BUY/SELL/HOLD) with 2-3 sentences of reasoning. Be specific and "
    "factual; do not invent data or prices. Respond in {language}."
)

EmitFn = Callable[[dict], None]


def build_prompt(ticker: str, analysis_date: str, language: str = "English") -> str:
    """Build the research prompt handed to each CLI agent."""
    return DEFAULT_PROMPT.format(
        ticker=ticker,
        date=analysis_date or "the latest trading day",
        language=language,
    )


def resolve_executable(tool: str, option: str | bool | None) -> str | None:
    """Resolve the binary to run: an explicit path wins, else PATH lookup."""
    if isinstance(option, str) and option.strip():
        candidate = option.strip()
        if os.path.exists(candidate):
            return candidate
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return shutil.which(tool)


def resolve_default_model(tool: str, fallback: str | None = None) -> str | None:
    """Pick the default deep model for a tool from the app's model catalog.

    Each agent maps to its own provider (see ``TOOL_PROVIDERS``), so e.g.
    ``claude`` gets the catalog's Anthropic deep model while ``codex`` gets
    the OpenAI one. Providers that only offer "Custom model ID" (e.g. kimi)
    return ``None`` so the agent keeps its own default; ``opencode`` falls
    back to the app's configured deep model via ``fallback``.
    """
    provider = TOOL_PROVIDERS.get(tool)
    if provider:
        try:
            from tradingagents.llm_clients.model_catalog import get_model_options

            for _label, value in get_model_options(provider, "deep"):
                if value != "custom":
                    return value
        except Exception:
            pass
    return fallback


def run_cli_agents(
    cli_options: dict,
    ticker: str,
    analysis_date: str,
    language: str = "English",
    timeout: int | None = None,
    emit: EmitFn | None = None,
    max_workers: int | None = None,
    keys: dict | None = None,
    models: dict | None = None,
) -> dict:
    """Run each enabled CLI agent, streaming line output through ``emit``.

    Agents run concurrently (bounded by ``max_workers``, default 3) to cut
    total wall time; each keeps its own per-tool timeout and output cap.

    Args:
        cli_options: ``{tool: path-or-True}`` from the analysis request.
        emit: optional callback receiving ``{"type": "message", ...}`` dicts
              (thread-safe; may be invoked from worker threads).
        max_workers: max concurrent agent processes.
        keys: optional ``{tool: api_key}``; each key is set as that tool's
              provider env var in its subprocess only.
        models: optional ``{tool: model_id}``; the model is pinned on the
              agent's CLI (e.g. ``--model``) so it matches the app's model
              configuration. Tools without a resolved model use their default.

    Returns:
        ``{tool: {"status": "completed"|"error"|"skipped",
                  "output": str, "error": str | None}}``
    """
    results: dict = {}
    jobs: list[tuple[str, str, list[str]]] = []
    for tool, option in (cli_options or {}).items():
        if not option:
            continue
        template = CLI_TEMPLATES.get(tool)
        if template is None:
            results[tool] = {
                "status": "skipped",
                "output": "",
                "error": f"No invocation template for '{tool}'",
            }
            continue
        exe = resolve_executable(tool, option)
        if not exe:
            results[tool] = {
                "status": "skipped",
                "output": "",
                "error": (
                    f"'{tool}' is not installed in this environment "
                    "(see the Dockerfile INSTALL_AGENT_CLIS build arg)"
                ),
            }
            continue
        jobs.append((tool, exe, template))

    if not jobs:
        return results

    max_workers = DEFAULT_MAX_WORKERS if max_workers is None else max(1, int(max_workers))
    semaphore = threading.Semaphore(max_workers)
    lock = threading.Lock()
    workers: list[tuple[str, threading.Thread]] = []
    keys = keys or {}
    models = models or {}

    def _worker(tool: str, exe: str, template: list[str]) -> None:
        with semaphore:
            result = _run_one(
                tool, exe, template, ticker, analysis_date, language, timeout, emit,
                key=keys.get(tool), model=models.get(tool),
            )
        with lock:
            results[tool] = result

    for tool, exe, template in jobs:
        thread = threading.Thread(target=_worker, args=(tool, exe, template), daemon=True)
        thread.start()
        workers.append((tool, thread))

    # Wait for all workers. Each _run_one enforces its own deadline, so this
    # join only needs a small safety margin beyond the per-tool timeout.
    deadline = time.monotonic() + (timeout or DEFAULT_TIMEOUT) + 15
    for tool, thread in workers:
        remaining = deadline - time.monotonic()
        if remaining > 0:
            thread.join(timeout=remaining)
        if thread.is_alive():
            with lock:
                results.setdefault(
                    tool, {"status": "error", "output": "", "error": "Agent did not finish in time"}
                )
    return results


def _run_one(
    tool: str,
    exe: str,
    template: list[str],
    ticker: str,
    analysis_date: str,
    language: str,
    timeout: int | None,
    emit: EmitFn | None,
    key: str | None = None,
    model: str | None = None,
) -> dict:
    timeout = DEFAULT_TIMEOUT if timeout is None else timeout
    prompt = build_prompt(ticker, analysis_date, language)
    cmd = [exe] + [arg.format(prompt=prompt) for arg in template]
    if model:
        flags = TOOL_MODEL_FLAGS.get(tool)
        if flags:
            cmd += [flag.format(model=model) for flag in flags]

    if emit:
        emit({"type": "message", "msg_type": "System", "content": f"Running CLI agent '{tool}' ({exe}) ..."})

    # Per-tool API key: inject into this subprocess's environment only. The
    # inherited environment stays the fallback for tools without a UI key.
    env = os.environ.copy()
    env_var = TOOL_KEY_ENV.get(tool)
    if env_var and key and str(key).strip():
        env[env_var] = str(key).strip()

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
    except (OSError, ValueError) as exc:
        return {"status": "error", "output": "", "error": str(exc)}

    # Reader thread: drain stdout line-by-line into a queue so the main thread
    # can stream messages without blocking on a chatty subprocess.
    lines_q: queue.Queue[str | None] = queue.Queue()

    def _reader() -> None:
        try:
            for line in proc.stdout:  # type: ignore[union-attr]
                lines_q.put(line)
        finally:
            with contextlib.suppress(Exception):
                proc.wait(timeout=5)
            lines_q.put(None)

    threading.Thread(target=_reader, daemon=True).start()

    collected: list[str] = []
    total = 0
    timed_out = False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            line = lines_q.get(timeout=0.5)
        except queue.Empty:
            continue
        if line is None:
            break
        stripped = line.strip()
        if not stripped:
            continue
        if emit:
            emit({"type": "message", "msg_type": "Data", "content": f"[{tool}] {stripped[:300]}"})
        if total < MAX_OUTPUT_CHARS:
            collected.append(stripped)
            total += len(stripped)
    else:
        timed_out = True

    if timed_out:
        with contextlib.suppress(Exception):
            proc.kill()

    exit_code = proc.poll()
    output = "\n".join(collected).strip()

    status, error = "completed", None
    if timed_out:
        status, error = "error", f"Timed out after {timeout}s"
    elif exit_code not in (0, None):
        status, error = "error", f"Exited with code {exit_code}"
    elif not output:
        status, error = "error", "No output produced"

    if emit:
        if error:
            emit({"type": "message", "msg_type": "System", "content": f"CLI agent '{tool}' error: {error}"})
        else:
            emit({"type": "message", "msg_type": "System", "content": f"CLI agent '{tool}' finished."})

    return {"status": status, "output": output, "error": error}
