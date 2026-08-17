"""FastAPI backend for TradingAgents Desktop.

Serves the web UI, provides REST endpoints for configuration and key validation,
and a WebSocket endpoint that streams analysis progress in real time.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger(__name__)

# Resolve paths
_APP_DIR = Path(__file__).parent
_STATIC_DIR = _APP_DIR / "static"

# Global lock: one analysis at a time
_analysis_lock = threading.Lock()


def create_app() -> FastAPI:
    """Factory that builds the FastAPI application."""

    # Load any persisted credentials/settings into the environment so the
    # existing LLM clients and execution brokers pick them up automatically.
    try:
        from app.config_store import apply_to_environment
        apply_to_environment()
    except Exception as exc:
        logger.warning("Could not apply stored credentials: %s", exc)

    app = FastAPI(title="TradingAgents Desktop", version="0.3.1")

    # ---------- Access Key Gate ----------
    # Runs before every other route. See app/auth_gate.py's docstring for
    # why this exists at all: without it, every route here -- including
    # ones that overwrite saved broker/LLM credentials, approve trades, and
    # toggle the kill switch -- is reachable by anyone with the URL.
    # Disabled entirely (as before this existed) when app_access_key is
    # unset, so a purely local/desktop install is unaffected.
    @app.middleware("http")
    async def _access_key_gate(request: Request, call_next):
        from app.auth_gate import COOKIE_NAME, QUERY_PARAM, is_authorized, is_exempt
        from tradingagents.default_config import DEFAULT_CONFIG

        if is_exempt(request.url.path):
            return await call_next(request)

        app_access_key = DEFAULT_CONFIG.get("app_access_key")
        cookie_value = request.cookies.get(COOKIE_NAME)
        query_key = request.query_params.get(QUERY_PARAM)
        authorized, token_to_set = is_authorized(app_access_key, cookie_value, query_key)

        if not authorized:
            if "text/html" in request.headers.get("accept", ""):
                target = "/login?error=1" if query_key else "/login"
                return RedirectResponse(url=target, status_code=303)
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)

        response = await call_next(request)
        if token_to_set:
            from app.auth_gate import COOKIE_MAX_AGE_SECONDS
            response.set_cookie(
                COOKIE_NAME, token_to_set, max_age=COOKIE_MAX_AGE_SECONDS,
                httponly=True, samesite="lax", secure=request.url.scheme == "https",
            )
        return response

    @app.get("/login")
    async def login_page():
        return FileResponse(str(_STATIC_DIR / "login.html"))

    # ---------- Approval Resolver (background) ----------
    # Runs resolve_pending() on the same short interval as app/worker.py's
    # own job, so an Approve tap reaches the broker promptly even when this
    # server is run standalone (desktop app, or a Coolify deployment without
    # the separate `worker` compose service). apscheduler is an optional
    # dependency (the `worker` extra) -- its absence degrades gracefully:
    # approvals still resolve whenever the worker process IS running, they
    # just won't resolve from the server process alone.
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.interval import IntervalTrigger

        def _resolve_pending_job() -> None:
            from tradingagents.default_config import DEFAULT_CONFIG
            from tradingagents.execution import resolve_pending
            try:
                resolve_pending(DEFAULT_CONFIG)
            except Exception:
                logger.exception("Background approval resolver tick failed.")

        _scheduler = BackgroundScheduler(timezone="UTC")
        _scheduler.add_job(
            _resolve_pending_job, IntervalTrigger(seconds=30),
            id="approval_resolver", misfire_grace_time=30,
        )
        _scheduler.start()
        app.state.approval_scheduler = _scheduler

        @app.on_event("shutdown")
        def _stop_approval_scheduler() -> None:
            _scheduler.shutdown(wait=False)
    except ImportError:
        logger.info("apscheduler not installed; background approval resolver disabled for this process.")

    # ---------- Static Files ----------
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # ---------- Root ----------
    @app.get("/")
    async def root():
        return FileResponse(str(_STATIC_DIR / "index.html"))

    # ---------- Config Endpoint ----------
    @app.get("/api/config")
    async def get_config():
        """Return available LLM providers, model options, and defaults."""
        try:
            from tradingagents.llm_clients.model_catalog import get_model_options
            from tradingagents.default_config import DEFAULT_CONFIG

            # Build model catalog per provider
            providers = [
                "openai", "google", "anthropic", "xai",
                "deepseek", "kimi", "groq", "nvidia", "ollama", "openrouter", "lm_studio", "openai_compatible",
            ]
            models = {}
            for p in providers:
                try:
                    # get_model_options(provider, mode) returns list[(label, value)]
                    deep_opts = get_model_options(p, "deep")
                    quick_opts = get_model_options(p, "quick")
                    models[p] = {
                        "deep": [val for _label, val in deep_opts if val != "custom"],
                        "quick": [val for _label, val in quick_opts if val != "custom"],
                    }
                except Exception:
                    models[p] = {"deep": [], "quick": []}

            # Check which API keys are configured (not the values!)
            from app.config_store import get_configured_providers
            key_status = get_configured_providers()
            # Ensure providers without a key requirement (e.g. ollama) show as ready
            from tradingagents.llm_clients.api_key_env import get_api_key_env
            for p in providers:
                if get_api_key_env(p) is None:
                    key_status[p] = True

            # Production settings status
            cf_status = {
                "configured": bool(os.environ.get("CLOUDFLARE_ACCOUNT_ID") or os.environ.get("CLOUDFLARE_AI_GATEWAY_URL")),
                "account_id": os.environ.get("CLOUDFLARE_ACCOUNT_ID", ""),
                "gateway_id": os.environ.get("CLOUDFLARE_GATEWAY_ID", ""),
                "byok_alias": os.environ.get("CLOUDFLARE_BYOK_ALIAS", "default"),
                "gateway_url": os.environ.get("CLOUDFLARE_AI_GATEWAY_URL", ""),
            }

            exec_status = {
                "platform": os.environ.get("EXECUTION_PLATFORM", "paper"),
                "alpaca_key_set": bool(os.environ.get("ALPACA_API_KEY")),
                "ibkr_host": os.environ.get("IBKR_HOST", "127.0.0.1"),
                "ibkr_port": os.environ.get("IBKR_PORT", "7497"),
                "ccxt_exchange": os.environ.get("CCXT_EXCHANGE", "binance"),
                "ccxt_key_set": bool(os.environ.get("CCXT_API_KEY")),
            }

            # Default API base URL per provider, so the UI can prefill the
            # endpoint field. Single source of truth is the OpenAI-compatible
            # provider registry; native providers get their official endpoints.
            base_urls = {}
            try:
                from tradingagents.llm_clients.openai_client import OPENAI_COMPATIBLE_PROVIDERS
                native_defaults = {
                    "openai": "https://api.openai.com/v1",
                    "anthropic": "https://api.anthropic.com",
                    "google": "https://generativelanguage.googleapis.com",
                }
                for p in providers:
                    spec = OPENAI_COMPATIBLE_PROVIDERS.get(p)
                    if spec is not None and spec.base_url:
                        base_urls[p] = spec.base_url
                    elif p in native_defaults:
                        base_urls[p] = native_defaults[p]
                    else:
                        base_urls[p] = ""
            except Exception:
                logger.warning("Could not resolve provider base URLs", exc_info=True)

            return {
                "models": models,
                "key_status": key_status,
                "cloudflare_status": cf_status,
                "execution_status": exec_status,
                "base_urls": base_urls,
                "defaults": {
                    "provider": DEFAULT_CONFIG.get("llm_provider", "openai"),
                    "deep_model": DEFAULT_CONFIG.get("deep_think_llm", "gpt-5.5"),
                    "quick_model": DEFAULT_CONFIG.get("quick_think_llm", "gpt-5.4-mini"),
                    # None unless overridden -- the UI shows these as "same as
                    # provider above" until the user opts into a split.
                    "deep_provider": DEFAULT_CONFIG.get("deep_think_provider"),
                    "quick_provider": DEFAULT_CONFIG.get("quick_think_provider"),
                    "language": DEFAULT_CONFIG.get("output_language", "English"),
                },
            }
        except Exception as exc:
            logger.warning("Config endpoint error: %s", exc)
            return JSONResponse({"error": str(exc)}, status_code=500)

    # ---------- Validate Key ----------
    @app.post("/api/validate-key")
    async def validate_key(body: dict):
        """Test whether an API key is valid for a given provider."""
        provider = body.get("provider", "")
        key = body.get("key", "")

        if not key:
            return {"valid": False, "message": "No key provided"}

        # Set the key in environment temporarily for validation
        try:
            from tradingagents.llm_clients.api_key_env import get_api_key_env
            env_var = get_api_key_env(provider)
            if env_var:
                os.environ[env_var] = key
                return {"valid": True, "message": "Key set successfully"}
            return {"valid": True, "message": "No key required for this provider"}
        except Exception as exc:
            return {"valid": False, "message": str(exc)}

    # ---------- Fetch Models ----------
    @app.post("/api/fetch-models")
    def fetch_models(body: dict):
        """Fetch available models using the provided API key and provider."""
        provider = body.get("provider", "").lower()
        key = body.get("key", "")
        base_url = body.get("base_url", "")

        if not key and provider not in ["ollama", "lm_studio", "openai_compatible"]:
            return {"valid": False, "message": "No key provided"}

        import requests
        try:
            # Simple validation + fetch using requests
            # Assuming OpenAI compatible /v1/models endpoint for most providers
            headers = {"Authorization": f"Bearer {key}"}
            url = ""
            
            if provider == "openai":
                url = "https://api.openai.com/v1/models"
            elif provider == "anthropic":
                # Anthropic now supports /v1/models
                url = "https://api.anthropic.com/v1/models"
                headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
            elif provider == "google":
                url = f"https://generativelanguage.googleapis.com/v1beta/models?key={key}"
                headers = {}
            elif provider == "xai":
                url = "https://api.x.ai/v1/models"
            elif provider == "deepseek":
                url = "https://api.deepseek.com/models"
            elif provider == "groq":
                url = "https://api.groq.com/openai/v1/models"
            elif provider == "ollama":
                url = f"{base_url.rstrip('/') if base_url else 'http://localhost:11434'}/api/tags"
                headers = {}
            elif provider in ["lm_studio", "openai_compatible", "openrouter", "nvidia"]:
                if provider == "nvidia" and not base_url:
                    base_url = "https://integrate.api.nvidia.com/v1"
                url = f"{base_url.rstrip('/')}/models"
                if not base_url:
                    return {"valid": False, "message": "Base URL required for this provider"}
            else:
                return {"valid": True, "message": "Valid key (model fetching not supported for this provider)", "models": []}

            resp = requests.get(url, headers=headers, timeout=10.0)
                
            if resp.status_code == 200:
                data = resp.json()
                models = []
                if provider == "ollama":
                    models = [m.get("name") for m in data.get("models", [])]
                elif provider == "google":
                    models = [m.get("name", "").replace("models/", "") for m in data.get("models", [])]
                else:
                    models = [m.get("id") for m in data.get("data", [])]
                    
                # Sort alphabetically
                models.sort()
                
                return {"valid": True, "models": models, "message": "Success"}
            else:
                return {"valid": False, "message": f"API error: {resp.status_code} - {resp.text}"}
                
        except Exception as exc:
            return {"valid": False, "message": f"Connection error: {str(exc)}"}

    # ---------- Save Key ----------
    @app.post("/api/save-key")
    async def save_key(body: dict):
        """Persist an API key to the project config store and environment."""
        provider = body.get("provider", "")
        key = body.get("key", "")

        if not provider or not key:
            return {"success": False, "message": "Provider and key are required"}

        try:
            from app.config_store import set_api_key
            set_api_key(provider, key)
            return {"success": True, "message": f"API key for '{provider}' saved to project config."}
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    # ---------- Save Production Settings (Cloudflare & Execution Brokers) ----------
    @app.post("/api/save-production-config")
    async def save_production_config(body: dict):
        """Persist Cloudflare AI Gateway and Execution Broker configuration to the project store."""
        try:
            from app.config_store import save_production_settings
            save_production_settings(body)
            return {
                "success": True,
                "message": "Successfully saved configuration parameters to project config & runtime!",
            }
        except Exception as exc:
            logger.error("Error saving production config: %s", exc)
            return JSONResponse({"success": False, "message": str(exc)}, status_code=500)

    # ---------- Parked Runs ----------
    @app.get("/api/runs")
    async def list_runs(status: str = "parked"):
        """List runs parked after a quota/rate-limit failure (or resolved ones).

        A parked run's LangGraph checkpoint is intact -- resubmit the same
        ticker+date via /ws/analysis (optionally with a different per-role
        provider) to resume it from the last completed node rather than
        starting over.
        """
        try:
            from tradingagents.default_config import DEFAULT_CONFIG
            from tradingagents.graph import run_registry
            runs = run_registry.list_parked_runs(DEFAULT_CONFIG["data_cache_dir"], status=status)
            return {"runs": runs}
        except Exception as exc:
            logger.warning("List runs error: %s", exc)
            return JSONResponse({"error": str(exc)}, status_code=500)

    @app.post("/api/runs/clear")
    async def clear_run(body: dict):
        """Abandon a parked run: clear its checkpoint and mark it resolved.

        Use this instead of resuming when the parked run should just start
        over from scratch next time (equivalent to the CLI's
        --clear-checkpoints, scoped to one ticker+date).
        """
        ticker = body.get("ticker", "")
        trade_date = body.get("trade_date", "")
        signature = body.get("signature", "")
        if not ticker or not trade_date:
            return JSONResponse(
                {"success": False, "message": "ticker and trade_date are required"}, status_code=400
            )
        try:
            from tradingagents.default_config import DEFAULT_CONFIG
            from tradingagents.graph import run_registry
            from tradingagents.graph.checkpointer import clear_checkpoint
            data_dir = DEFAULT_CONFIG["data_cache_dir"]
            clear_checkpoint(data_dir, ticker, trade_date, signature)
            run_registry.mark_run_resolved(data_dir, ticker, trade_date, signature, status="cleared")
            return {"success": True}
        except Exception as exc:
            logger.warning("Clear run error: %s", exc)
            return JSONResponse({"success": False, "message": str(exc)}, status_code=500)

    # ---------- Update Check ----------
    @app.get("/api/update-check")
    async def update_check():
        """Check for new releases on GitHub."""
        try:
            from app.updater import check_for_update
            result = check_for_update()
            return result
        except Exception as exc:
            return {
                "current_version": "0.3.1",
                "latest_version": "0.3.1",
                "update_available": False,
                "download_url": "",
                "release_notes": "",
            }

    # ---------- Find CLIs ----------
    @app.get("/api/find-clis")
    async def find_clis():
        """Detect installed CLI tools and their default model per the model catalog."""
        import shutil

        from app.cli_runner import resolve_default_model
        tools_to_check = ["claude", "codex", "kimi", "freebuff", "gemini", "kimchi", "opencode"]
        tools = {}
        models = {}
        for tool in tools_to_check:
            # shutil.which searches the PATH and returns the absolute path if found
            tools[tool] = shutil.which(tool)
            resolved = resolve_default_model(tool)
            if resolved:
                models[tool] = resolved
        return {"tools": tools, "models": models}

    # ---------- CLI Agent OAuth Login (fallback when no API key) ----------
    @app.post("/api/cli-login")
    async def cli_login(body: dict):
        """Start an OAuth login for a CLI agent (claude, codex, opencode, ...).

        Runs the agent's login command inside the container, captures the
        authorization URL printed by the CLI, and returns it so the browser
        UI can open it. The login process keeps running in the background;
        poll /api/cli-login-status until it reports done.
        """
        tool = (body.get("tool") or "").strip().lower()
        if not tool:
            return {"success": False, "error": "tool is required"}
        from app.cli_auth import start_login
        result = await asyncio.to_thread(start_login, tool)
        result.setdefault("tool", tool)
        return result

    @app.get("/api/cli-login-status")
    async def cli_login_status(tool: str = ""):
        """Return the state of a running CLI agent login for a tool."""
        from app.cli_auth import login_status
        return login_status(tool.strip().lower())

    # ---------- Telegram ----------
    @app.post("/api/telegram/webhook")
    async def telegram_webhook(request: Request):
        """Receive Telegram Bot API updates (button taps, commands).

        Guarded by the ``X-Telegram-Bot-Api-Secret-Token`` header: Telegram
        echoes back whatever ``secret_token`` was passed to ``setWebhook`` on
        every request, so a mismatch means the request didn't originate from
        our own webhook registration. A configured-but-missing/mismatched
        header is rejected outright; an unconfigured secret accepts anything
        (documented in .env.example as required for production use).
        """
        from tradingagents.default_config import DEFAULT_CONFIG
        from tradingagents.execution import ApprovalStore
        from tradingagents.notifications import TelegramClient, handle_update

        config = DEFAULT_CONFIG
        expected_secret = config.get("telegram_webhook_secret")
        if expected_secret:
            got = request.headers.get("x-telegram-bot-api-secret-token")
            if got != expected_secret:
                return JSONResponse({"detail": "Forbidden"}, status_code=403)

        update = await request.json()
        client = TelegramClient(config.get("telegram_bot_token"))
        store = ApprovalStore(config["data_cache_dir"])
        await asyncio.to_thread(handle_update, update, client, store, config)
        return {"ok": True}

    @app.post("/api/telegram/test")
    async def telegram_test():
        """Send a test message to the configured chat, from the config screen."""
        from tradingagents.default_config import DEFAULT_CONFIG
        from tradingagents.notifications import TelegramClient

        config = DEFAULT_CONFIG
        client = TelegramClient(config.get("telegram_bot_token"))
        if not client.is_configured or not config.get("telegram_chat_id"):
            return JSONResponse(
                {"success": False, "message": "Telegram bot token or chat id not configured."},
                status_code=400,
            )
        resp = await asyncio.to_thread(
            client.send_message, config["telegram_chat_id"],
            "✅ TradingAgents Telegram test message.",
        )
        ok = bool(resp and resp.get("ok"))
        return {"success": ok, "message": "Sent." if ok else "Failed to send -- check token/chat id."}

    # ---------- Trade Approvals ----------
    @app.get("/api/approvals")
    async def list_approvals():
        """Pending proposals plus recent decided/executed ones, for the
        Trading view's approval queue."""
        from tradingagents.default_config import DEFAULT_CONFIG
        from tradingagents.execution import ApprovalStore
        store = ApprovalStore(DEFAULT_CONFIG["data_cache_dir"])
        return {"pending": store.list_pending(), "recent": store.list_recent()}

    @app.post("/api/approvals/{approval_id}/decide")
    async def decide_approval(approval_id: str, body: dict):
        """Approve/reject from the browser -- same store, same conditional
        transitions as the Telegram callback handler, so a decision made in
        either place strips the other's buttons and can't be double-acted."""
        from tradingagents.default_config import DEFAULT_CONFIG
        from tradingagents.execution import ApprovalStore
        from tradingagents.notifications import TelegramClient, format_decision_message

        decision = (body.get("decision") or "").lower()
        if decision not in ("approve", "reject"):
            return JSONResponse(
                {"success": False, "message": "decision must be 'approve' or 'reject'"}, status_code=400,
            )
        config = DEFAULT_CONFIG
        store = ApprovalStore(config["data_cache_dir"])
        status = "approved" if decision == "approve" else "rejected"
        row = (
            store.approve(approval_id, decided_by="ui")
            if decision == "approve" else store.reject(approval_id, decided_by="ui")
        )
        if row is None:
            return JSONResponse(
                {"success": False, "message": "Already decided, or unknown approval id."}, status_code=409,
            )
        if row.get("chat_id") and row.get("message_id"):
            client = TelegramClient(config.get("telegram_bot_token"))
            await asyncio.to_thread(
                client.edit_message_text,
                str(row["chat_id"]), str(row["message_id"]),
                format_decision_message(row["proposal"], status),
            )
        return {"success": True, "approval": row}

    # ---------- Trading Status / Kill Switch ----------
    @app.get("/api/trading/status")
    async def trading_status():
        """Platform, live-vs-paper, kill-switch state, balance and positions
        for the Trading view's status panel."""
        from tradingagents.default_config import DEFAULT_CONFIG
        from tradingagents.execution import create_executor, is_kill_switch_active, is_live_trading_enabled

        config = DEFAULT_CONFIG
        platform = config.get("execution_platform", "paper")
        result = {
            "platform": platform,
            "live_trading_enabled": is_live_trading_enabled(),
            "kill_switch_active": is_kill_switch_active(config["data_cache_dir"]),
            "require_trade_approval": config.get("require_trade_approval", True),
        }
        try:
            executor = create_executor(platform, config=config)
            account = executor.get_account_balance()
            positions = executor.get_positions()
            result["account"] = account.model_dump(mode="json")
            result["positions"] = [p.model_dump(mode="json") for p in positions]
        except Exception as exc:
            result["account_error"] = str(exc)
        return result

    @app.get("/api/kill-switch")
    async def get_kill_switch():
        from tradingagents.default_config import DEFAULT_CONFIG
        from tradingagents.execution import is_kill_switch_active
        return {"active": is_kill_switch_active(DEFAULT_CONFIG["data_cache_dir"])}

    @app.post("/api/kill-switch")
    async def set_kill_switch(body: dict):
        """Toggle the file-based kill switch (see execution/live_gate.py) --
        checked immediately before every order submission, so this halts new
        trading without touching config or redeploying."""
        from tradingagents.default_config import DEFAULT_CONFIG
        from tradingagents.execution import kill_switch_path

        active = bool(body.get("active", True))
        path = kill_switch_path(DEFAULT_CONFIG["data_cache_dir"])
        if active:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("halted via web UI", encoding="utf-8")
        elif path.exists():
            path.unlink()
        return {"active": active}

    # ---------- Persisted Reports ----------
    @app.get("/api/reports")
    async def list_reports():
        """List report trees written by save_reports() -- both UI and
        worker/CLI runs, since all three call the same helper."""
        from tradingagents.default_config import DEFAULT_CONFIG
        reports_dir = Path(DEFAULT_CONFIG["results_dir"]) / "reports"
        if not reports_dir.exists():
            return {"reports": []}
        entries = []
        for child in sorted(reports_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if child.is_dir():
                entries.append({
                    "id": child.name,
                    "modified": child.stat().st_mtime,
                    "has_complete_report": (child / "complete_report.md").exists(),
                })
        return {"reports": entries}

    @app.get("/api/reports/{report_id}")
    async def get_report(report_id: str):
        """Return one report's complete_report.md. report_id is a directory
        name from /api/reports, resolved strictly under results_dir/reports
        to prevent path traversal."""
        from tradingagents.default_config import DEFAULT_CONFIG
        reports_dir = (Path(DEFAULT_CONFIG["results_dir"]) / "reports").resolve()
        report_dir = (reports_dir / report_id).resolve()
        if report_dir == reports_dir or not report_dir.is_relative_to(reports_dir):
            return JSONResponse({"error": "invalid report id"}, status_code=400)
        report_file = report_dir / "complete_report.md"
        if not report_file.exists():
            return JSONResponse({"error": "report not found"}, status_code=404)
        return {"id": report_id, "content": report_file.read_text(encoding="utf-8")}

    # ---------- WebSocket: Analysis ----------
    @app.websocket("/ws/analysis")
    async def ws_analysis(websocket: WebSocket):
        """Stream analysis progress over WebSocket."""
        await websocket.accept()

        # Access key gate. The HTTP middleware above never runs for a
        # WebSocket upgrade (Starlette dispatches it on a separate path),
        # so this endpoint -- the one that can trigger paid LLM calls and,
        # with execute=true, real trades -- needs its own check.
        from app.auth_gate import COOKIE_NAME, QUERY_PARAM, is_authorized
        from tradingagents.default_config import DEFAULT_CONFIG
        app_access_key = DEFAULT_CONFIG.get("app_access_key")
        authorized, _ = is_authorized(
            app_access_key, websocket.cookies.get(COOKIE_NAME), websocket.query_params.get(QUERY_PARAM),
        )
        if not authorized:
            await websocket.send_json({"type": "error", "detail": "Unauthorized"})
            await websocket.close()
            return

        # Check lock
        if not _analysis_lock.acquire(blocking=False):
            await websocket.send_json({
                "type": "error",
                "detail": "Analysis already in progress. Please wait.",
            })
            await websocket.close()
            return

        try:
            # Receive analysis request
            raw = await websocket.receive_text()
            request = json.loads(raw)

            # Run analysis in a thread to avoid blocking the event loop
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                _run_analysis_sync,
                websocket,
                loop,
                request,
            )

        except WebSocketDisconnect:
            logger.info("WebSocket disconnected")
        except Exception as exc:
            logger.error("WebSocket error: %s", exc, exc_info=True)
            try:
                await websocket.send_json({
                    "type": "error",
                    "detail": str(exc),
                })
            except Exception:
                pass
        finally:
            _analysis_lock.release()

    return app


