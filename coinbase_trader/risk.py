from __future__ import annotations

from datetime import datetime, timezone

from .config import Settings
from .models import Position


def exit_reason(position: Position, price: float, now: datetime, settings: Settings) -> str | None:
    position.peak_price = max(position.peak_price, price)
    if price <= position.entry_price * (1 - settings.stop_loss_pct):
        return "hard_stop"
    if price <= position.peak_price * (1 - settings.trailing_stop_pct):
        return "trailing_stop"
    if price >= position.entry_price * (1 + settings.take_profit_pct):
        return "take_profit"
    age_minutes = (now - position.opened_at).total_seconds() / 60
    if age_minutes >= settings.max_hold_minutes:
        return "max_hold"
    return None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)

