from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .coinbase_agents import CoinbaseAgentsCLI
from .models import Candle, Observation


class CoinbaseMarketData:
    """Historical Coinbase market data obtained through Coinbase for Agents CLI."""

    granularity_seconds = {
        "ONE_MINUTE": 60,
        "FIVE_MINUTE": 300,
        "FIFTEEN_MINUTE": 900,
        "ONE_HOUR": 3600,
        "SIX_HOUR": 21600,
        "ONE_DAY": 86400,
    }
    cli_granularity = {"ONE_MINUTE": "1m", "FIVE_MINUTE": "5m", "FIFTEEN_MINUTE": "15m", "ONE_HOUR": "1h", "SIX_HOUR": "6h", "ONE_DAY": "1d"}

    def __init__(self, client: CoinbaseAgentsCLI | None = None):
        self.client = client or CoinbaseAgentsCLI()

    @staticmethod
    def _time(value: str | int | float) -> datetime:
        if isinstance(value, (int, float)) or str(value).isdigit():
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)

    def _request(self, product_id: str, *, limit: int = 120, granularity: str = "ONE_MINUTE", start: int | None = None, end: int | None = None) -> list[Candle]:
        args = ["products", "candles", product_id, f"granularity=={self.cli_granularity[granularity]}", f"limit=={limit}"]
        if start is not None:
            args.append(f"start=={datetime.fromtimestamp(start, tz=timezone.utc).isoformat().replace('+00:00', 'Z')}")
        if end is not None:
            args.append(f"end=={datetime.fromtimestamp(end, tz=timezone.utc).isoformat().replace('+00:00', 'Z')}")
        payload = self.client.run(*args)
        rows = payload.get("candles", []) if isinstance(payload, dict) else []
        candles = [
            Candle(
                timestamp=self._time(row["start"]),
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
