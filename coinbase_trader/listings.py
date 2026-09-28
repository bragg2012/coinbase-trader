from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .coinbase_agents import CoinbaseAgentsCLI


@dataclass(frozen=True)
class MarketProduct:
    product_id: str
    base: str
    quote: str
    status: str
    post_only: bool
    limit_only: bool
    cancel_only: bool
    trading_disabled: bool
    auction_mode: bool
    is_new: bool = False
    new_at: str = ""

    @property
    def eligible_to_monitor(self) -> bool:
        return self.status == "online" and not self.trading_disabled and not self.cancel_only

    @property
    def fully_open(self) -> bool:
        return self.eligible_to_monitor and not self.post_only and not self.limit_only and not self.auction_mode

    @property
    def phase(self) -> str:
        if self.status != "online" or self.trading_disabled:
            return "inactive"
        if self.cancel_only:
            return "cancel_only"
        if self.post_only:
            return "post_only"
        if self.limit_only:
            return "limit_only"
        if self.auction_mode:
            return "auction"
        return "open"


@dataclass(frozen=True)
class PairCost:
    product_id: str
    quote: str
    bid: float
    ask: float
    spread_bps: float | None
    bid_depth_quote: float
    ask_depth_quote: float
    round_trip_fee_bps: float
    estimated_slippage_bps: float | None
    conversion_cost_bps: float
    estimated_round_trip_bps: float | None
    eligible: bool
    reason: str


class CoinbaseAdvancedPublic:
    """Advanced Trade access through the supported Coinbase for Agents CLI."""

    def __init__(self, client: CoinbaseAgentsCLI | None = None):
        self.client = client or CoinbaseAgentsCLI()

    def products(self) -> list[MarketProduct]:
        raw_products: list[dict] = []
        cursor = ""
        for _ in range(20):
            args = ["products", "list", "product_type==SPOT", "limit==250"]
            if cursor:
                args.append(f"cursor=={cursor}")
            raw = self.client.run(*args)
            if not isinstance(raw, dict) or not isinstance(raw.get("products"), list):
                raise ValueError("Coinbase Advanced product catalog response was invalid")
            raw_products.extend(row for row in raw["products"] if isinstance(row, dict))
            if not raw.get("has_next"):
                break
            cursor = str(raw.get("cursor", ""))
            if not cursor:
                break
        products = []
        for row in raw_products:
            if not isinstance(row, dict) or "-" not in str(row.get("product_id", "")):
                continue
            product_id = str(row["product_id"])
            products.append(MarketProduct(
                product_id=product_id,
                base=str(row.get("base_currency_id", "")),
                quote=str(row.get("quote_currency_id", "")),
                status=str(row.get("status", "offline")),
                post_only=bool(row.get("post_only", False)),
                limit_only=bool(row.get("limit_only", False)),
                cancel_only=bool(row.get("cancel_only", False)),
                trading_disabled=bool(row.get("trading_disabled", False) or row.get("is_disabled", False)),
                auction_mode=bool(row.get("auction_mode", False)),
                is_new=bool(row.get("new", False)),
                new_at=str(row.get("new_at", "")),
            ))
        return products

    def spot_fees(self) -> dict:
        result = self.client.run("fees", "product_type==SPOT")
        if not isinstance(result, dict) or not isinstance(result.get("fee_tier"), dict):
            raise ValueError("Coinbase for Agents did not return the spot fee tier")
        return result

    def book_cost(self, product: MarketProduct, *, entry_fee_rate: float, exit_fee_rate: float, target_quote: float, min_depth_quote: float) -> PairCost:
        raw = self.client.run("products", "book", product.product_id)
        if not isinstance(raw, dict) or not isinstance(raw.get("pricebook"), dict):
            raise ValueError(f"invalid order book for {product.product_id}")
        raw = raw["pricebook"]
        bids = raw.get("bids", [])
        asks = raw.get("asks", [])
        if not bids or not asks:
            return PairCost(product.product_id, product.quote, 0, 0, None, 0, 0, (entry_fee_rate + exit_fee_rate) * 10_000, None, 0, None, False, "empty order book")
        bid = float(bids[0]["price"])
        ask = float(asks[0]["price"])
        mid = (bid + ask) / 2
        spread_bps = (ask - bid) / mid * 10_000 if mid else float("inf")
        bid_depth = sum(float(level["price"]) * float(level["size"]) for level in bids[:10])
        ask_depth = sum(float(level["price"]) * float(level["size"]) for level in asks[:10])
        deep_enough = min(bid_depth, ask_depth) >= max(min_depth_quote, target_quote * 5)
        open_market = product.fully_open
        fee_bps = (entry_fee_rate + exit_fee_rate) * 10_000
        buy_remaining = target_quote
        bought_base = 0.0
        buy_spend = 0.0
        for level in asks[:10]:
            price, size = float(level["price"]), float(level["size"])
            take_quote = min(buy_remaining, price * size)
            bought_base += take_quote / price
            buy_spend += take_quote
            buy_remaining -= take_quote
            if buy_remaining <= 1e-9:
                break
        sell_remaining = bought_base
        sell_proceeds = 0.0
        for level in bids[:10]:
            price, size = float(level["price"]), float(level["size"])
            take_base = min(sell_remaining, size)
            sell_proceeds += take_base * price
            sell_remaining -= take_base
            if sell_remaining <= 1e-12:
                break
        depth_covers_order = buy_remaining <= 1e-9 and sell_remaining <= 1e-12
        slippage_bps = max(0.0, (target_quote - sell_proceeds) / target_quote * 10_000) if target_quote else float("inf")
        estimated = slippage_bps + fee_bps
        eligible = open_market and deep_enough
        if not depth_covers_order:
            eligible = False
        reason = "eligible" if eligible else "market not fully open" if not open_market else "insufficient top-10 depth for configured order" if not depth_covers_order or not deep_enough else "insufficient top-10 depth"
        return PairCost(product.product_id, product.quote, bid, ask, spread_bps, bid_depth, ask_depth, fee_bps, slippage_bps, 0.0, estimated, eligible, reason)


