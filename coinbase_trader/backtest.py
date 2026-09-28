from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone

from .config import Settings
from .jev import JevDecisionEngine
from .market import observe
from .models import Candle, Decision


@dataclass(frozen=True)
class BacktestResult:
    product_id: str
    bars: int
    accepted: int
    rejected: int
    final_return: float


def load_csv(path: str, product_id: str) -> list[Candle]:
    with open(path, newline="") as handle:
        return [
            Candle(datetime.fromisoformat(row["timestamp"]).replace(tzinfo=timezone.utc), product_id, float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"]), float(row["volume"]))
            for row in csv.DictReader(handle)
        ]


def run(candles: list[Candle], settings: Settings) -> BacktestResult:
    engine = JevDecisionEngine()
    accepted = rejected = 0
    cash_return = 0.0
    for index in range(20, len(candles)):
        decision = engine.decide(observe(candles[: index + 1], candles[index].product_id))
        if decision.decision == Decision.ACCEPT:
            accepted += 1
            cash_return += candles[index].close / candles[index - 1].close - 1
        elif decision.decision == Decision.REJECT:
            rejected += 1
    return BacktestResult(candles[-1].product_id, len(candles), accepted, rejected, cash_return)