def _send_ws_sync(ws: WebSocket, loop: asyncio.AbstractEventLoop, data: dict):
    """Send a JSON message to the WebSocket from a sync thread."""
    future = asyncio.run_coroutine_threadsafe(ws.send_json(data), loop)
    try:
        future.result(timeout=5)
    except Exception:
        pass


def _run_analysis_sync(
    ws: WebSocket,
    loop: asyncio.AbstractEventLoop,
    request: dict,
):
    """Execute the TradingAgents analysis pipeline synchronously.

    Streams progress updates to the WebSocket via the event loop.
    This mirrors the logic in ``cli/main.py`` but outputs JSON instead of
    Rich terminal widgets.
    """
    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.graph.checkpointer import thread_id
    from tradingagents.graph.analyst_execution import (
        AnalystWallTimeTracker,
        build_analyst_execution_plan,
        get_initial_analyst_node,
        sync_analyst_tracker_from_chunk,
    )
    from cli.stats_handler import StatsCallbackHandler

    send = lambda data: _send_ws_sync(ws, loop, data)

    # Bound here (not inside the try) so the except handler below can safely
    # check "is checkpointed_ctx None" regardless of how early the try block
    # failed -- it's only non-None once graph/ticker/analysis_date/asset_type
    # are all already bound too.
    checkpointed_ctx = None

    try:
        # Build config. "provider"/"base_url" remain the shared/legacy fields
        # (single-provider requests from older UI builds keep working
        # unchanged); "deep_provider"/"quick_provider" let the UI route each
        # role to a different provider, falling back to the shared value when
        # a role-specific one isn't sent.
        config = DEFAULT_CONFIG.copy()
        shared_provider = request.get("provider", "openai").lower()
        deep_provider = (request.get("deep_provider") or shared_provider).lower()
        quick_provider = (request.get("quick_provider") or shared_provider).lower()
        config["llm_provider"] = deep_provider
        config["deep_think_provider"] = deep_provider
        config["quick_think_provider"] = quick_provider
        config["deep_think_llm"] = request.get("deep_model", "gpt-5.5")
        config["quick_think_llm"] = request.get("quick_model", "gpt-5.4-mini")
        config["max_debate_rounds"] = request.get("depth", 1)
        config["max_risk_discuss_rounds"] = request.get("depth", 1)
        config["output_language"] = request.get("language", "English")
        # Per-run platform override for _execute_decision (falls back to
        # DEFAULT_CONFIG's execution_platform, e.g. from the Step 3 broker
        # settings, when the run didn't send one).
        if request.get("execution_platform"):
            config["execution_platform"] = request["execution_platform"]

        shared_base_url = request.get("base_url")
        deep_base_url = request.get("deep_base_url") or shared_base_url
        quick_base_url = request.get("quick_base_url") or shared_base_url
        if deep_base_url:
            config["backend_url"] = deep_base_url
            config["deep_think_base_url"] = deep_base_url
        if quick_base_url:
            config["quick_think_base_url"] = quick_base_url

        # Diagnostic log so Coolify logs show exactly what the UI sent.
        from tradingagents.llm_clients.api_key_env import get_api_key_env
        logger.info(
            "Analysis request: deep=%s/%s (base_url=%s) quick=%s/%s (base_url=%s)",
            deep_provider, config["deep_think_llm"], deep_base_url or "(provider default)",
            quick_provider, config["quick_think_llm"], quick_base_url or "(provider default)",
        )

        # Enable checkpointing for resume support
        config["checkpoint_enabled"] = True

        # Set API key(s) if provided. api_key applies to the deep-thinking
        # provider (legacy field name); quick_api_key is optional and only
        # needed when quick_provider differs from deep_provider and its key
        # isn't already in the persistent credential store.
        if request.get("api_key"):
            env_var = get_api_key_env(deep_provider)
            if env_var:
                os.environ[env_var] = request["api_key"]
        if request.get("quick_api_key"):
            env_var = get_api_key_env(quick_provider)
            if env_var:
                os.environ[env_var] = request["quick_api_key"]

        # Provider-specific thinking config, applied per role so a deep/quick
        # split across providers doesn't leak one role's knob onto the other.
        def _apply_thinking_config(provider: str, value: str) -> None:
            if provider == "google":
                config["google_thinking_level"] = value
            elif provider == "openai":
                config["openai_reasoning_effort"] = value
            elif provider == "anthropic":
                config["anthropic_effort"] = value

        thinking = request.get("thinking_config")
        if thinking:
            _apply_thinking_config(deep_provider, thinking)
        quick_thinking = request.get("quick_thinking_config")
        if quick_thinking and quick_provider != deep_provider:
            _apply_thinking_config(quick_provider, quick_thinking)

        # Analyst setup
        selected_analysts = request.get("analysts", ["market", "social", "news", "fundamentals"])
        ticker = request.get("ticker", "SPY")
        analysis_date = request.get("date", "")
        
        # CLI Options
        config["cli_options"] = request.get("cli_options", {})

        send({"type": "message", "msg_type": "System", "content": f"Starting analysis for {ticker} on {analysis_date}"})

        # Create stats handler
        stats_handler = StatsCallbackHandler(token_budget=config.get("token_budget_per_run"))
        start_time = time.time()

        # Build analyst execution plan
        analyst_execution_plan = build_analyst_execution_plan(selected_analysts)
        analyst_wall_time_tracker = AnalystWallTimeTracker(analyst_execution_plan)

        # Initialize graph
        graph = TradingAgentsGraph(
            selected_analysts,
            config=config,
            debug=True,
            callbacks=[stats_handler],
        )

        # Detect asset type
        from cli.utils import detect_asset_type
        asset_type = detect_asset_type(ticker)

        # Resolve instrument context
        instrument_context = graph.resolve_instrument_context(ticker, asset_type.value)

        # Create initial state
        init_state = graph.propagator.create_initial_state(
            ticker,
            analysis_date,
            asset_type=asset_type.value,
            instrument_context=instrument_context,
        )
        args = graph.propagator.get_graph_args(callbacks=[stats_handler])

        # Recompile with a checkpointer for the duration of this run (see
        # TradingAgentsGraph.checkpointed -- config["checkpoint_enabled"]=True
        # above is otherwise inert, since this handler streams graph.graph
        # directly rather than going through propagate()). thread_id is keyed
        # on ticker+date+graph-shape, NOT on which provider/model is
        # configured, so resuming under a different deep/quick provider than
        # the run that originally failed reuses the same checkpoint.
        checkpointed_ctx = graph.checkpointed(ticker)
        checkpointed_ctx.__enter__()
        if config.get("checkpoint_enabled"):
            tid = thread_id(ticker, str(analysis_date), graph._run_signature(asset_type.value))
            args.setdefault("config", {}).setdefault("configurable", {})["thread_id"] = tid
        graph_input = graph.resolve_graph_input(init_state, ticker, analysis_date, asset_type.value)

        # Set first analyst to in_progress
        first_analyst = get_initial_analyst_node(analyst_execution_plan)
        send({"type": "agent_status", "agent": first_analyst, "status": "in_progress"})
        analyst_wall_time_tracker.mark_started(selected_analysts[0])

        # Agent name mappings (from cli/main.py)
        ANALYST_AGENT_NAMES = {
            "market": "Market Analyst",
            "social": "Sentiment Analyst",
            "news": "News Analyst",
            "fundamentals": "Fundamentals Analyst",
        }
        ANALYST_REPORT_MAP = {
            "market": "market_report",
            "social": "sentiment_report",
            "news": "news_report",
            "fundamentals": "fundamentals_report",
        }
        ANALYST_ORDER = ["market", "social", "news", "fundamentals"]

        # Track reports for progress counting
        reports_received = set()
        processed_message_ids = set()

        # Stream the analysis
        trace = []
        for chunk in graph.graph.stream(graph_input, **args):
            # Process messages
            for message in chunk.get("messages", []):
                msg_id = getattr(message, "id", None)
                if msg_id is not None:
                    if msg_id in processed_message_ids:
                        continue
                    processed_message_ids.add(msg_id)

                # Classify message
                content = _extract_content(message)
                if content and content.strip():
                    msg_type = _classify_msg_type(message)
                    send({"type": "message", "msg_type": msg_type, "content": content[:500]})

                # Tool calls
                if hasattr(message, "tool_calls") and message.tool_calls:
                    for tc in message.tool_calls:
                        if isinstance(tc, dict):
                            send({"type": "tool_call", "name": tc["name"], "args": tc.get("args", {})})
                        else:
                            send({"type": "tool_call", "name": tc.name, "args": tc.args if hasattr(tc, "args") else {}})

            # Update analyst statuses
            found_active = False
            for analyst_key in ANALYST_ORDER:
                if analyst_key not in selected_analysts:
                    continue
                agent_name = ANALYST_AGENT_NAMES[analyst_key]
                report_key = ANALYST_REPORT_MAP[analyst_key]

                if chunk.get(report_key):
                    reports_received.add(report_key)
                    send({"type": "report_update", "section": report_key, "content": chunk[report_key]})
                    send({"type": "agent_status", "agent": agent_name, "status": "completed"})
                elif report_key not in reports_received:
                    if not found_active:
                        send({"type": "agent_status", "agent": agent_name, "status": "in_progress"})
                        found_active = True

            # Sync analyst wall time tracker
            sync_analyst_tracker_from_chunk(analyst_wall_time_tracker, chunk)

            # Research Team
            if chunk.get("investment_debate_state"):
                debate = chunk["investment_debate_state"]
                bull = debate.get("bull_history", "").strip()
                bear = debate.get("bear_history", "").strip()
                judge = debate.get("judge_decision", "").strip()

                if bull or bear:
                    send({"type": "agent_status", "agent": "Bull Researcher", "status": "in_progress"})
                    send({"type": "agent_status", "agent": "Bear Researcher", "status": "in_progress"})
                if bull:
                    send({"type": "report_update", "section": "investment_plan", "content": f"### Bull Researcher Analysis\n{bull}"})
                if bear:
                    send({"type": "report_update", "section": "investment_plan", "content": f"### Bear Researcher Analysis\n{bear}"})
                if judge:
                    content = f"### Research Manager Decision\n{judge}"
                    if bull:
                        content = f"### Bull Researcher Analysis\n{bull}\n\n### Bear Researcher Analysis\n{bear}\n\n{content}"
                    send({"type": "report_update", "section": "investment_plan", "content": content})
                    send({"type": "agent_status", "agent": "Bull Researcher", "status": "completed"})
                    send({"type": "agent_status", "agent": "Bear Researcher", "status": "completed"})
                    send({"type": "agent_status", "agent": "Research Manager", "status": "completed"})
                    send({"type": "agent_status", "agent": "Trader", "status": "in_progress"})

            # Trading Team
            if chunk.get("trader_investment_plan"):
                send({"type": "report_update", "section": "trader_investment_plan", "content": chunk["trader_investment_plan"]})
                send({"type": "agent_status", "agent": "Trader", "status": "completed"})
                send({"type": "agent_status", "agent": "Aggressive Analyst", "status": "in_progress"})

            # Risk Management Team
            if chunk.get("risk_debate_state"):
                risk = chunk["risk_debate_state"]
                agg = risk.get("aggressive_history", "").strip()
                con = risk.get("conservative_history", "").strip()
                neu = risk.get("neutral_history", "").strip()
                judge = risk.get("judge_decision", "").strip()

                if agg:
                    send({"type": "agent_status", "agent": "Aggressive Analyst", "status": "in_progress"})
                if con:
                    send({"type": "agent_status", "agent": "Conservative Analyst", "status": "in_progress"})
                if neu:
                    send({"type": "agent_status", "agent": "Neutral Analyst", "status": "in_progress"})

                report_content = ""
                if agg:
                    report_content += f"### Aggressive Analyst Analysis\n{agg}\n\n"
                if con:
                    report_content += f"### Conservative Analyst Analysis\n{con}\n\n"
                if neu:
                    report_content += f"### Neutral Analyst Analysis\n{neu}\n\n"
                if judge:
                    report_content += f"### Portfolio Manager Decision\n{judge}"
                    send({"type": "agent_status", "agent": "Aggressive Analyst", "status": "completed"})
                    send({"type": "agent_status", "agent": "Conservative Analyst", "status": "completed"})
                    send({"type": "agent_status", "agent": "Neutral Analyst", "status": "completed"})
                    send({"type": "agent_status", "agent": "Portfolio Manager", "status": "completed"})

                if report_content.strip():
                    send({"type": "report_update", "section": "final_trade_decision", "content": report_content.strip()})

            # Send stats periodically
            stats = stats_handler.get_stats()
            send({
                "type": "stats",
                "llm_calls": stats["llm_calls"],
                "tool_calls": stats["tool_calls"],
                "tokens_in": stats.get("tokens_in", 0),
                "tokens_out": stats.get("tokens_out", 0),
                "elapsed": time.time() - start_time,
            })

            trace.append(chunk)

        # ---------- CLI Agent Integrations (Agent Skills) ----------
        # Run enabled coding-agent CLIs (claude, codex, gemini, ...) as a
        # second-opinion research pass after the graph finishes. Each tool
        # must be installed in the container (Dockerfile INSTALL_AGENT_CLIS)
        # and have its provider API key set via env vars
        # (ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY / ...).
        cli_insights = None
        cli_options = config.get("cli_options") or {}
        enabled_clis = {k: v for k, v in cli_options.items() if v}
        if enabled_clis:
            try:
                from app.cli_runner import run_cli_agents

                send({
                    "type": "message",
                    "msg_type": "System",
                    "content": f"Running enabled CLI agents: {', '.join(sorted(enabled_clis))}",
                })
                # Pin each agent to the model its provider gets from the app's
                # model configuration; provider-agnostic agents (opencode) use
                # the app's configured deep model.
                from app.cli_runner import resolve_default_model
                app_deep_model = request.get("deep_model") or config.get("deep_think_llm")
                cli_models = {}
                for tool in enabled_clis:
                    if tool == "opencode":
                        # opencode expects "provider/model" IDs.
                        provider = request.get("provider", "").lower()
                        if provider in ("openai", "anthropic", "google"):
                            model = f"{provider}/{app_deep_model}"
                        else:
                            model = app_deep_model
                    else:
                        model = resolve_default_model(tool)
                    if model:
                        cli_models[tool] = model
                cli_results = run_cli_agents(
                    enabled_clis,
                    ticker=ticker,
                    analysis_date=analysis_date,
                    language=config.get("output_language", "English"),
                    emit=send,
                    keys=request.get("cli_keys") or {},
                    models=cli_models,
                )
                sections = []
                for tool, res in sorted(cli_results.items()):
                    if res["status"] == "completed" and res.get("output"):
                        sections.append(f"### {tool}\n\n{res['output']}")
                    else:
                        sections.append(f"### {tool} -- not available\n\n_{res.get('error') or 'no output'}_")
                if sections:
                    cli_insights = "\n\n".join(sections)
                    send({"type": "report_update", "section": "cli_insights", "content": cli_insights})
            except Exception as exc:
                logger.warning("CLI agent integration failed (non-fatal): %s", exc, exc_info=True)
                send({
                    "type": "message",
                    "msg_type": "System",
                    "content": f"CLI agent step failed (non-fatal): {exc}",
                })

        # Merge final state
        final_state = {}
        for chunk in trace:
            final_state.update(chunk)
        if cli_insights:
            final_state["cli_insights"] = cli_insights

        # Close the checkpointer and clear/resolve the checkpoint + any
        # parked-run record now that the run completed successfully.
        if checkpointed_ctx is not None:
            checkpointed_ctx.__exit__(None, None, None)
            graph.conclude_checkpointed_run(ticker, analysis_date, asset_type.value)

        # Persist this run the same way propagate()/_run_graph() does for the
        # CLI and the worker (this handler streams graph.graph directly, so
        # none of that happens automatically -- see the comment above
        # checkpointed_ctx). Without this, UI runs never feed the reflection
        # loop and are lost the moment the browser closes.
        rating = None
        if final_state.get("final_trade_decision"):
            rating = graph.process_signal(final_state["final_trade_decision"])
            graph.memory_log.store_decision(
                ticker=ticker, trade_date=analysis_date,
                final_trade_decision=final_state["final_trade_decision"],
            )
            try:
                graph.save_reports(final_state, ticker)
            except Exception:
                logger.warning("Failed to persist report tree for %s on %s.", ticker, analysis_date, exc_info=True)

        send({
            "type": "complete",
            "final_state": _serialize_final_state(final_state),
            "rating": rating,
        })

        # Optional: route the completed decision to SignalBridge, subject to
        # both the global execute_from_ui flag and this run's own toggle --
        # a run is analysis-only unless both agree. Never raised past this
        # point: a broker/approval failure must not turn a successfully
        # completed analysis into a WebSocket "error".
        if rating and request.get("execute") and config.get("execute_from_ui", False):
            try:
                _execute_decision(send, config, graph, ticker, analysis_date, asset_type.value, rating)
            except Exception as exc:
                logger.error("Trade execution step failed for %s on %s: %s", ticker, analysis_date, exc, exc_info=True)
                send({"type": "message", "msg_type": "System", "content": f"Trade execution failed (non-fatal): {exc}"})

    except Exception as exc:
        logger.error("Analysis error: %s", exc, exc_info=True)
        if checkpointed_ctx is not None:
            try:
                checkpointed_ctx.__exit__(type(exc), exc, exc.__traceback__)
            except Exception:
                logger.warning("Failed to close checkpointer context cleanly", exc_info=True)
            try:
                # Reclassifies exc; raises RunParkedError (chained from exc)
                # for a quota failure so the WS "error" detail is the clear
                # parked/resumable message instead of the bare provider error,
                # and so a parked-run record + intact checkpoint exist for
                # this run even though it was driven outside propagate().
                graph.park_or_raise(exc, ticker, analysis_date, asset_type.value)
            except Exception as parked_exc:
                exc = parked_exc
                send({
                    "type": "parked",
                    "ticker": getattr(parked_exc, "ticker", ticker),
                    "trade_date": getattr(parked_exc, "trade_date", analysis_date),
                    "failed_role": getattr(parked_exc, "failed_role", "unknown"),
                    "failed_provider": getattr(parked_exc, "failed_provider", "unknown"),
                })
        send({"type": "error", "detail": str(exc)})


