import os

_TRADINGAGENTS_HOME = os.path.join(os.path.expanduser("~"), ".tradingagents")

# Single source of truth for env-var → config-key overrides. To expose
# a new config key for environment-based override, add a row here — no
# entry-point script changes required. Coercion is driven by the type
# of the existing default, so users can keep writing plain strings in
# their .env file.
_ENV_OVERRIDES = {
    "TRADINGAGENTS_LLM_PROVIDER":         "llm_provider",
    "TRADINGAGENTS_DEEP_THINK_LLM":       "deep_think_llm",
    "TRADINGAGENTS_QUICK_THINK_LLM":      "quick_think_llm",
    "TRADINGAGENTS_LLM_BACKEND_URL":      "backend_url",
    # Per-role provider override. When unset (None), the role falls back to
    # llm_provider / backend_url, so existing single-provider configs and
    # tests are unaffected. Set both to route deep-thinking and quick-thinking
    # calls to different providers (e.g. Kimi for deep, Ollama for quick).
    "TRADINGAGENTS_DEEP_PROVIDER":        "deep_think_provider",
    "TRADINGAGENTS_DEEP_BASE_URL":        "deep_think_base_url",
    "TRADINGAGENTS_QUICK_PROVIDER":       "quick_think_provider",
    "TRADINGAGENTS_QUICK_BASE_URL":       "quick_think_base_url",
    "TRADINGAGENTS_OUTPUT_LANGUAGE":      "output_language",
    "TRADINGAGENTS_MAX_DEBATE_ROUNDS":    "max_debate_rounds",
    "TRADINGAGENTS_MAX_RISK_ROUNDS":      "max_risk_discuss_rounds",
    "TRADINGAGENTS_CHECKPOINT_ENABLED":   "checkpoint_enabled",
    "TRADINGAGENTS_BENCHMARK_TICKER":     "benchmark_ticker",
    "TRADINGAGENTS_MAX_OHLCV_ROWS":       "max_ohlcv_rows",
    "TRADINGAGENTS_MAX_INDICATOR_DAYS":   "max_indicator_days",
    "TRADINGAGENTS_TOKEN_BUDGET_PER_RUN": "token_budget_per_run",
    # Execution platform for the worker/signal bridge (tradingagents/execution/).
    # Deliberately NOT TRADINGAGENTS_-prefixed: EXECUTION_PLATFORM is the
    # existing env var name app/config_store.py's credential store already
    # writes when the web UI's "Trading Execution Platform" dropdown is
    # saved -- kept as-is for backward compatibility with that UI/store.
    "EXECUTION_PLATFORM": "execution_platform",
    "TRADINGAGENTS_WORKER_CALENDAR": "worker_calendar",
    "TRADINGAGENTS_AI_TRADER_BASE_URL": "ai_trader_base_url",
    "TRADINGAGENTS_AI_TRADER_AGENT_TOKEN": "ai_trader_agent_token",
    "TRADINGAGENTS_TEMPERATURE":          "temperature",
    "TRADINGAGENTS_LLM_MAX_RETRIES":      "llm_max_retries",
    # Provider-specific reasoning/thinking knobs (None = each provider's own
    # default). Settable here for non-interactive runs; the CLI also offers an
    # interactive choice, which is skipped when the matching var is set.
    "TRADINGAGENTS_GOOGLE_THINKING_LEVEL":   "google_thinking_level",
    "TRADINGAGENTS_OPENAI_REASONING_EFFORT": "openai_reasoning_effort",
    "TRADINGAGENTS_ANTHROPIC_EFFORT":        "anthropic_effort",
}


_BOOL_TRUE = ("true", "1", "yes", "on")
_BOOL_FALSE = ("false", "0", "no", "off")


def _coerce(value: str, reference):
    """Coerce env-var string to the type of the existing default value.

    Invalid values raise ``ValueError`` rather than silently falling back to a
    default — a misspelled boolean (e.g. ``treu``) or non-numeric int should fail
    loudly at startup, not quietly misconfigure an unattended run.
    """
    if isinstance(reference, bool):
        normalized = value.strip().lower()
        if normalized in _BOOL_TRUE:
            return True
        if normalized in _BOOL_FALSE:
            return False
        raise ValueError(
            f"expected a boolean ({'/'.join(_BOOL_TRUE + _BOOL_FALSE)}), got {value!r}"
        )
    if isinstance(reference, int) and not isinstance(reference, bool):
        return int(value)
    if isinstance(reference, float):
        return float(value)
    return value


