"""Scheduled worker: runs the analysis pipeline for a watchlist and bridges
completed decisions to a broker/exchange executor.

Deliberately not driven by Coolify's Scheduled Tasks (container-only, no
market-calendar awareness) -- this owns its own schedule via APScheduler so
it can skip non-trading days, and stays a single always-on process
(``restart: unless-stopped``) rather than a cron-spawned one-shot container,
so a mid-tick crash leaves a resumable checkpoint (see graph.trading_graph)
instead of an ambiguous partial container lifecycle.

Run once immediately: ``python -m app.worker --once``
Run the scheduler:      ``python -m app.worker``
"""

from __future__ import annotations

import argparse
import logging
import os
from datetime import date, datetime

logger = logging.getLogger(__name__)

_HEARTBEAT_FILENAME = "worker_heartbeat"


def get_watchlist() -> list[str]:
    """Comma-separated tickers from TRADINGAGENTS_WATCHLIST, e.g. "AAPL,BTC-USD"."""
    raw = os.environ.get("TRADINGAGENTS_WATCHLIST", "")
    return [t.strip().upper() for t in raw.split(",") if t.strip()]


def build_worker_config() -> dict:
    """DEFAULT_CONFIG plus any browser-saved credentials, with checkpointing forced on.

    The worker is unattended by definition, so checkpoint_enabled must be
    True regardless of what the config default/env says -- otherwise a
    crash mid-tick loses everything instead of leaving a resumable/parkable
    run (see Phase 2's checkpoint + run-parking work).
    """
    from app.config_store import apply_to_environment
    from tradingagents.default_config import DEFAULT_CONFIG

    apply_to_environment()
    config = DEFAULT_CONFIG.copy()
    config["checkpoint_enabled"] = True
    return config


def is_trading_day(the_date: date, calendar_name: str = "XNYS") -> bool:
    """Whether ``the_date`` is a trading day on ``calendar_name`` (default: NYSE).

    Uses ``exchange_calendars`` when installed (accounts for holidays, not
    just weekends). Falls back to a plain Mon-Fri check when it isn't --
    crypto watchlists trade every day, and a degraded-but-safe default is
    better than a hard dependency for a check this narrow.
    """
    try:
        import exchange_calendars as xcals
        cal = xcals.get_calendar(calendar_name)
        return bool(cal.is_session(the_date.isoformat()))
    except ImportError:
        return the_date.weekday() < 5
    except Exception:
        logger.warning("Trading-day check failed for %s on %s; assuming open.", calendar_name, the_date, exc_info=True)
        return True


def run_tick(config: dict, watchlist: list[str], trade_date: str | None = None) -> dict[str, str]:
    """Run the pipeline for every ticker in ``watchlist``, bridging completed
    decisions to the configured executor. One ticker's failure does not stop
    the others -- each is isolated in its own try/except.

    Returns ``{ticker: outcome}`` for observability/testing, where outcome is
    one of "ok", "parked", "no_price", "error:<ExceptionType>".
    """
    from cli.utils import detect_asset_type
    from tradingagents.execution import SignalBridge, create_executor
    from tradingagents.dataflows.market_data_validator import get_reference_price
    from tradingagents.graph.checkpointer import thread_id as compute_thread_id
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.llm_clients.llm_errors import RunParkedError

    trade_date = trade_date or date.today().isoformat()
    outcomes: dict[str, str] = {}

    if not watchlist:
        logger.warning("Watchlist is empty (TRADINGAGENTS_WATCHLIST unset) -- nothing to do.")
        return outcomes

    executor = create_executor(config.get("execution_platform", "paper"), config=config)
    bridge = SignalBridge(executor, data_dir=config["data_cache_dir"])

    from tradingagents.integrations import AITraderClient
    ai_trader = AITraderClient(
        base_url=config.get("ai_trader_base_url"), agent_token=config.get("ai_trader_agent_token"),
    )

    for ticker in watchlist:
        try:
            asset_type = detect_asset_type(ticker)
            graph = TradingAgentsGraph(config=config, debug=False)

            try:
                final_state, rating = graph.propagate(ticker, trade_date, asset_type=asset_type.value)
            except RunParkedError as exc:
                logger.warning("Run parked for %s on %s: %s", ticker, trade_date, exc)
                outcomes[ticker] = "parked"
                continue

            reference_price = get_reference_price(ticker, trade_date)
            if reference_price is None:
                logger.warning(
                    "No reference price available for %s on %s; skipping order (analysis still completed and was logged).",
                    ticker, trade_date,
                )
                outcomes[ticker] = "no_price"
                continue

            sig = graph._run_signature(asset_type.value)
            tid = compute_thread_id(ticker, trade_date, sig)
            order_result = bridge.execute_signal(
                ticker, trade_date, tid, rating,
                reference_price=reference_price, asset_type=asset_type.value,
            )
            outcomes[ticker] = "ok"

            # Optional, additive, never fatal: post the decision for
            # AI-Trader's leaderboard/copy-trade surface (see
            # integrations/ai_trader_client.py). A no-op when unconfigured.
            if ai_trader.is_configured:
                action = order_result.side.value if order_result else rating.lower()
                ai_trader.post_signal(
                    ticker, action, reference_price,
                    quantity=order_result.quantity if order_result else 0.0,
                    asset_type=asset_type.value,
                    content=f"TradingAgents rating: {rating}",
                )
        except Exception as exc:
            logger.error("Tick failed for %s on %s: %s", ticker, trade_date, exc, exc_info=True)
            outcomes[ticker] = f"error:{type(exc).__name__}"

    return outcomes


def _touch_heartbeat(data_dir: str) -> None:
    from pathlib import Path
    path = Path(data_dir) / _HEARTBEAT_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(datetime.now().isoformat(), encoding="utf-8")


def _scheduled_tick() -> None:
    config = build_worker_config()
    today = date.today()
    if not is_trading_day(today, config.get("worker_calendar", "XNYS")):
        logger.info("Not a trading day (%s); skipping tick.", today)
        _touch_heartbeat(config["data_cache_dir"])
        return

    watchlist = get_watchlist()
    outcomes = run_tick(config, watchlist)
    logger.info("Tick complete for %s: %s", today, outcomes)
    _touch_heartbeat(config["data_cache_dir"])


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="TradingAgents scheduled worker")
    parser.add_argument(
        "--once", action="store_true",
        help="Run a single tick immediately and exit, instead of starting the scheduler.",
    )
    args = parser.parse_args()

    if args.once:
        _scheduled_tick()
        return

    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    # Default: once daily shortly after the US market close (21:00 UTC ~=
    # 4-5pm ET depending on DST), so the day's OHLCV is settled. Override
    # with a standard 5-field cron expression for a different cadence (e.g.
    # crypto watchlists that want to run more than once a day).
    cron_expr = os.environ.get("TRADINGAGENTS_WORKER_CRON", "0 21 * * 1-5")
    trigger = CronTrigger.from_crontab(cron_expr)

    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(_scheduled_tick, trigger, id="tradingagents_tick", misfire_grace_time=3600)
    logger.info("Worker started; next run schedule: %s", cron_expr)
    scheduler.start()


if __name__ == "__main__":
    main()
