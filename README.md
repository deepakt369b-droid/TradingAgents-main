# TradingAgents — Multi-Agent LLM Financial Trading Framework

A multi-agent trading framework that mirrors the dynamics of real-world trading firms. Specialized LLM-powered agents — fundamental analysts, sentiment experts, technical analysts, a trader, and a risk management team — collaboratively evaluate market conditions and inform trading decisions through dynamic discussion.

> **Disclaimer:** This framework is designed for research purposes. Trading performance may vary based on many factors, including the chosen backbone language models, model temperature, trading periods, data quality, and other non-deterministic factors. It is **not** intended as financial, investment, or trading advice.

---

## ✨ Features

- **Multi-agent architecture** — Analyst team, researcher team, trader, risk management, and portfolio manager.
- **Multi-provider LLM support** — OpenAI, Google, Anthropic, xAI, DeepSeek, Qwen, GLM, MiniMax, OpenRouter, Ollama, Azure, Bedrock, and any OpenAI-compatible endpoint.
- **Browser API-key configuration** — Save LLM API keys directly from the web UI. Keys persist inside the project (`config/credentials.json`), so analysis works without setting environment variables on the host.
- **Headless web server** — Runs a FastAPI/uvicorn server on `0.0.0.0:8000`, ready for containerized deployment.
- **Coolify deployment** — See [`docs/Coolify_Deployment_Guide.pdf`](docs/Coolify_Deployment_Guide.pdf) for a step-by-step, image-rich guide to deploying on a self-hosted Coolify instance (Ubuntu VM).
- **Persistence & recovery** — Decision log and optional checkpoint resume.

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
- **`docker-compose.coolify.yml`** — maps host port `8001` → container port `8000` (Coolify itself occupies port 8000), with a `tradingagents_config` volume so browser-saved API keys persist across restarts.
- **`docs/Coolify_Deployment_Guide.pdf`** — full step-by-step deployment guide with architecture and flow diagrams.

> **Coolify 1-hour build limits:** The build uses `uv` (parallel, streams progress) and caches the dependency layer across builds. On slow network links (~80 kB/s measured on one host) the **first** build's image + PyPI downloads can approach the 1-hour queue timeout, so if the first deploy still times out, re-deploy once — Docker will reuse the layers already downloaded and the second build completes quickly. Keep the **Build Timeout** at `3600` seconds (1 hour) as it already is.

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

Each completed run appends its decision to `~/.tradingagents/memory/trading_memory.md`. On the next run for the same ticker, TradingAgents fetches the realised return, generates a reflection, and injects recent decisions into the Portfolio Manager prompt.

Override the path with `TRADINGAGENTS_MEMORY_LOG_PATH`.

### Checkpoint resume

Checkpoint resume is opt-in via `--checkpoint`. LangGraph saves state after each node so a crashed or interrupted run resumes from the last successful step.

```bash
tradingagents analyze --checkpoint           # enable for this run
tradingagents analyze --clear-checkpoints    # reset before running
```

---

## 🔁 Reproducibility

TradingAgents is LLM-driven, so two runs of the same ticker and date can differ. This is expected for a research tool built on language models. Variation comes from:

- **Language model sampling** — non-deterministic, especially for reasoning models.
- **Live data** — news, StockTwits, and Reddit return different content over time.

To reduce variation, lower the sampling temperature (`temperature` in config, or `TRADINGAGENTS_TEMPERATURE` in `.env`). For tighter reproducibility, use a non-reasoning model.

Backtest results are not guaranteed to match any published figure. Treat the framework as a research scaffold for studying multi-agent analysis.

---

## 🤝 Contributing

Contributions are welcome: bug fixes, documentation, and feature ideas. Past contributions are credited per release in [`CHANGELOG.md`](CHANGELOG.md).

---

## 📄 License

See the [LICENSE](LICENSE) file.