def _execute_decision(send, config: dict, graph, ticker: str, analysis_date: str, asset_type: str, rating: str) -> None:
    """Bridge one completed UI run's decision to the execution platform.

    Deliberately reuses the exact same wiring as ``app.worker.run_tick``
    (executor/approval-gate construction, thread_id derivation, reference
    price lookup) rather than reimplementing it, so a UI-triggered trade and
    a worker-triggered trade go through identical sizing/risk/approval
    logic. Sends a WS message describing the outcome; never raises (the
    caller already wraps this, but each internal step is defensive too).
    """
    from tradingagents.dataflows.market_data_validator import get_reference_price
    from tradingagents.execution import ApprovalGate, ApprovalStore, SignalBridge, create_executor
    from tradingagents.graph.checkpointer import thread_id as compute_thread_id
    from tradingagents.notifications.telegram_client import TelegramClient

    reference_price = get_reference_price(ticker, analysis_date)
    if reference_price is None:
        send({
            "type": "message", "msg_type": "System",
            "content": f"No reference price available for {ticker} on {analysis_date}; skipping trade execution.",
        })
        return

    platform = config.get("execution_platform", "paper")
    executor = create_executor(platform, config=config)
    approval_gate = ApprovalGate(
        store=ApprovalStore(config["data_cache_dir"]),
        notifier=TelegramClient(config.get("telegram_bot_token")) if config.get("telegram_enabled") else None,
        chat_id=config.get("telegram_chat_id"),
        timeout_minutes=config.get("approval_timeout_minutes", 60),
        enabled=config.get("require_trade_approval", True),
    )
    bridge = SignalBridge(
        executor, data_dir=config["data_cache_dir"], approval_gate=approval_gate, platform=platform,
    )

    sig = graph._run_signature(asset_type)
    tid = compute_thread_id(ticker, analysis_date, sig)
    order_result = bridge.execute_signal(
        ticker, analysis_date, tid, rating, reference_price=reference_price, asset_type=asset_type,
    )

    if order_result is None:
        send({"type": "message", "msg_type": "System", "content": f"No trade action for {ticker} (rating: {rating})."})
    elif order_result.status.value == "pending_approval":
        send({
            "type": "approval_pending", "ticker": ticker, "side": order_result.side.value,
            "quantity": order_result.quantity,
        })
    else:
        send({
            "type": "order_placed", "ticker": ticker, "side": order_result.side.value,
            "quantity": order_result.quantity, "status": order_result.status.value,
            "message": order_result.message,
        })


def _extract_content(message) -> str | None:
    """Extract text content from a LangChain message."""
    content = getattr(message, "content", None)
    if content is None:
        return None
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
            elif isinstance(item, str):
                parts.append(item)
        return " ".join(parts).strip()
    if isinstance(content, dict):
        return content.get("text", "").strip()
    return str(content).strip()


def _classify_msg_type(message) -> str:
    """Classify a LangChain message into a display type."""
    try:
        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
        if isinstance(message, HumanMessage):
            return "User"
        if isinstance(message, ToolMessage):
            return "Data"
        if isinstance(message, AIMessage):
            return "Agent"
    except ImportError:
        pass
    return "System"


def _serialize_final_state(state: dict) -> dict:
    """Make the final state JSON-serializable by keeping only string/dict values."""
    result = {}
    for key, value in state.items():
        if isinstance(value, str):
            result[key] = value
        elif isinstance(value, dict):
            # Try to serialize nested dicts
            try:
                json.dumps(value)
                result[key] = value
            except (TypeError, ValueError):
                result[key] = str(value)
        # Skip non-serializable objects (LangChain messages, etc.)
    return result
