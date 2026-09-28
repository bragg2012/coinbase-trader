from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass

from .config import Settings


@dataclass(frozen=True)
class OrderIntent:
    product_id: str
    side: str
    quote_size: float
    reason: str


class CoinbaseForAgentsExecutor:
    """Execution boundary for the local Coinbase for Agents CLI.

    Commands are deliberately kept behind one adapter so the rest of the system
    can be tested in shadow mode without credentials or order side effects.
    """

    def __init__(self, settings: Settings):
        self.settings = settings

    def submit(self, intent: OrderIntent) -> dict:
        self.settings.validate_product(intent.product_id)
        if self.settings.app_mode in {"SHADOW", "PAPER"}:
            return {"status": "simulated", "intent": intent.__dict__}
        if not self.settings.live_allowed():
            raise RuntimeError("live execution denied by APP_MODE/confirmation/CLI guards")
        # Keep the exact CLI order syntax in one place; it can be validated against
        # the installed Coinbase CLI before live enablement.
        command = [self.settings.coinbase_cli_bin, "orders", "create-market-order", "--product-id", intent.product_id, "--side", intent.side, "--quote-size", str(intent.quote_size), "--output", "json"]
        completed = subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)
        return json.loads(completed.stdout)

