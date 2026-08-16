"""Paper-first gate: the single source of truth for whether real orders may be placed.

Every executor construction and every order submission checks this. Default
is always paper/sandbox -- live trading requires an explicit, affirmative
opt-in via ``TRADINGAGENTS_LIVE_TRADING_ENABLED``, and even then a kill-switch
file on the persistent volume can halt submission without touching config or
redeploying.
"""

from __future__ import annotations

import os
from pathlib import Path

_LIVE_ENV_VAR = "TRADINGAGENTS_LIVE_TRADING_ENABLED"
_TRUE_VALUES = ("true", "1", "yes", "on")
_KILL_SWITCH_FILENAME = "LIVE_TRADING_KILL_SWITCH"


def is_live_trading_enabled() -> bool:
    """Whether live (real-money) order submission is permitted at all.

    False (the default, and the value of an unset/misconfigured env var) is
    the only safe default: every executor falls back to paper/sandbox
    behavior when this is False, regardless of what platform was requested.
    """
    return os.environ.get(_LIVE_ENV_VAR, "").strip().lower() in _TRUE_VALUES


def kill_switch_path(data_dir: str | Path) -> Path:
    return Path(data_dir) / _KILL_SWITCH_FILENAME


def is_kill_switch_active(data_dir: str | Path) -> bool:
    """Whether the kill-switch file is present.

    Checked immediately before every order submission (see
    ``SignalBridge.execute_signal``). Halting this way -- dropping a file on
    the persistent volume -- works without touching config, env vars, or a
    redeploy, and survives a container restart since the volume is what
    persists it.
    """
    return kill_switch_path(data_dir).exists()
