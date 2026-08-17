"""App-wide access-key gate.

Nothing else in this app authenticates who is allowed to view balances,
approve trades, toggle the kill switch, or overwrite saved broker/LLM
credentials -- see ``default_config.py``'s ``app_access_key`` docstring.
This module is the single place that enforces it, for both the regular
HTTP request/response cycle (via ASGI middleware in ``server.py``) and the
one route that bypasses HTTP middleware entirely (the WebSocket analysis
endpoint checks this module directly before accepting).

Deliberately not a full session/user system -- this app has exactly one
operator. The cookie carries a value *derived* from the configured key via
HMAC, not the raw key itself, so a leaked cookie doesn't hand over the key
you'd otherwise have to go rotate everywhere it's configured (a Mini App
button URL, bookmarks, .env, ...) -- invalidating a leaked cookie is just
rotating ``app_access_key`` once.
"""

from __future__ import annotations

import hashlib
import hmac

COOKIE_NAME = "ta_session"
QUERY_PARAM = "key"
COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 180  # ~6 months

# Paths that must stay reachable with no key at all:
#  - the Telegram webhook has its own secret-token header check (see
#    server.py's telegram_webhook route) -- Telegram's servers have no
#    browser cookie and cannot carry one.
#  - /login and /static are needed to render/serve the login page itself,
#    or every unauthenticated visitor would be stuck in a redirect loop.
_EXEMPT_PREFIXES = ("/api/telegram/webhook", "/login", "/static")


def _derive_token(app_access_key: str) -> str:
    return hmac.new(app_access_key.encode("utf-8"), b"ta-session-v1", hashlib.sha256).hexdigest()


def is_exempt(path: str) -> bool:
    return any(path == p or path.startswith(p + "/") for p in _EXEMPT_PREFIXES)


def is_authorized(
    app_access_key: str | None, cookie_value: str | None, query_key: str | None,
) -> tuple[bool, str | None]:
    """Check a request against the configured key.

    Returns ``(authorized, token_to_set)``. ``token_to_set`` is non-None
    only when a fresh ``?key=`` query param just validated and the caller
    should set a cookie so future requests don't need the query param
    again.
    """
    if not app_access_key:
        return True, None  # gate disabled entirely -- historical default

    expected = _derive_token(app_access_key)
    if cookie_value and hmac.compare_digest(cookie_value, expected):
        return True, None
    if query_key and hmac.compare_digest(query_key, app_access_key):
        return True, expected
    return False, None
