"""Persistent credential & configuration store for TradingAgents.

Stores API keys and production settings (Cloudflare AI Gateway, brokerage
execution) inside the project so the browser configuration page can save
and apply them without relying on Coolify environment variables.

The store is a JSON file. At rest it is encrypted with Fernet (from the
``cryptography`` package, already a pinned dependency) whenever a master key
is configured via the ``TRADINGAGENTS_CREDENTIALS_KEY`` environment variable
(e.g. a Coolify env var). The key may be any passphrase (derived with
PBKDF2-HMAC-SHA256) or a raw 32-byte urlsafe-base64 Fernet key. Without a
configured key the store falls back to plaintext JSON (legacy behavior), so
upgrading is safe -- set the env var and the next save encrypts.

Caveat: if the key is lost or changed, previously encrypted credentials can
no longer be read (they are only recoverable by restoring the key that wrote
them).
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Master-key env var for at-rest encryption of the credentials store.
_CREDENTIALS_KEY_ENV = "TRADINGAGENTS_CREDENTIALS_KEY"
# Fixed salt for passphrase derivation (public; security comes from the key).
_FERNET_SALT = b"tradingagents-credentials-v1"
# Fernet tokens always start with this base64 prefix (version byte 0x80).
_FERNET_PREFIX = "gAAAA"

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
    # Trade approval + Telegram (tradingagents/execution/approval_*.py,
    # tradingagents/notifications/).
    "require_trade_approval": "TRADINGAGENTS_REQUIRE_TRADE_APPROVAL",
    "approval_timeout_minutes": "TRADINGAGENTS_APPROVAL_TIMEOUT_MINUTES",
    "execute_from_ui": "TRADINGAGENTS_EXECUTE_FROM_UI",
    "telegram_enabled": "TELEGRAM_ENABLED",
    "telegram_bot_token": "TELEGRAM_BOT_TOKEN",
    "telegram_chat_id": "TELEGRAM_CHAT_ID",
    "telegram_allowed_chat_ids": "TELEGRAM_ALLOWED_CHAT_IDS",
    "telegram_webhook_secret": "TELEGRAM_WEBHOOK_SECRET",
    # App-wide access key (app/auth_gate.py). Settable here too, but note
    # the chicken-and-egg: this route is itself gated once a key exists, so
    # rotating the key via the browser requires already being authenticated
    # -- the first key must come from .env or a still-unauthenticated app.
    "app_access_key": "TRADINGAGENTS_APP_ACCESS_KEY",
}


def _fernet_key() -> bytes | None:
    """Return the Fernet key derived from the configured master secret."""
    secret = os.environ.get(_CREDENTIALS_KEY_ENV, "")
    if not secret:
        return None
    # Accept a raw Fernet key (32-byte urlsafe base64) directly.
    try:
        decoded = base64.urlsafe_b64decode(secret.encode("ascii") + b"==")
        if len(decoded) == 32:
            return secret.encode("ascii")
    except Exception:
        pass
    # Otherwise treat the value as a passphrase and derive a 32-byte key.
    return base64.urlsafe_b64encode(
        hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), _FERNET_SALT, 200_000, dklen=32)
    )


def _fernet():
    """Return a configured Fernet instance, or None when no master key is set."""
    key = _fernet_key()
    if key is None:
        return None
    from cryptography.fernet import Fernet
    return Fernet(key)


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
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not read credentials store %s: %s", path, exc)
        return {}

    fernet = _fernet()
    if raw.lstrip().startswith(_FERNET_PREFIX):
        if fernet is None:
            logger.warning(
                "Credentials store %s is encrypted but %s is not set; "
                "credentials are unavailable until the key is configured.",
                path, _CREDENTIALS_KEY_ENV,
            )
            return {}
        try:
            raw = fernet.decrypt(raw.encode("utf-8")).decode("utf-8")
        except Exception as exc:
            logger.warning(
                "Could not decrypt credentials store %s (wrong key?): %s", path, exc
            )
            return {}

    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not parse credentials store %s: %s", path, exc)
        return {}


def save_credentials(data: dict) -> None:
    """Persist the full credentials/config dict to the store."""
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, ensure_ascii=False)
    fernet = _fernet()
    if fernet is not None:
        payload = fernet.encrypt(payload.encode("utf-8")).decode("utf-8")
    else:
        logger.info(
            "%s not set -- credentials store written in plaintext (set it to encrypt at rest).",
            _CREDENTIALS_KEY_ENV,
        )
    with open(path, "w", encoding="utf-8") as f:
        f.write(payload)


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
        if stored_keys.get(provider) or (env_var and os.environ.get(env_var)):
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

    # DEFAULT_CONFIG (tradingagents/default_config.py) is a module-level dict
    # computed once from os.environ at import time -- routes like
    # /api/telegram/test read it directly, so without this, settings saved
    # here (e.g. Telegram bot token/chat id) silently would not take effect
    # until the whole app process restarts, despite the UI's "saved to
    # runtime" message.
    from tradingagents.default_config import DEFAULT_CONFIG, _apply_env_overrides
    _apply_env_overrides(DEFAULT_CONFIG)
