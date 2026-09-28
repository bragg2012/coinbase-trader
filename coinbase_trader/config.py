from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_mode: str = os.getenv("APP_MODE", "SHADOW").upper()
    products: tuple[str, ...] = tuple(
        p.strip().upper() for p in os.getenv("COINBASE_PRODUCTS", "BTC-USD,ETH-USD").split(",") if p.strip()
    )
    granularity: str = os.getenv("BAR_GRANULARITY", "ONE_MINUTE")
    lookback_bars: int = int(os.getenv("LOOKBACK_BARS", "120"))
    jev_mode: str = os.getenv("JEV_MODE", "DETERMINISTIC").upper()
    enable_live_trading: bool = _bool("ENABLE_LIVE_TRADING")
    live_confirmation: str = os.getenv("LIVE_CONFIRMATION", "")
    coinbase_cli_enabled: bool = _bool("COINBASE_CLI_ENABLED")
    coinbase_cli_bin: str = os.getenv("COINBASE_CLI_BIN", "coinbase")
    max_position_quote: float = float(os.getenv("MAX_POSITION_QUOTE", "50"))
    max_daily_loss_quote: float = float(os.getenv("MAX_DAILY_LOSS_QUOTE", "10"))
    stop_loss_pct: float = float(os.getenv("STOP_LOSS_PCT", "0.008"))
    trailing_stop_pct: float = float(os.getenv("TRAILING_STOP_PCT", "0.012"))
    take_profit_pct: float = float(os.getenv("TAKE_PROFIT_PCT", "0.018"))
    max_hold_minutes: int = int(os.getenv("MAX_HOLD_MINUTES", "180"))

    def validate_product(self, product: str) -> str:
        product = product.upper()
        if product not in self.products:
            raise ValueError(f"product {product!r} is not in the fixed allowlist: {self.products}")
        return product

    def live_allowed(self) -> bool:
        return (
            self.app_mode == "LIVE"
            and self.enable_live_trading
            and self.live_confirmation == "I_UNDERSTAND"
            and self.coinbase_cli_enabled
        )

