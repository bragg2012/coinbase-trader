from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from .config import Settings
from .jev import HttpJevDecisionEngine, JevDecisionEngine
from .market import observe
from .models import Candle, Decision, Position
from .risk import exit_reason


@dataclass(frozen=True)
class Trade:
    product_id: str
    side: str
    timestamp: str
    price: float
    reason: str
    jev_decision: str | None = None
    jev_input_hash: str | None = None
    pnl_quote: float | None = None


@dataclass(frozen=True)
class BacktestResult:
    product_id: str
    bars: int
    entries: int
    exits: int
    wins: int
    losses: int
    final_return: float
    trades: tuple[Trade, ...]
    jev_calls: tuple[dict, ...] = ()

    def write_json(self, path: str) -> None:
        with open(path, "w") as handle:
            json.dump(asdict(self), handle, indent=2)


def load_csv(path: str, product_id: str) -> list[Candle]:
    with open(path, newline="") as handle:
        rows = []
        for row in csv.DictReader(handle):
            timestamp = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00")).astimezone(timezone.utc)
            rows.append(Candle(timestamp, product_id, float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"]), float(row["volume"])))
        return rows


def write_csv(candles: list[Candle], path: str) -> None:
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["timestamp", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        for candle in candles:
            writer.writerow({"timestamp": candle.timestamp.isoformat(), "open": candle.open, "high": candle.high, "low": candle.low, "close": candle.close, "volume": candle.volume})


def run(candles: list[Candle], settings: Settings, *, engine: JevDecisionEngine | None = None) -> BacktestResult:
    if len(candles) < 21:
        raise ValueError("at least 21 candles are required")
    engine = engine or (HttpJevDecisionEngine() if settings.jev_mode == "HTTP" else JevDecisionEngine())
    position: Position | None = None
    trades: list[Trade] = []
    realized = 0.0
    for index in range(20, len(candles)):
        candle = candles[index]
        observation = observe(candles[: index + 1], candle.product_id)
        if position:
            reason = exit_reason(position, candle.close, candle.timestamp, settings)
            if reason is None and settings.jev_sell_enabled:
                should_sell, jev_reason = engine.sell_gate(observation, position)
                reason = f"jev_sell_pressure:{jev_reason}" if should_sell else None
            if reason:
                pnl = (candle.close - position.entry_price) * position.quantity
                realized += pnl
                trades.append(Trade(candle.product_id, "SELL", candle.timestamp.isoformat(), candle.close, reason, pnl_quote=pnl))
                position = None
                continue
        if position is None:
            decision = engine.decide(observation)
            if decision.decision == Decision.ACCEPT:
                quantity = settings.max_position_quote / candle.close
                position = Position(candle.product_id, candle.close, quantity, candle.timestamp, candle.close)
                trades.append(Trade(candle.product_id, "BUY", candle.timestamp.isoformat(), candle.close, "jev_accept", decision.decision.value, decision.input_hash))
    if position:
        candle = candles[-1]
        pnl = (candle.close - position.entry_price) * position.quantity
        realized += pnl
        trades.append(Trade(candle.product_id, "SELL", candle.timestamp.isoformat(), candle.close, "end_of_test", pnl_quote=pnl))
    entries = sum(trade.side == "BUY" for trade in trades)
    sells = [trade for trade in trades if trade.side == "SELL" and trade.pnl_quote is not None]
    return BacktestResult(candles[-1].product_id, len(candles), entries, len(sells), sum(trade.pnl_quote > 0 for trade in sells), sum(trade.pnl_quote <= 0 for trade in sells), realized / settings.max_position_quote, tuple(trades), tuple(getattr(engine, "call_log", ())))
