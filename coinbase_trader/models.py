from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class Decision(StrEnum):
    ACCEPT = "ACCEPT"
    WATCH = "WATCH"
    REJECT = "REJECT"


@dataclass(frozen=True)
class Candle:
    timestamp: datetime
    product_id: str
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class Observation:
    product_id: str
    price: float
    return_lookback: float
    volume_ratio: float
    range_ratio: float
    momentum: float


@dataclass(frozen=True)
class DecisionRecord:
    product_id: str
    decision: Decision
    confidence: float
    reasons: tuple[str, ...]
    input_hash: str


@dataclass
class Position:
    product_id: str
    entry_price: float
    quantity: float
    opened_at: datetime
    peak_price: float

