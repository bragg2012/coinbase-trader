from __future__ import annotations

import http.client
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from .models import Candle, Observation


class CoinbaseMarketData:
    """Public Coinbase historical market-data client; no credentials required."""

    base_url = "https://api.exchange.coinbase.com"

    granularity_seconds = {
        "ONE_MINUTE": 60,
        "FIVE_MINUTE": 300,
        "FIFTEEN_MINUTE": 900,
        "ONE_HOUR": 3600,
        "SIX_HOUR": 21600,
        "ONE_DAY": 86400,
    }

    def _request(self, product_id: str, *, limit: int = 120, granularity: str = "ONE_MINUTE", start: int | None = None, end: int | None = None) -> list[Candle]:
        url = f"{self.base_url}/products/{urllib.parse.quote(product_id)}/candles"
        params = {"granularity": self.granularity_seconds[granularity]}
        if start is not None:
            params["start"] = start
        if end is not None:
            params["end"] = end
        query = urllib.parse.urlencode(params)
        request = urllib.request.Request(f"{url}?{query}", headers={"User-Agent": "coinbase-trader/0.1"})
        payload = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    payload = json.load(response)
                break
            except (http.client.RemoteDisconnected, urllib.error.HTTPError, urllib.error.URLError):
                if attempt == 2:
                    raise
                time.sleep(0.5 * (attempt + 1))
        rows = payload if isinstance(payload, list) else []
        candles = [
            Candle(
                timestamp=datetime.fromtimestamp(int(row[0]), tz=timezone.utc),
                product_id=product_id,
                low=float(row[1]),
                high=float(row[2]),
                open=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
            )
            for row in rows
        ]
        return sorted(candles, key=lambda candle: candle.timestamp)

    def candles(self, product_id: str, limit: int = 120, granularity: str = "ONE_MINUTE") -> list[Candle]:
        return self._request(product_id, limit=limit, granularity=granularity)

    def candles_between(self, product_id: str, start: datetime, end: datetime, granularity: str = "FIVE_MINUTE") -> list[Candle]:
        """Fetch a long range in Coinbase's maximum 350-candle pages."""
        seconds = self.granularity_seconds[granularity]
        cursor = start.astimezone(timezone.utc)
        end = end.astimezone(timezone.utc)
        result: dict[int, Candle] = {}
        while cursor < end:
            # Coinbase Exchange caps a candle response at roughly 300 buckets;
            # keep a one-bucket margin because both range endpoints are inclusive.
            page_end = min(end, cursor + timedelta(seconds=seconds * 299))
            for candle in self._request(product_id, limit=350, granularity=granularity, start=int(cursor.timestamp()), end=int(page_end.timestamp())):
                result[int(candle.timestamp.timestamp())] = candle
            cursor = page_end + timedelta(seconds=seconds)
        return [result[key] for key in sorted(result)]


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
