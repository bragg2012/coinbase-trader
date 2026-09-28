from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

from .models import Candle, Observation


@dataclass(frozen=True)
class TimeframeFeatures:
    timeframe: str
    bars: int
    close: float
    ema_fast: float
    ema_slow: float
    trend: int
    return_lookback: float
    rsi: float
    macd: float
    macd_signal: float
    macd_histogram: float
    atr: float
    volume_ratio: float


@dataclass(frozen=True)
class TrendMomentumSnapshot:
    product_id: str
    as_of: str
    frames: tuple[TimeframeFeatures, ...]
    trend_score: int
    regime: str
    entry_signal: bool
    exit_signal: bool
    reasons: tuple[str, ...]

    def to_state(self) -> dict:
        return {
            "action": "MULTI_TIMEFRAME_SETUP",
            "product_id": self.product_id,
            "as_of": self.as_of,
            "trend_score": self.trend_score,
            "regime": self.regime,
            "entry_signal": self.entry_signal,
            "exit_signal": self.exit_signal,
            "reasons": list(self.reasons),
            "timeframes": {frame.timeframe: asdict(frame) for frame in self.frames},
        }

    def to_observation(self) -> Observation:
        frame = self.frames[0]
        return Observation(
            self.product_id,
            frame.close,
            frame.return_lookback,
            frame.volume_ratio,
            frame.atr / frame.close if frame.close else 0.0,
            frame.macd_histogram / frame.close if frame.close else 0.0,
        )


def _ema(values: list[float], period: int) -> float:
    if not values:
        return 0.0
    alpha = 2 / (period + 1)
    value = values[0]
    for item in values[1:]:
        value = alpha * item + (1 - alpha) * value
    return value


def _ema_series(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2 / (period + 1)
    result = [values[0]]
    for item in values[1:]:
        result.append(alpha * item + (1 - alpha) * result[-1])
    return result


def _rsi(closes: list[float], period: int = 14) -> float:
    if len(closes) < 2:
        return 50.0
    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))][-period:]
    gains = sum(max(change, 0.0) for change in changes) / max(1, len(changes))
    losses = sum(max(-change, 0.0) for change in changes) / max(1, len(changes))
    if losses == 0:
        return 100.0 if gains else 50.0
    return 100 - (100 / (1 + gains / losses))


def _atr(candles: list[Candle], period: int = 14) -> float:
    if not candles:
        return 0.0
    true_ranges: list[float] = []
    for index, candle in enumerate(candles):
        previous_close = candles[index - 1].close if index else candle.open
        true_ranges.append(max(candle.high - candle.low, abs(candle.high - previous_close), abs(candle.low - previous_close)))
    values = true_ranges[-period:]
    return sum(values) / len(values)


def _aggregate(candles: list[Candle], minutes: int) -> list[Candle]:
    """Aggregate only complete fixed windows, preventing look-ahead from partial bars."""
    if minutes == 1:
        return candles
    seconds = minutes * 60
    groups: dict[int, list[Candle]] = {}
    for candle in candles:
        bucket = int(candle.timestamp.timestamp()) // seconds * seconds
        groups.setdefault(bucket, []).append(candle)
    result: list[Candle] = []
    for bucket, items in sorted(groups.items()):
        items = sorted(items, key=lambda item: item.timestamp)
        if len(items) != minutes:
            continue
        result.append(Candle(datetime.fromtimestamp(bucket, tz=timezone.utc), items[0].product_id, items[0].open, max(item.high for item in items), min(item.low for item in items), items[-1].close, sum(item.volume for item in items)))
    return result


def _frame(candles: list[Candle], label: str, minutes: int) -> TimeframeFeatures | None:
    bars = _aggregate(candles, minutes)
    if len(bars) < 30:
        return None
    closes = [item.close for item in bars]
    fast = _ema(closes, 8)
    slow = _ema(closes, 21)
    trend = 1 if closes[-1] > fast > slow else -1 if closes[-1] < fast < slow else 0
    lookback = closes[-1] / closes[max(0, len(closes) - 6)] - 1
    macd_values = [fast_value - slow_value for fast_value, slow_value in zip(_ema_series(closes, 12), _ema_series(closes, 26))]
    macd = macd_values[-1]
    signal = _ema(macd_values[-9:], 9)
    volume_average = sum(item.volume for item in bars[-21:-1]) / 20
    return TimeframeFeatures(label, len(bars), closes[-1], fast, slow, trend, lookback, _rsi(closes), macd, signal, macd - signal, _atr(bars), bars[-1].volume / volume_average if volume_average else 1.0)


def build_snapshot(candles: list[Candle], product_id: str) -> TrendMomentumSnapshot | None:
    # A bounded history is sufficient for the configured slow window and keeps
    # repeated 1-minute backtest snapshots fast while remaining causal.
    candles = candles[-(35 * 60):]
    specs = (("1m", 1, 1), ("5m", 5, 2), ("15m", 15, 3), ("1h", 60, 4))
    frames = tuple(frame for label, minutes, _ in specs if (frame := _frame(candles, label, minutes)) is not None)
    if len(frames) != len(specs):
        return None
    weights = {label: weight for label, _, weight in specs}
    score = sum(frame.trend * weights[frame.timeframe] for frame in frames)
    by_name = {frame.timeframe: frame for frame in frames}
    entry = score >= 4 and by_name["1m"].trend > 0 and by_name["5m"].trend > 0 and by_name["1m"].volume_ratio >= 1.05 and by_name["15m"].trend >= 0
    exit_signal = score <= 0 or (by_name["1m"].trend < 0 and by_name["5m"].trend < 0 and by_name["1m"].volume_ratio >= 1.05)
    regime = "UPTREND" if score >= 4 else "DOWNTREND" if score <= -4 else "MIXED"
    reasons = (f"weighted_trend_score={score}", f"1m_rsi={by_name['1m'].rsi:.1f}", f"1m_volume_ratio={by_name['1m'].volume_ratio:.2f}", f"regime={regime}")
    return TrendMomentumSnapshot(product_id, candles[-1].timestamp.isoformat(), frames, score, regime, entry, exit_signal, reasons)


def synthetic_coinbase_candles(product_id: str = "BTC-USD", hours: int = 72) -> list[Candle]:
    """Deterministic Coinbase-shaped 1-minute OHLCV data for local plumbing/backtests."""
    import math

    total = max(24 * 60, hours * 60)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    price = 100_000.0
    candles: list[Candle] = []
    for index in range(total):
        phase = index / total
        drift = 0.00016 if phase < 0.34 else 0.00002 if phase < 0.66 else -0.00013
        wave = 0.00012 * math.sin(index / 17) + 0.00006 * math.sin(index / 5)
        open_price = price
        close = price * (1 + drift + wave)
        high = max(open_price, close) * (1 + 0.00025 + 0.00008 * abs(math.sin(index)))
        low = min(open_price, close) * (1 - 0.00025 - 0.00005 * abs(math.cos(index)))
        volume = 1.0 + 0.25 * abs(math.sin(index / 11)) + (1.0 if index % 37 == 0 else 0.0)
        candles.append(Candle(start + timedelta(minutes=index), product_id, open_price, high, low, close, volume))
        price = close
    return candles
