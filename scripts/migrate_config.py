"""Script to migrate and enrich existing .env configuration for production features."""

from __future__ import annotations

import os
from pathlib import Path
from dotenv import find_dotenv

NEW_ENV_TEMPLATE = """
# =====================================================================
# TradingAgents Production Configuration
# =====================================================================

# Cloudflare AI Gateway Integration (Optional)
# Enable BYOK key rotation and unified failover proxy
# CLOUDFLARE_ACCOUNT_ID=
# CLOUDFLARE_GATEWAY_ID=
# CLOUDFLARE_BYOK_ALIAS=default
# CLOUDFLARE_AI_GATEWAY_URL=
# CLOUDFLARE_AI_GATEWAY_TOKEN=

# API Key Rotation Pools (Comma-separated keys supported for multi-key rotation)
# OPENAI_API_KEY=key1,key2
# ANTHROPIC_API_KEY=key1,key2
# GOOGLE_API_KEY=key1,key2

# Extended LLM Providers
# TOGETHER_API_KEY=
# FIREWORKS_API_KEY=
# CEREBRAS_API_KEY=
# SAMBANOVA_API_KEY=
# PERPLEXITY_API_KEY=
# COHERE_API_KEY=
# AI21_API_KEY=

# Commission-Free Trade Execution Platforms
# 1. US Equities (Alpaca)
# ALPACA_API_KEY=
# ALPACA_SECRET_KEY=

# 2. Global Markets & FX (Interactive Brokers)
# IBKR_HOST=127.0.0.1
# IBKR_PORT=7497
# IBKR_CLIENT_ID=1

# 3. Crypto (CCXT: Binance, Coinbase, KuCoin, Bybit)
# CCXT_EXCHANGE=binance
# CCXT_API_KEY=
# CCXT_SECRET_KEY=
"""


def main():
    env_file = find_dotenv() or ".env"
    env_path = Path(env_file)

    print(f"Checking configuration at: {env_path.resolve()}")
    if not env_path.exists():
        print(f"Creating new production .env template at {env_path}")
        env_path.write_text(NEW_ENV_TEMPLATE.strip() + "\n", encoding="utf-8")
        return

    content = env_path.read_text(encoding="utf-8")
    added = False
    with open(env_path, "a", encoding="utf-8") as f:
        if "CLOUDFLARE_ACCOUNT_ID" not in content:
            f.write("\n" + NEW_ENV_TEMPLATE.strip() + "\n")
            added = True

    if added:
        print("Updated .env with production parameters (Cloudflare AI Gateway, Multi-Key Pool, Trade Execution).")
    else:
        print(".env already contains production parameters.")


if __name__ == "__main__":
    main()
