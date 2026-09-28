from datetime import datetime, timedelta, timezone

from coinbase_trader.config import Settings
from coinbase_trader.backtest import run
from coinbase_trader.backtest import run_trend_momentum
from coinbase_trader.features import build_snapshot, synthetic_coinbase_candles
from coinbase_trader.jev import JevDecisionEngine
from coinbase_trader.models import Candle, Decision, Observation, Position
from coinbase_trader.risk import estimated_net_pnl_quote, exit_reason


def test_product_allowlist_is_fixed():
    settings = Settings()
    assert settings.validate_product("btc-usd") == "BTC-USD"
    try:
        settings.validate_product("SOL-USD")
    except ValueError as error:
        assert "allowlist" in str(error)
    else:
        raise AssertionError("unlisted products must be rejected")


def test_jev_accepts_volume_confirmed_momentum():
    observation = Observation("BTC-USD", 101, 0.01, 2.0, 1.2, 0.003)
    assert JevDecisionEngine().decide(observation).decision == Decision.ACCEPT


def test_trailing_stop_updates_peak_and_exits():
    settings = Settings()
    opened = datetime.now(timezone.utc) - timedelta(minutes=2)
    position = Position("BTC-USD", 100, 1, opened, 100)
    assert exit_reason(position, 101, opened, settings) is None
    assert exit_reason(position, 99.6, opened, settings) == "trailing_stop"


def test_backtest_records_causal_buy_and_sell():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    candles = []
    for index in range(25):
        price = 100 + index * 0.2
        candles.append(Candle(start + timedelta(minutes=index), "BTC-USD", price, price + 0.1, price - 0.1, price, 100 + index * 10))
    result = run(candles, Settings(jev_sell_enabled=False))
    assert result.bars == 25
    assert result.entries >= 1
    assert result.trades[0].side == "BUY"
    assert result.trades[-1].side == "SELL"


def test_fee_adjusted_pnl_and_take_profit():
    settings = Settings(entry_fee_rate=0.006, exit_fee_rate=0.006)
    opened = datetime.now(timezone.utc) - timedelta(minutes=2)
    position = Position("BTC-USD", 100, 1, opened, 100)
    assert estimated_net_pnl_quote(position, 101.5, settings) > 0
    assert estimated_net_pnl_quote(position, 101.0, settings) < 0
    assert exit_reason(position, 101.8, opened, settings) is None
    assert exit_reason(position, 103.1, opened, settings) == "take_profit"


def test_multitimeframe_snapshot_has_closed_frames_and_signal_state():
    candles = synthetic_coinbase_candles(hours=36)
    snapshot = build_snapshot(candles, "BTC-USD")
    assert snapshot is not None
    assert {frame.timeframe for frame in snapshot.frames} == {"1m", "5m", "15m", "1h"}
    assert "timeframes" in snapshot.to_state()


def test_multitimeframe_backtest_compares_jev_filter():
    candles = synthetic_coinbase_candles(hours=36)
    settings = Settings(jev_sell_enabled=True)
    rules_only = run_trend_momentum(candles, settings, use_jev=False)
    with_jev = run_trend_momentum(candles, settings, use_jev=True)
    assert rules_only.jev_calls == ()
    assert with_jev.entries <= rules_only.entries
