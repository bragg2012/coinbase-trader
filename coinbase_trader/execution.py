from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from .coinbase_agents import CoinbaseAgentsCLI
from .config import Settings


@dataclass(frozen=True)
class OrderIntent:
    product_id: str
    side: str
    quote_size: float
    reason: str
    base_size: float | None = None
    client_order_id: str | None = None


class CoinbaseForAgentsExecutor:
    """Execution boundary for the local Coinbase for Agents CLI.

    Commands are deliberately kept behind one adapter so the rest of the system
    can be tested in shadow mode without credentials or order side effects.
    """

    def __init__(self, settings: Settings, client: CoinbaseAgentsCLI | None = None):
        self.settings = settings
        self.client = client or CoinbaseAgentsCLI(settings.coinbase_cli_bin)

    def submit(self, intent: OrderIntent) -> dict:
        self.settings.validate_product(intent.product_id)
        if self.settings.app_mode in {"SHADOW", "PAPER"}:
            return {"status": "simulated", "intent": intent.__dict__}
        if not self.settings.live_allowed():
            raise RuntimeError("live execution denied by APP_MODE/confirmation/CLI guards")
        side = intent.side.upper()
        if side not in {"BUY", "SELL"}:
            raise ValueError("order side must be BUY or SELL")
        args = ["orders", "create", f"product_id={intent.product_id}", f"side={side}", "type=market"]
        if side == "BUY":
            if intent.quote_size <= 0:
                raise ValueError("market BUY requires positive quote_size")
            args.append(f"quote_size={intent.quote_size:.8f}")
        else:
            if intent.base_size is None or intent.base_size <= 0:
                raise ValueError("market SELL requires positive base_size")
            args.append(f"base_size={intent.base_size:.12f}")
        if self.settings.coinbase_portfolio_id:
            args.append(f"portfolio_id={self.settings.coinbase_portfolio_id}")
        args.append(f"client_order_id={intent.client_order_id or uuid4()}")
        result = self.client.run(*args)
        if not isinstance(result, dict):
            raise ValueError("Coinbase for Agents returned an invalid order response")
        return result
