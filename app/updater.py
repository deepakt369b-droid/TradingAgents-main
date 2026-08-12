"""GitHub-based auto-update checker for TradingAgents Desktop.

Queries the GitHub Releases API for the latest version tag and compares it
against the currently installed version.  Caches the result for one hour to
avoid rate-limit issues, and silently returns "no update" on network errors
so the app never blocks on startup.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# GitHub repository to check
REPO_OWNER = "TauricResearch"
REPO_NAME = "TradingAgents"
RELEASES_URL = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/latest"

# Cache directory
_TRADINGAGENTS_HOME = Path(os.path.expanduser("~")) / ".tradingagents"
_CACHE_DIR = _TRADINGAGENTS_HOME / "cache"
_CACHE_FILE = _CACHE_DIR / "update_check.json"

# Check at most once per hour
CACHE_TTL_SECONDS = 3600


def _get_current_version() -> str:
    """Read the installed version from the package."""
    try:
        from app import __version__
        return __version__
    except ImportError:
        return "0.3.0"


def _parse_semver(version: str) -> tuple[int, ...]:
    """Parse a version string like '0.3.0' or 'v0.3.0' into a comparable tuple."""
    cleaned = re.sub(r"^v", "", version.strip())
    parts = []
    for segment in cleaned.split("."):
        try:
            parts.append(int(segment))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def _read_cache() -> dict | None:
    """Read cached update-check result if still fresh."""
    try:
        if not _CACHE_FILE.exists():
            return None
        data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        if time.time() - data.get("timestamp", 0) < CACHE_TTL_SECONDS:
            return data
    except Exception:
        pass
    return None


def _write_cache(data: dict) -> None:
    """Write update-check result to cache."""
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        data["timestamp"] = time.time()
        _CACHE_FILE.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        pass


def check_for_update() -> dict:
    """Check GitHub Releases for a newer version.

    Returns a dict with keys:
      - current_version: str
      - latest_version: str
      - update_available: bool
      - download_url: str (browser URL for the release page)
      - release_notes: str (first 500 chars of release body)

    This function is safe to call from any thread and will never raise.
    """
    current = _get_current_version()
    result = {
        "current_version": current,
        "latest_version": current,
        "update_available": False,
        "download_url": "",
        "release_notes": "",
    }

    # Check cache first
    cached = _read_cache()
    if cached and cached.get("current_version") == current:
        cached.pop("timestamp", None)
        return cached

    # Fetch from GitHub
    try:
        import requests
        resp = requests.get(
            RELEASES_URL,
            headers={"Accept": "application/vnd.github.v3+json"},
            timeout=5,
        )
        if resp.status_code != 200:
            _write_cache(result)
            return result

        data = resp.json()
        tag = data.get("tag_name", current)
        latest = tag

        if _parse_semver(latest) > _parse_semver(current):
            result["latest_version"] = latest
            result["update_available"] = True
            result["download_url"] = data.get("html_url", "")
            body = data.get("body", "") or ""
            result["release_notes"] = body[:500]
        else:
            result["latest_version"] = latest

    except Exception as exc:
        logger.debug("Update check failed (non-fatal): %s", exc)

    _write_cache(result)
    return result
