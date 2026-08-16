# TradingAgents — Multi-Agent LLM Financial Trading Framework

A multi-agent trading framework that mirrors the dynamics of real-world trading firms. Specialized LLM-powered agents — fundamental analysts, sentiment experts, technical analysts, a trader, and a risk management team — collaboratively evaluate market conditions and inform trading decisions through dynamic discussion.

> **Disclaimer:** This framework is designed for research purposes. Trading performance may vary based on many factors, including the chosen backbone language models, model temperature, trading periods, data quality, and other non-deterministic factors. It is **not** intended as financial, investment, or trading advice.

---

## ✨ Features

- **Multi-agent architecture** — Analyst team, researcher team, trader, risk management, and portfolio manager.
- **Multi-provider LLM support** — OpenAI, Google, Anthropic, xAI, DeepSeek, Qwen, GLM, MiniMax, OpenRouter, Ollama, Azure, Bedrock, and any OpenAI-compatible endpoint.
- **Per-role provider routing** — Route deep-thinking and quick-thinking calls to different providers (e.g. Kimi for deep reasoning, a local Ollama endpoint for the high-volume quick calls). See [Per-role providers](#-per-role-llm-providers).
- **Browser API-key configuration** — Save LLM API keys directly from the web UI. Keys persist inside the project (`config/credentials.json`), so analysis works without setting environment variables on the host.
- **Headless web server** — Runs a FastAPI/uvicorn server on `0.0.0.0:8000`, ready for containerized deployment.
- **Coolify deployment** — See [`docs/Coolify_Deployment_Guide.pdf`](docs/Coolify_Deployment_Guide.pdf) for a step-by-step, image-rich guide to deploying on a self-hosted Coolify instance (Ubuntu VM).
- **Persistence & recovery** — Decision log, checkpoint resume, and quota-aware run parking (a run that hits a provider's rate limit parks instead of crashing, and resumes under a different provider). See [Persistence and Recovery](#-persistence-and-recovery).
- **Token-efficient debate layer** — Analyst reports are compressed into one evidence digest before the bull/bear and risk debates, instead of every debate turn re-reading all four full reports.
- **Paper and live trade execution** — Optional broker/exchange execution (Alpaca for US equities, CCXT for crypto) behind an explicit, off-by-default live-trading gate, plus a scheduled worker that runs the pipeline against a watchlist. See [Trade execution](#-trade-execution).

---

## 🚀 Quick Start (Browser)

1. Deploy the app (see the [Coolify deployment guide](docs/Coolify_Deployment_Guide.pdf)).
2. Open the app in your browser (e.g. `http://192.168.0.161:8001`).
3. In the **LLM Configuration** section, select your provider, enter your API key, and click **Save Key**.
4. Click **Validate & Fetch Models**, then **Launch Analysis**.

> **Security note:** API keys are stored in plaintext (like `.env`) in `config/credentials.json`, which is excluded from version control via `.gitignore`. Protect the volume and VM access.

---

## 📦 Installation

### Local

```bash
git clone <your-repo-url>
cd TradingAgents
```

Create a virtual environment:

```bash
conda create -n tradingagents python=3.12
conda activate tradingagents
```

Install the package and its dependencies:

```bash
pip install .
```

### Docker

```bash
cp .env.example .env  # add your API keys
docker compose run --rm tradingagents
```

For local models with Ollama:

```bash
docker compose --profile ollama run --rm tradingagents-ollama
```

---

## 🔑 API Keys

TradingAgents supports multiple LLM providers. You can set keys either via environment variables or directly in the browser (recommended for deployments).

### Option A — Browser (recommended)

Open the app, go to **LLM Configuration**, enter your key, and click **Save Key**. The key persists to `config/credentials.json` and is loaded automatically at startup.

### Option B — Environment variables

```bash
export OPENAI_API_KEY=...          # OpenAI (GPT)
export GOOGLE_API_KEY=...          # Google (Gemini)
export ANTHROPIC_API_KEY=...       # Anthropic (Claude)
export XAI_API_KEY=...             # xAI (Grok)
export DEEPSEEK_API_KEY=...        # DeepSeek
export DASHSCOPE_API_KEY=...       # Qwen — International
export DASHSCOPE_CN_API_KEY=...    # Qwen — China
export ZHIPU_API_KEY=...           # GLM via Z.AI (international)
export ZHIPU_CN_API_KEY=...        # GLM via BigModel (China)
export MINIMAX_API_KEY=...         # MiniMax — Global
export MINIMAX_CN_API_KEY=...      # MiniMax — China
export OPENROUTER_API_KEY=...      # OpenRouter
export ALPHA_VANTAGE_API_KEY=...   # Alpha Vantage
```

For Azure OpenAI, copy `.env.enterprise.example` to `.env.enterprise` and fill in your credentials.

For AWS Bedrock, install the extra with `pip install ".[bedrock]"`, set `llm_provider: "bedrock"`, configure AWS credentials, and use a Bedrock model ID.

For local models, configure Ollama with `llm_provider: "ollama"`. The default endpoint is `http://localhost:11434/v1`; set `OLLAMA_BASE_URL` to point at a remote `ollama-serve`.

For any other OpenAI-compatible server (vLLM, LM Studio, llama.cpp, or a custom relay), use `llm_provider: "openai_compatible"` and set the endpoint via `backend_url` (or `TRADINGAGENTS_LLM_BACKEND_URL`).

Alternatively, copy `.env.example` to `.env` and fill in your keys:

```bash
cp .env.example .env
```

---

## 🔀 Per-role LLM providers

Deep-thinking (Research Manager, Portfolio Manager) and quick-thinking (analysts, debate/risk nodes — the high-volume calls) can run on **different providers**, not just different models on the same provider:

```bash
export TRADINGAGENTS_DEEP_PROVIDER=kimi         # deep reasoning on Kimi K2
export TRADINGAGENTS_DEEP_BASE_URL=             # unset = Kimi's default endpoint
export TRADINGAGENTS_QUICK_PROVIDER=ollama      # high-volume quick calls on local Ollama
export TRADINGAGENTS_QUICK_BASE_URL=http://localhost:11434/v1
```

Both unset (the default) routes both roles through `TRADINGAGENTS_LLM_PROVIDER`/`llm_provider` — unchanged single-provider behavior. The same split is available from the web UI: check **"Use a different provider for Quick Thinking"** under LLM Configuration. Running Ollama on the same host as the container? Point `TRADINGAGENTS_QUICK_BASE_URL`/`OLLAMA_BASE_URL` at `http://host.docker.internal:11434/v1` — the compose files already add the `extra_hosts` entry that makes that hostname resolve.

---

## 🖥️ CLI Usage

Launch the interactive CLI:

```bash
tradingagents          # installed command
python -m cli.main     # alternative: run directly from source
```

You will see a screen where you can select your desired tickers, analysis date, LLM provider, research depth, and more.

### Markets and tickers

TradingAgents works with any market Yahoo Finance covers, using the exchange-suffixed ticker.

- US: `AAPL`, `SPY`
- Hong Kong: `0700.HK` · Tokyo: `7203.T` · London: `AZN.L`
- India: `RELIANCE.NS`, `.BO` · Canada: `.TO` · Australia: `.AX`
- China A-shares: Shanghai `.SS`, Shenzhen `.SZ`
- Crypto: `BTC-USD`, `ETH-USD`

---

## 🐳 Docker / Coolify Deployment

The project is configured for containerized deployment:

- **`Dockerfile`** — builds a headless FastAPI/uvicorn server on `0.0.0.0:8000`. The builder stage uses **[uv](https://github.com/astral-sh/uv)** (Rust package manager) with the locked `requirements.txt`, which downloads and compiles dependencies **in parallel while streaming progress output**. To keep the first build fast on slow networks, it uses a single `python:3.12-slim` base image for both stages (uv is installed via a small `pip install uv` wheel, not a separate ~70MB uv base image), omits the `# syntax=docker/dockerfile:1` directive (avoids pulling a 14MB BuildKit frontend), and installs **no `curl`** in the runtime image — the healthcheck uses Python's stdlib `urllib` instead. The optional **CLI agent integrations** (Claude Code, Codex, Gemini CLI, OpenCode — used by the app's "CLI Integrations (Agent Skills)" section) are installed in a separate cached layer; disable them with `--build-arg INSTALL_AGENT_CLIS=0` and provide each agent's provider API key (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, ...) as environment variables for them to actually run.

**Securing stored credentials:** API keys saved from the browser (LLM keys, Cloudflare gateway, brokerage, per-tool CLI keys) are persisted to `config/credentials.json`. To encrypt that file at rest, set `TRADINGAGENTS_CREDENTIALS_KEY` to any secret passphrase (or a raw 32-byte urlsafe-base64 Fernet key) in Coolify — the store is then written with Fernet encryption (`cryptography`, already a pinned dependency) and stays unreadable without the key. Unset, it falls back to plaintext (legacy behavior). Keep the key stable: losing or changing it makes previously saved credentials unreadable.

**CLI agent OAuth logins survive redeploys:** the CLI agent credential folders (`~/.claude`, `~/.codex`, `~/.gemini`, `~/.local/share/opencode`) are mounted as named Docker volumes (declared in `docker-compose*.yml` and pre-created with `appuser` ownership in the Dockerfile), so accounts authorized via the app's 🔑 Login buttons persist across container recreates instead of being wiped on every redeploy.
- **`docker-compose.coolify.yml`** — maps host port `8001` → container port `8000` (Coolify itself occupies port 8000), with a `tradingagents_config` volume so browser-saved API keys persist across restarts. Defines two services: `tradingagents` (the web UI, gets the Coolify domain) and `worker` (the scheduled watchlist worker, no domain — see [Trade Execution](#-trade-execution)), sharing the same `tradingagents_data` volume so checkpoints, the paper portfolio, and the order ledger stay consistent between them. Pass `--build-arg INSTALL_EXEC_DEPS=1` (or set `INSTALL_EXEC_DEPS=1` before `docker compose build`) to install the Alpaca/CCXT execution dependencies — omitted by default since paper trading needs neither.
- **`docs/Coolify_Deployment_Guide.pdf`** — full step-by-step deployment guide with architecture and flow diagrams.

> **Coolify 1-hour build limits:** The build uses `uv` (parallel, streams progress) and caches the dependency layer across builds. On slow network links (~80 kB/s measured on one host) the **first** build's image + PyPI downloads can approach the 1-hour queue timeout, so if the first deploy still times out, re-deploy once — Docker will reuse the layers already downloaded and the second build completes quickly. Keep the **Build Timeout** at `3600` seconds (1 hour) as it already is.

> **Coolify "exit code 255" mid-build (long builds killed at a random step):** every Coolify command — even on a `localhost` server — runs over one shared, multiplexed SSH connection. When that connection is older than 30 minutes (`SSH_MUX_MAX_AGE`), the next Coolify job to touch it runs `ssh -O exit`, which terminates the master **and any in-flight deployment**, so the build dies with `Command execution failed (exit code 255)` and BuildKit reports `context canceled` — typically during the long, silent final `exporting to image` phase ([coollabsio/coolify#10853](https://github.com/coollabsio/coolify/issues/10853)). The Dockerfile is fine; the fix is on the Coolify host: add `SSH_MUX_MAX_AGE=86400` to `/data/coolify/.env` (and, if a build's downloads exceed an hour, `SSH_COMMAND_TIMEOUT=7200`) and restart the Coolify container. That shrinks the kill window from every 30 minutes to once a day. Re-deploy after restarting — Docker reuses the layers from the failed build, so the retry is fast.

---

## 📦 Python Usage

Import the `tradingagents` module and initialize a `TradingAgentsGraph()` object. The `.propagate()` function returns a decision:

```python
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

ta = TradingAgentsGraph(debug=True, config=DEFAULT_CONFIG.copy())

# forward propagate
_, decision = ta.propagate("NVDA", "2026-01-15")
print(decision)
```

Adjust the default configuration to set your own choice of LLMs, debate rounds, etc.:

```python
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

config = DEFAULT_CONFIG.copy()
config["llm_provider"] = "openai"          # e.g. openai, google, anthropic, deepseek, groq, ollama
config["deep_think_llm"] = "gpt-5.5"       # Model for complex reasoning
config["quick_think_llm"] = "gpt-5.4-mini" # Model for quick tasks
config["max_debate_rounds"] = 2

ta = TradingAgentsGraph(debug=True, config=config)
_, decision = ta.propagate("NVDA", "2026-01-15")
print(decision)
```

See `tradingagents/default_config.py` for all configuration options.

---

## 💾 Persistence and Recovery

### Decision log

Each completed run appends its decision to `~/.tradingagents/memory/trading_memory.md`. On the next run for the same ticker, TradingAgents fetches the realised return, generates a reflection, and injects recent decisions into the Portfolio Manager prompt. Cross-ticker "lessons learned" are ranked by relevance to the current ticker's own history (TF-IDF over the log's own text — no extra model, no extra service), not just recency, so a lesson about a thematically similar name outranks an unrelated one that merely resolved more recently.

Override the path with `TRADINGAGENTS_MEMORY_LOG_PATH`.

### Checkpoint resume

Checkpoint resume is opt-in via `--checkpoint` (the web UI and worker always enable it). LangGraph saves state after each node so a crashed or interrupted run resumes from the last successful step — including under a **different** per-role provider than the run that failed, since the checkpoint doesn't depend on which model produced it.

```bash
tradingagents analyze --checkpoint           # enable for this run
tradingagents analyze --clear-checkpoints    # reset before running
tradingagents list-runs                      # show runs parked after a quota/rate-limit error
```

### Parked runs

A run that hits a provider quota/rate-limit error (or exceeds an optional `TRADINGAGENTS_TOKEN_BUDGET_PER_RUN`) **parks** instead of crashing: the checkpoint stays intact and the failure is recorded so you can discover and resume it. Resuming is just re-running the same ticker+date — optionally with a different provider set for the role that failed (`tradingagents list-runs` shows which role/provider hit the limit). The web UI exposes the same thing at `GET /api/runs` and `POST /api/runs/clear` (to abandon a parked run instead of resuming it).

---

## 🔁 Reproducibility

TradingAgents is LLM-driven, so two runs of the same ticker and date can differ. This is expected for a research tool built on language models. Variation comes from:

- **Language model sampling** — non-deterministic, especially for reasoning models.
- **Live data** — news, StockTwits, and Reddit return different content over time.

To reduce variation, lower the sampling temperature (`temperature` in config, or `TRADINGAGENTS_TEMPERATURE` in `.env`). For tighter reproducibility, use a non-reasoning model.

Backtest results are not guaranteed to match any published figure. Treat the framework as a research scaffold for studying multi-agent analysis.

---

## ⚡ Trade Execution

> **This framework produces research and trade proposals. Whether it executes them against a real broker is controlled entirely by the settings below, which default to safe (paper trading, off).** Read this whole section before setting `TRADINGAGENTS_LIVE_TRADING_ENABLED=true`.

### Paper-first gate

Every execution platform — Alpaca, CCXT/crypto exchanges — resolves to that platform's **paper/sandbox mode** regardless of which one you configure, unless `TRADINGAGENTS_LIVE_TRADING_ENABLED=true` is set explicitly. There is no other way to reach a live broker. Paper-trading state (cash, positions, order history) persists to SQLite under `~/.tradingagents/execution/`, so it survives restarts and redeploys — it's a real track record, not a reset-on-restart simulation.

A **kill switch** halts order submission even when live trading is enabled: drop a file named `LIVE_TRADING_KILL_SWITCH` in the data directory (`~/.tradingagents/` locally, the `tradingagents_data` volume in Docker). No redeploy or config change needed — the next tick checks for the file's presence before placing any order.

```bash
# Install execution dependencies (not part of the base install)
pip install ".[exec]"          # Alpaca + CCXT

export EXECUTION_PLATFORM=paper           # paper (default) | alpaca | ccxt/binance/coinbase/kucoin/bybit
export ALPACA_API_KEY=...
export ALPACA_SECRET_KEY=...
export CCXT_EXCHANGE=binance
export CCXT_API_KEY=...
export CCXT_SECRET_KEY=...

# Only once you've reviewed a real paper-trading track record:
export TRADINGAGENTS_LIVE_TRADING_ENABLED=true
```

IBKR is deliberately unsupported for live/paper routing here — it needs a persistent TWS/IB Gateway process alongside the container, out of scope for this deployment shape.

### Position sizing and risk guards

Sizing is a fixed, non-LLM lookup on the Portfolio Manager's 5-tier rating (`Buy`/`Overweight`/`Hold`/`Underweight`/`Sell`) — a target portfolio weight per tier, rebalanced against the current position. The model's own free-text sizing language (e.g. "5% of portfolio" in a trader proposal) is never parsed for the actual order — the LLM is never the last thing before an order is submitted. `RiskGuards` checks every order before it's placed: a symbol blacklist, a max-open-positions cap, a max-position-size cap (BUY only — a SELL that reduces or exits an oversized position is never blocked by the cap that exists to prevent it), and a daily-drawdown circuit breaker that halts all new trades.

Every order carries a deterministic `client_order_id` derived from the run's checkpoint thread — a resumed run or a retried worker tick that arrives at the same decision reuses the same ID and is recognized as already-placed rather than submitted twice.

### Scheduled worker

`app/worker.py` runs the pipeline against a watchlist on a schedule and bridges completed decisions to the configured execution platform:

```bash
pip install ".[worker]"                                 # apscheduler + exchange_calendars
export TRADINGAGENTS_WATCHLIST=AAPL,MSFT,BTC-USD
tradingagents-worker --once                              # run one tick now and exit
tradingagents-worker                                      # start the scheduler (default: weekdays 21:00 UTC)
```

It skips non-trading days on the configured market calendar (`TRADINGAGENTS_WORKER_CALENDAR`, default `XNYS`/NYSE — falls back to a plain weekday check without `exchange_calendars` installed, which already covers a crypto-only watchlist). One ticker's failure doesn't stop the rest of the watchlist. In Docker/Coolify it runs as its own `worker` service (`docker-compose.coolify.yml`), sharing the same data volume as the web service so checkpoints, the paper portfolio, and the order ledger stay consistent between them.

### Optional: AI-Trader signal sync

Completed decisions can optionally be posted to an [AI-Trader](https://github.com/HKUDS/AI-Trader) instance's leaderboard/copy-trade surface via its REST API (`TRADINGAGENTS_AI_TRADER_BASE_URL` + `TRADINGAGENTS_AI_TRADER_AGENT_TOKEN`, register an agent first via that service's `/api/claw/agents/selfRegister`). This is a thin REST client only — no AI-Trader code is vendored into this repo (its `service/README.md` describes that directory as proprietary, and it has no LICENSE file). Unconfigured by default; entirely optional.

---

## 🤝 Contributing

Contributions are welcome: bug fixes, documentation, and feature ideas. Past contributions are credited per release in [`CHANGELOG.md`](CHANGELOG.md).

---

## 📄 License

See the [LICENSE](LICENSE) file.