def scan_new_listings(products: list[MarketProduct], state_path: str | Path) -> dict:
    """Diff catalog IDs/status against a local snapshot; first scan establishes baseline."""
    path = Path(state_path)
    prior: dict[str, str] = {}
    prior_events: list[dict] = []
    if path.exists():
        saved = json.loads(path.read_text())
        prior = {str(key): str(value) for key, value in saved.get("products", {}).items()}
        prior_events = list(saved.get("events", []))
    current = {product.product_id: product.phase for product in products}
    first_run = not path.exists()
    candidates = []
    if not first_run:
        for product in products:
            state = current[product.product_id]
            previous = prior.get(product.product_id)
            if product.eligible_to_monitor and state != previous:
                if previous is None:
                    event = "new_market_post_only" if product.post_only else "new_market_open" if product.fully_open else "new_market_early_phase"
                elif product.fully_open:
                    event = "market_opened"
                else:
                    event = f"market_phase_{state}"
                candidates.append({**asdict(product), "event": event, "phase": state, "fully_open": product.fully_open, "detected_at": datetime.now(timezone.utc).isoformat()})
    all_events = prior_events + candidates
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"updated_at": datetime.now(timezone.utc).isoformat(), "products": current, "events": all_events}, indent=2))
    return {"first_run": first_run, "catalog_count": len(products), "candidates": candidates, "total_events": len(all_events), "state_file": str(path)}


def rank_quote_pairs(products: list[MarketProduct], base: str, client: CoinbaseAdvancedPublic, *, quotes: tuple[str, ...], entry_fee_rate: float, exit_fee_rate: float, target_quote: float, min_depth_quote: float, conversion_cost_bps: dict[str, float] | None = None) -> list[PairCost]:
    selected = [item for item in products if item.base.upper() == base.upper() and item.quote.upper() in quotes]
    costs = []
    for product in selected:
        if product.status != "online" or product.trading_disabled:
            costs.append(PairCost(product.product_id, product.quote, 0, 0, None, 0, 0, (entry_fee_rate + exit_fee_rate) * 10_000, None, 0.0, None, False, f"product status is {product.status}"))
        else:
            costs.append(client.book_cost(product, entry_fee_rate=entry_fee_rate, exit_fee_rate=exit_fee_rate, target_quote=target_quote, min_depth_quote=min_depth_quote))
    conversion_cost_bps = conversion_cost_bps or {}
    costs = [PairCost(item.product_id, item.quote, item.bid, item.ask, item.spread_bps, item.bid_depth_quote, item.ask_depth_quote, item.round_trip_fee_bps, item.estimated_slippage_bps, conversion_cost_bps.get(item.quote, 0.0), item.estimated_round_trip_bps + conversion_cost_bps.get(item.quote, 0.0) if item.estimated_round_trip_bps is not None else None, item.eligible, item.reason) for item in costs]
    return sorted(costs, key=lambda item: (not item.eligible, item.estimated_round_trip_bps if item.estimated_round_trip_bps is not None else float("inf"), item.product_id))
