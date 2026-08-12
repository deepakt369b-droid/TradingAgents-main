"""Persistent credential & configuration store for TradingAgents.

Stores API keys and production settings (Cloudflare AI Gateway, brokerage
execution) inside the project so the browser configuration page can save
and apply them without relying on Coolify environment variables.

The store is a JSON file. Keys are stored in plaintext (same as .env), so
the file should be kept out of version control and protected by the OS.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Default location: inside the project under config/credentials.json
_PROJECT_DIR = Path(__file__).resolve().parent.parent
_DEFAULT_STORE_PATH = _PROJECT_DIR / "config" / "credentials.json"

# Fallback location when the project dir is not writable (e.g. read-only
# container image). Mirrors the existing ~/.tradingagents convention.
_FALLBACK_STORE_PATH = Path(
    os.environ.get("TRADINGAGENTS_HOME", os.path.join(os.path.expanduser("~"), ".tradingagents"))
) / "credentials.json"

# Mapping of store keys -> env var names for LLM API keys.
# Mirrors tradingagents/llm_clients/api_key_env.PROVIDER_API_KEY_ENV.
LLM_KEY_ENV_MAP = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "xai": "XAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "qwen": "DASHSCOPE_API_KEY",
    "qwen-cn": "DASHSCOPE_CN_API_KEY",
    "glm": "ZHIPU_API_KEY",
    "glm-cn": "ZHIPU_CN_API_KEY",
    "minimax": "MINIMAX_API_KEY",
    "minimax-cn": "MINIMAX_CN_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "kimi": "MOONSHOT_API_KEY",
    "groq": "GROQ_API_KEY",
    "nvidia": "NVIDIA_API_KEY",
    "together": "TOGETHER_API_KEY",
    "fireworks": "FIREWORKS_API_KEY",
    "cerebras": "CEREBRAS_API_KEY",
    "sambanova": "SAMBANOVA_API_KEY",
    "perplexity": "PERPLEXITY_API_KEY",
    "cohere": "COHERE_API_KEY",
    "ai21": "AI21_API_KEY",
    "openai_compatible": "OPENAI_COMPATIBLE_API_KEY",
}

# Mapping of store keys -> env var names for production settings.
PROD_ENV_MAP = {
    # Cloudflare AI Gateway
    "cf_account_id": "CLOUDFLARE_ACCOUNT_ID",
    "cf_gateway_id": "CLOUDFLARE_GATEWAY_ID",
    "cf_byok_alias": "CLOUDFLARE_BYOK_ALIAS",
    "cf_gateway_url": "CLOUDFLARE_AI_GATEWAY_URL",
    "cf_gateway_token": "CLOUDFLARE_AI_GATEWAY_TOKEN",
    # Execution
    "execution_platform": "EXECUTION_PLATFORM",
    "alpaca_api_key": "ALPACA_API_KEY",
    "alpaca_secret_key": "ALPACA_SECRET_KEY",
    "ibkr_host": "IBKR_HOST",
    "ibkr_port": "IBKR_PORT",
    "ccxt_exchange": "CCXT_EXCHANGE",
    "ccxt_api_key": "CCXT_API_KEY",
    "ccxt_secret_key": "CCXT_SECRET_KEY",
}


def _store_path() -> Path:
    """Return the writable store path, preferring the project directory."""
    try:
        _DEFAULT_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        # Probe writability
        probe = _DEFAULT_STORE_PATH.parent / ".write_test"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        return _DEFAULT_STORE_PATH
    except OSError:
        try:
            _FALLBACK_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
            return _FALLBACK_STORE_PATH
        except OSError:
            logger.warning("No writable location for credentials store; using project dir anyway.")
            return _DEFAULT_STORE_PATH


def load_credentials() -> dict:
    """Load the full credentials/config dict from the store."""
    path = _store_path()
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read credentials store %s: %s", path, exc)
        return {}


def save_credentials(data: dict) -> None:
    """Persist the full credentials/config dict to the store."""
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_api_key(provider: str) -> str | None:
    """Return the stored API key for a provider, or None if not set.

    Checks the store first, then falls back to the environment variable.
    """
    provider = provider.lower()
    data = load_credentials()
    stored = data.get("api_keys", {}).get(provider)
    if stored:
        return stored
    env_var = LLM_KEY_ENV_MAP.get(provider)
    if env_var:
        return os.environ.get(env_var)
    return None


def set_api_key(provider: str, key: str) -> None:
    """Persist an API key for a provider to the store and environment."""
    provider = provider.lower()
    data = load_credentials()
    data.setdefault("api_keys", {})[provider] = key
    save_credentials(data)
    env_var = LLM_KEY_ENV_MAP.get(provider)
    if env_var:
        os.environ[env_var] = key


def get_configured_providers() -> dict[str, bool]:
    """Return {provider: bool} indicating which LLM keys are configured."""
    data = load_credentials()
    stored_keys = data.get("api_keys", {})
    result = {}
    for provider, env_var in LLM_KEY_ENV_MAP.items():
        if stored_keys.get(provider):
            result[provider] = True
        elif env_var and os.environ.get(env_var):
            result[provider] = True
        else:
            result[provider] = False
    return result


def apply_to_environment() -> None:
    """Load all stored keys/settings into os.environ so existing clients work."""
    data = load_credentials()
    for provider, key in data.get("api_keys", {}).items():
        env_var = LLM_KEY_ENV_MAP.get(provider)
        if env_var and key:
            os.environ[env_var] = key
    for store_key, env_var in PROD_ENV_MAP.items():
        val = data.get("production", {}).get(store_key)
        if val is not None and str(val).strip() != "":
            os.environ[env_var] = str(val).strip()


def save_production_settings(settings: dict) -> None:
    """Persist production settings (Cloudflare + brokerage) to the store."""
    data = load_credentials()
    prod = data.setdefault("production", {})
    for store_key, env_var in PROD_ENV_MAP.items():
        val = settings.get(store_key)
        if val is not None and str(val).strip() != "":
            prod[store_key] = str(val).strip()
            os.environ[env_var] = str(val).strip()
    save_credentials(data)