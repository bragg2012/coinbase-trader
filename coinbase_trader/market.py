from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from .models import Candle, Observation


class CoinbaseMarketData:
    """Small public Advanced Trade market-data client; no credentials required."""

    base_url = "https://api.coinbase.com/api/v3/brokerage"

    def candles(self, product_id: str, limit: int = 120, granularity: str = "ONE_MINUTE") -> list[Candle]:
        url = f"{self.base_url}/products/{urllib.parse.quote(product_id)}/candles"
        query = urllib.parse.urlencode({"granularity": granularity, "limit": min(limit, 350)})
        request = urllib.request.Request(f"{url}?{query}", headers={"User-Agent": "coinbase-trader/0.1"})
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.load(response)
        rows = payload.get("candles", [])
        candles = [
            Candle(
                timestamp=datetime.fromtimestamp(int(row["start"]), tz=timezone.utc),
                product_id=product_id,
                low=float(row["low"]),
                high=float(row["high"]),
                open=float(row["open"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            )
            for row in rows
        ]
        return sorted(candles, key=lambda candle: candle.timestamp)


def observe(candles: list[Candle], product_id: str) -> Observation:
    if len(candles) < 3:
        raise ValueError("at least three candles are required")
    latest = candles[-1]
    previous = candles[:-1]
    baseline = previous[-20:] if len(previous) >= 20 else previous
    average_volume = sum(c.volume for c in baseline) / max(len(baseline), 1)
    average_range = sum(c.high - c.low for c in baseline) / max(len(baseline), 1)
    reference = candles[-min(len(candles), 20)].close
    return Observation(
        product_id=product_id,
        price=latest.close,
        return_lookback=(latest.close / reference) - 1,
        volume_ratio=latest.volume / average_volume if average_volume else 0,
        range_ratio=(latest.high - latest.low) / average_range if average_range else 0,
        momentum=(latest.close / previous[-1].close) - 1,
    )

