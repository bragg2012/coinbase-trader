from __future__ import annotations

from datetime import datetime, timezone

from .config import Settings
from .models import Position


def estimated_fees_quote(position: Position, price: float, settings: Settings) -> float:
    return (position.entry_price * position.quantity * settings.entry_fee_rate) + (price * position.quantity * settings.exit_fee_rate)


def estimated_net_pnl_quote(position: Position, price: float, settings: Settings) -> float:
    entry_value = position.entry_price * position.quantity
    exit_value = price * position.quantity
    return (exit_value * (1 - settings.exit_fee_rate)) - (entry_value * (1 + settings.entry_fee_rate))


def exit_reason(position: Position, price: float, now: datetime, settings: Settings) -> str | None:
    position.peak_price = max(position.peak_price, price)
    if price <= position.entry_price * (1 - settings.stop_loss_pct):
        return "hard_stop"
    if price <= position.peak_price * (1 - settings.trailing_stop_pct):
        return "trailing_stop"
    fee_adjusted_target = position.entry_price * (1 + settings.entry_fee_rate + settings.take_profit_pct) / (1 - settings.exit_fee_rate)
    if price >= fee_adjusted_target:
        return "take_profit"
    age_minutes = (now - position.opened_at).total_seconds() / 60
    if age_minutes >= settings.max_hold_minutes:
        return "max_hold"
    return None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