def _apply_env_overrides(config: dict) -> dict:
    """Apply TRADINGAGENTS_* env vars to the config dict in-place."""
    for env_var, key in _ENV_OVERRIDES.items():
        raw = os.environ.get(env_var)
        if raw is None or raw == "":
            continue
        try:
            config[key] = _coerce(raw, config.get(key))
        except ValueError as exc:
            raise ValueError(f"Invalid value for {env_var}: {exc}") from exc
    return config


DEFAULT_CONFIG = _apply_env_overrides({
    "project_dir": os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
    "results_dir": os.getenv("TRADINGAGENTS_RESULTS_DIR", os.path.join(_TRADINGAGENTS_HOME, "logs")),
    "data_cache_dir": os.getenv("TRADINGAGENTS_CACHE_DIR", os.path.join(_TRADINGAGENTS_HOME, "cache")),
    "memory_log_path": os.getenv("TRADINGAGENTS_MEMORY_LOG_PATH", os.path.join(_TRADINGAGENTS_HOME, "memory", "trading_memory.md")),
    # Optional cap on the number of resolved memory log entries. When set,
    # the oldest resolved entries are pruned once this limit is exceeded.
    # Pending entries are never pruned. None disables rotation entirely.
    "memory_log_max_entries": None,
    # LLM settings
    "llm_provider": "openai",
    "deep_think_llm": "gpt-5.5",
    "quick_think_llm": "gpt-5.4-mini",
    # When None, each provider's client falls back to its own default endpoint
    # (api.openai.com for OpenAI, generativelanguage.googleapis.com for Gemini, ...).
    # The CLI overrides this per provider when the user picks one. Keeping a
    # provider-specific URL here would leak (e.g. OpenAI's /v1 was previously
    # being forwarded to Gemini, producing malformed request URLs).
    "backend_url": None,
    # Per-role provider overrides. None means "use llm_provider / backend_url
    # for this role" -- the pre-existing single-provider behavior. Set one or
    # both to split deep-thinking and quick-thinking across providers (e.g.
    # a cloud provider for deep reasoning, a local Ollama endpoint for the
    # high-volume quick-thinking calls).
    "deep_think_provider": None,
    "deep_think_base_url": None,
    "quick_think_provider": None,
    "quick_think_base_url": None,
    # Provider-specific thinking configuration
    "google_thinking_level": None,      # "high", "minimal", etc.
    "openai_reasoning_effort": None,    # "medium", "high", "low"
    "anthropic_effort": None,           # "high", "medium", "low"
    # Sampling temperature, forwarded to every provider when set. None leaves
    # each provider at its own default. Lower values reduce run-to-run
    # variation on models that honor it; reasoning models largely ignore it
    # and no setting makes LLM output bit-identical across runs (see README).
    "temperature": None,
    # SDK retry budget forwarded to every provider chat client. None leaves each
    # provider/SDK at its own default (usually 2). Raise it to ride out bursty
    # 429 throttling on rate-limited deployments instead of aborting a run (#1091).
    "llm_max_retries": None,
    # Checkpoint/resume: when True, LangGraph saves state after each node
    # so a crashed run can resume from the last successful step.
    "checkpoint_enabled": False,
    # Output language for analyst reports and final decision
    # Internal agent debate stays in English for reasoning quality
    "output_language": "English",
    # Debate and discussion settings
    "max_debate_rounds": 1,
    "max_risk_discuss_rounds": 1,
    "max_recur_limit": 100,
    # News / data fetching parameters
    # Increase for longer lookback strategies or to broaden macro coverage;
    # decrease to reduce token usage in agent prompts.
    "news_article_limit": 20,             # max articles per ticker (ticker-news)
    "global_news_article_limit": 10,      # max articles for global/macro news
    "global_news_lookback_days": 7,       # macro news lookback window
    # Row caps on agent-controlled date-range tool calls (get_stock_data,
    # get_indicators). The agent picks start/end dates or a look-back window
    # itself with no upstream bound, so an unusually wide request otherwise
    # serializes the full range into the prompt uncapped. Capped by ROWS
    # (most recent N kept), never by truncating the serialized CSV string --
    # a string-length cut silently drops rows from the middle while leaving
    # output that still parses, which is a data-corruption risk in a system
    # that reads this to place trades.
    "max_ohlcv_rows": 250,                # ~1 trading year of daily OHLCV rows
    "max_indicator_days": 90,             # cap on get_indicators' look_back_days
    # None = unlimited. When set, a run that spends more than this many
    # tokens (input + output, summed across every LLM call) parks cleanly
    # via the same path as a provider quota error (StatsCallbackHandler /
    # TokenBudgetExceededError) instead of running unbounded. Requires
    # checkpoint_enabled to actually park rather than just crash.
    "token_budget_per_run": None,
    # Execution platform for the worker/signal bridge: "paper", "alpaca",
    # "ccxt"/"binance"/"coinbase"/"kucoin"/"bybit", or "ibkr" (unsupported --
    # requires a TWS/IB Gateway process). "paper" is always the safe default;
    # every other value still resolves to paper/sandbox mode unless
    # TRADINGAGENTS_LIVE_TRADING_ENABLED is set (see execution/live_gate.py).
    "execution_platform": "paper",
    # Market calendar the worker checks before running a tick (see
    # app/worker.py::is_trading_day). "XNYS" (NYSE) by default; a
    # crypto-only watchlist can leave this as-is since exchange_calendars
    # isn't required -- the worker falls back to a plain weekday check when
    # it isn't installed, which already covers crypto (every day is "open").
    "worker_calendar": "XNYS",
    # Optional: post completed decisions to an AI-Trader instance (hosted
    # ai4trade.ai, or a self-run instance) for its leaderboard/copy-trade
    # surface (see integrations/ai_trader_client.py). Both None = disabled,
    # the default -- this is purely additive to the pipeline.
    "ai_trader_base_url": None,
    "ai_trader_agent_token": None,
    # Search queries used by get_global_news for macro headlines. Extend or
    # replace to broaden geographic / sector coverage.
    "global_news_queries": [
        "Federal Reserve interest rates inflation",
        "S&P 500 earnings GDP economic outlook",
        "geopolitical risk trade war sanctions",
        "ECB Bank of England BOJ central bank policy",
        "oil commodities supply chain energy",
    ],
    # Data vendor configuration
    # Category-level configuration (default for all tools in category).
    # The configured value is the exact vendor chain — requests are NOT silently
    # routed to vendors you didn't choose. For ordered fallback, list several,
    # e.g. "yfinance,alpha_vantage". "default" uses all available vendors.
    "data_vendors": {
        "core_stock_apis": "yfinance",       # Options: alpha_vantage, yfinance
        "technical_indicators": "yfinance",  # Options: alpha_vantage, yfinance
        "fundamental_data": "yfinance",      # Options: alpha_vantage, yfinance
        "news_data": "yfinance",             # Options: alpha_vantage, yfinance
        "macro_data": "fred",                # Options: fred (needs FRED_API_KEY)
        "prediction_markets": "polymarket",  # Options: polymarket (keyless)
    },
    # Tool-level configuration (takes precedence over category-level)
    "tool_vendors": {
        # Example: "get_stock_data": "alpha_vantage",  # Override category default
    },
    # Benchmark for alpha calculation in the reflection layer.
    # ``benchmark_ticker`` (when set) overrides the suffix map for all
    # tickers; leave it None to use ``benchmark_map`` for auto-detection
    # based on the ticker's exchange suffix. SPY remains the US default
    # so the reflection label keeps reading "Alpha vs SPY" for US tickers
    # while non-US tickers get their regional index automatically.
    "benchmark_ticker": None,
    "benchmark_map": {
        ".NS":  "^NSEI",       # NSE India (Nifty 50)
        ".BO":  "^BSESN",      # BSE India (Sensex)
        ".T":   "^N225",       # Tokyo (Nikkei 225)
        ".HK":  "^HSI",        # Hong Kong (Hang Seng)
        ".L":   "^FTSE",       # London (FTSE 100)
        ".TO":  "^GSPTSE",     # Toronto (TSX Composite)
        ".AX":  "^AXJO",       # Australia (ASX 200)
        ".SS":  "000001.SS",   # Shanghai (SSE Composite)
        ".SZ":  "399001.SZ",   # Shenzhen (SZSE Component)
        "":     "SPY",         # default for US-listed tickers (no suffix)
    },
})
