"""Unit tests for production features (Cloudflare AI Gateway, Key Pools, Resilient Gateway, Token Optimizer, Trade Execution, Risk Guards)."""

from tradingagents.llm_clients.cloudflare_gateway import CloudflareAIGateway
from tradingagents.llm_clients.key_pool import KeyPoolManager
from tradingagents.llm_clients.llm_gateway import CircuitBreaker, ResilientLLMGateway
from tradingagents.llm_clients.token_optimizer import TokenOptimizer
from tradingagents.llm_clients.adaptive_router import AdaptiveModelRouter
from tradingagents.execution.paper_executor import PaperExecutor
from tradingagents.execution.order_models import Order, OrderSide, OrderType, OrderStatus
from tradingagents.execution.risk_guards import RiskGuards


def test_cloudflare_ai_gateway_url_resolution():
    gw = CloudflareAIGateway(account_id="acc123", gateway_id="gw456", byok_alias="prod_key")
    assert gw.is_configured is True
    url = gw.get_provider_url("openai")
    assert url == "https://gateway.ai.cloudflare.com/v1/acc123/gw456/openai"
    headers = gw.get_extra_headers()
    assert headers.get("cf-aig-byok-alias") == "prod_key"


def test_key_pool_manager_rotation_and_quarantine():
    pool = KeyPoolManager(quarantine_cooldown=100.0)
    pool.register_provider_keys("openai", "key1,key2,key3")

    # Round robin
    k1 = pool.get_active_key("openai")
    k2 = pool.get_active_key("openai")
    k3 = pool.get_active_key("openai")

    assert {k1, k2, k3} == {"key1", "key2", "key3"}

    # Quarantine k1
    pool.report_failure("openai", k1, status_code=429)
    next_key = pool.get_active_key("openai")
    assert next_key != k1


def test_circuit_breaker_tripping():
    cb = CircuitBreaker(failure_threshold=2, cooldown=60.0)
    assert cb.is_available() is True
    cb.record_failure()
    assert cb.is_available() is True
    cb.record_failure()
    assert cb.is_available() is False


def test_token_optimizer_trimming():
    opt = TokenOptimizer()
    text = "Hello " * 500
    trimmed = opt.compress_tool_output(text, max_length=100)
    assert len(trimmed) < len(text)
    assert "TokenOptimizer trimmed" in trimmed


def test_adaptive_model_router():
    router = AdaptiveModelRouter()
    # Portfolio manager should always get deep
    tier_pm = router.select_model_tier("portfolio_manager")
    assert tier_pm == "deep"

    # Routine market analyst gets quick by default
    tier_analyst = router.select_model_tier("market_analyst", volatility_index=15.0)
    assert tier_analyst == "quick"

    # Volatile market analyst gets escalated to deep
    tier_volatile = router.select_model_tier("market_analyst", volatility_index=30.0)
    assert tier_volatile == "deep"


def test_paper_executor_and_risk_guards(tmp_path):
    # data_dir must be test-isolated: PaperExecutor now persists state to
    # SQLite (Phase 4 -- state used to be in-memory and was lost on every
    # restart), so the default path would collide with a real user's
    # ~/.tradingagents and with other test runs.
    executor = PaperExecutor(initial_cash=10000.0, data_dir=tmp_path)
    acc = executor.get_account_balance()
    assert acc.cash == 10000.0

    order = Order(symbol="AAPL", side=OrderSide.BUY, quantity=10, price=150.0)
    res = executor.place_order(order)
    assert res.status == OrderStatus.FILLED

    positions = executor.get_positions()
    assert len(positions) == 1
    assert positions[0].symbol == "AAPL"

    # Risk guards check
    guards = RiskGuards(max_position_pct=0.05)  # 5% max position limit
    valid, msg = guards.validate_order(
        Order(symbol="TSLA", side=OrderSide.BUY, quantity=100, price=200.0),
        account=executor.get_account_balance(),
        positions=positions,
    )
    # Order value $20,000 exceeds 5% of $10,000 portfolio
    assert valid is False
    assert "exceeds maximum position limit" in msg
