from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_local_env() -> None:
    """Load the repository's ignored .env without adding a dotenv dependency."""
    path = Path.cwd() / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


_load_local_env()


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
    jev_sell_enabled: bool = _bool("JEV_SELL_ENABLED", True)
    enable_live_trading: bool = _bool("ENABLE_LIVE_TRADING")
    live_confirmation: str = os.getenv("LIVE_CONFIRMATION", "")
    coinbase_cli_enabled: bool = _bool("COINBASE_CLI_ENABLED")
    coinbase_cli_bin: str = os.getenv("COINBASE_CLI_BIN", "coinbase")
    max_position_quote: float = float(os.getenv("MAX_POSITION_QUOTE", "50"))
    entry_fee_rate: float = float(os.getenv("ENTRY_FEE_RATE", os.getenv("COINBASE_TAKER_FEE_RATE", "0.006")))
    exit_fee_rate: float = float(os.getenv("EXIT_FEE_RATE", os.getenv("COINBASE_TAKER_FEE_RATE", "0.006")))
    discovery_quote_currencies: tuple[str, ...] = tuple(p.strip().upper() for p in os.getenv("DISCOVERY_QUOTE_CURRENCIES", "USD,USDC").split(",") if p.strip())
    min_listing_depth_quote: float = float(os.getenv("MIN_LISTING_DEPTH_QUOTE", "5000"))
    usd_conversion_cost_bps: float = float(os.getenv("USD_CONVERSION_COST_BPS", "0"))
    usdc_conversion_cost_bps: float = float(os.getenv("USDC_CONVERSION_COST_BPS", "0"))
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
