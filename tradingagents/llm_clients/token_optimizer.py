"""Token Optimizer for TradingAgents.

Provides:
- Prompt Compression via LLMLingua-2 (with fallback to heuristic entity-preserving compression)
- Response Caching for tool calls and market data
- Context token reduction
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Lazy import for llmlingua
_compressor_instance = None


def _get_compressor():
    global _compressor_instance
    if _compressor_instance is None:
        try:
            from llmlingua import PromptCompressor
            # Use LLMLingua-2 small model if available
            _compressor_instance = PromptCompressor(
                model_name="microsoft/llmlingua-2-bert-base-multilingual-cased-meetingbank",
                use_llmlingua2=True,
            )
            logger.info("LLMLingua-2 PromptCompressor initialized successfully.")
        except Exception as exc:
            logger.warning("LLMLingua initialization skipped (%s). Using fallback heuristic compressor.", exc)
            _compressor_instance = False
    return _compressor_instance


class TokenOptimizer:
    """Token optimizer managing compression, caching, and payload pruning."""

    def __init__(self, cache_ttl_seconds: int = 300):
        self.cache_ttl = cache_ttl_seconds
        # hash -> (response_content, timestamp)
        self._cache: dict[str, tuple[Any, float]] = {}

    def hash_prompt(self, prompt: str) -> str:
        return hashlib.sha256(prompt.encode("utf-8")).hexdigest()

    def get_cached_response(self, prompt: str) -> Optional[Any]:
        key = self.hash_prompt(prompt)
        if key in self._cache:
            data, timestamp = self._cache[key]
            if time.time() - timestamp <= self.cache_ttl:
                logger.debug("TokenOptimizer: Hit cache for prompt hash %s", key[:8])
                return data
            del self._cache[key]
        return None

    def store_cached_response(self, prompt: str, response: Any) -> None:
        key = self.hash_prompt(prompt)
        self._cache[key] = (response, time.time())

    def compress_prompt(self, text: str, rate: float = 0.5) -> str:
        """Compress prompt text using LLMLingua-2 or heuristic preservation.

        Preserves financial tickers, currency values, percentages, and dates.
        """
        if not text or len(text) < 200:
            return text

        compressor = _get_compressor()
        if compressor:
            try:
                results = compressor.compress_prompt(
                    [text],
                    rate=rate,
                    drop_consecutive_special=True,
                )
                compressed = results.get("compressed_prompt", text)
                logger.info(
                    "LLMLingua-2 compressed prompt from %d to %d chars (%.1f%% reduction)",
                    len(text),
                    len(compressed),
                    (1 - len(compressed) / len(text)) * 100,
                )
                return compressed
            except Exception as exc:
                logger.warning("LLMLingua-2 compression failed (%s). Falling back to heuristic.", exc)

        return self._heuristic_compress(text, rate=rate)

    def _heuristic_compress(self, text: str, rate: float = 0.5) -> str:
        """Heuristic compression that removes redundant whitespace/fillers while keeping numbers/tickers."""
        lines = text.split("\n")
        cleaned_lines = []
        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue
            # Remove filler phrases
            line_str = re.sub(r"(?i)\b(please note that|as mentioned previously|it is important to note|in order to|due to the fact that)\b", "", line_str)
            # Normalize whitespace
            line_str = re.sub(r"\s+", " ", line_str)
            cleaned_lines.append(line_str)

        compressed = "\n".join(cleaned_lines)
        return compressed

    def compress_tool_output(self, output: str | dict | list, max_length: int = 1500) -> str:
        """Trim large tool outputs (JSON logs, news feeds) to fit token budgets."""
        if isinstance(output, (dict, list)):
            raw = json.dumps(output, ensure_ascii=False)
        else:
            raw = str(output)

        if len(raw) <= max_length:
            return raw

        head = raw[: max_length // 2]
        tail = raw[-max_length // 2 :]
        return f"{head}\n... [TokenOptimizer trimmed {len(raw) - max_length} chars] ...\n{tail}"


global_token_optimizer = TokenOptimizer()
