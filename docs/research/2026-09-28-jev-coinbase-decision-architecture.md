# Jev + Coinbase decision architecture

Research date: 2026-09-28

## Conclusion

Use Coinbase WebSocket market data as the always-on ingest layer, compute features locally, and call TypeSafe Jev only at decision boundaries. Do not poll Coinbase REST or call Jev on every tick.

The first live-like configuration should be:

- BTC-USD and ETH-USD only.
- WebSocket `level2`, `market_trades`, and `candles`/ticker data.
- 1-minute bars as the execution decision clock.
- 5-minute bars as the primary confirmation timeframe.
- 15-minute and 1-hour bars as regime/context filters.
- Local hard stops and trailing stops evaluated continuously, independently of Jev.
- Jev entry calls only when flat and a deterministic setup pre-filter fires.
- Jev sell-pressure calls only while a position is open and the local exit gates have not already fired.

Coinbase’s Advanced Trade API separates REST for orders/account/HTTP market data from WebSocket for real-time prices, order book, and account updates. The public market-data endpoint is `wss://advanced-trade-ws.coinbase.com`; the feed requires a subscription message within five seconds and supports multiple products/channels. [Advanced Trade overview](https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/overview), [WebSocket overview](https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/websocket/websocket-overview)

TypeSafe Jev’s API is `POST https://api.typesafe.ai/v1/systemone` with Bearer authentication and a body containing `state`, `model`, and typed `questions`. It returns structured `answers`, including `choice`, `score`, `noul`, probabilities, and confidence. [TypeSafe quick start](https://docs.typesafe.ai/introduction/quickstart), [TypeSafe introduction](https://docs.typesafe.ai/introduction)

## What Coinbase data should become Jev state?

Do not send raw WebSocket messages directly. Normalize them into a compact, timestamped decision snapshot. The state should include:

```json
{
  "as_of": "2026-09-28T12:00:00Z",
  "product_id": "BTC-USD",
  "market": {
    "last": 84000.0,
    "bid": 83999.9,
    "ask": 84000.1,
    "spread_bps": 0.024,
    "top_book_imbalance": 0.18,
    "trade_flow": {
      "buy_notional_1m": 1200000,
      "sell_notional_1m": 980000,
      "buy_sell_ratio_1m": 1.224,
      "trade_count_1m": 1840
    }
  },
  "timeframes": {
    "1m": {"open": 83920, "high": 84040, "low": 83880, "close": 84000, "volume": 96, "return": 0.0010, "volume_z": 1.7, "rsi": 61.2, "atr_bps": 19.4},
    "5m": {"return": 0.0031, "volume_z": 1.3, "trend": "UP", "breakout": true},
    "15m": {"return": 0.0064, "trend": "UP", "structure": "higher_highs"},
    "1h": {"return": 0.011, "trend": "UP", "distance_from_vwap_bps": 34}
  },
  "data_quality": {
    "market_data_age_ms": 220,
    "candle_gaps": 0,
    "book_sequence_gap": false,
    "all_required_timeframes_closed": true
  },
  "portfolio": {
    "mode": "SHADOW",
    "position": "FLAT",
    "quote_available": 150.0,
    "daily_realized_pnl": 0.0
  }
}
```

The exact indicators are not sacred; the important properties are: one observation timestamp, closed-bar features only, explicit freshness, explicit missingness, and no look-ahead. For order-book imbalance, preserve the depth used and the calculation window, for example `top_book_imbalance_depth=10`.

For the first version, send both summaries and a short recent-bar tail (for example the last 20 closed bars for each timeframe) only when Jev needs chart structure. Avoid sending an entire month of candles in every request.

## Question design

TypeSafe recommends atomic questions evaluated independently against the same state. Therefore use separate entry and exit calls rather than one ambiguous “should I trade?” question.

### Flat position: entry call

```json
{
  "state": "<compact JSON snapshot>",
  "model": "jev-1.13.0",
  "questions": {
    "entry_action": {
      "type": "choice",
      "instructions": "Given only the supplied closed-bar, flow, book, freshness, and portfolio state, choose the action now.",
      "criteria": {
        "BUY": "A long spot entry is supported by aligned multi-timeframe structure, confirmation, and acceptable execution conditions.",
        "WAIT": "The setup is incomplete, conflicting, stale, extended, or not attractive enough after costs.",
        "REJECT": "The evidence is adverse or unsafe for an entry."
      }
    },
    "entry_quality": {
      "type": "score",
      "instructions": "Score the quality of the proposed entry.",
      "criteria": ["Poor", "Mixed", "Strong"]
    },
    "risk_flag": {
      "type": "noul",
      "instructions": "Does the supplied state contain a material market-data, liquidity, or execution-risk warning?"
    }
  }
}
```

The code should admit a BUY only when `entry_action.choice == BUY`, confidence is above a configured threshold, `risk_flag.noul` is below the configured danger threshold, and deterministic risk/cost/freshness gates pass. Jev should not be asked to invent a price, size, stop, or fee estimate.

### Open position: exit call

```json
{
  "state": "<snapshot plus entry_price, peak_price, stop_price, unrealized_pnl, age>",
  "model": "jev-1.13.0",
  "questions": {
    "exit_action": {
      "type": "choice",
      "instructions": "Given only the supplied state, decide whether to sell the open spot position now.",
      "criteria": {
        "SELL": "Sell pressure, failed structure, or a deteriorating multi-timeframe setup justifies exiting.",
        "HOLD": "The position remains supported and no Jev sell-pressure gate is present."
      }
    },
    "sell_pressure": {
      "type": "score",
      "instructions": "Score current sell pressure.",
      "criteria": ["Low", "Mixed", "High"]
    }
  }
}
```

The local hard stop and trailing stop remain immediate risk controls. Jev is an additional sell-pressure gate, not a reason to delay a hard stop or rely on a model response during a data outage.

## Real-time cadence

Coinbase’s WebSocket feed is the right mechanism for near-real-time operation; it avoids repeatedly fetching REST candles and gives the system live price/order-book/trade updates. Coinbase’s documentation does not expose a single numeric WebSocket request budget in the page retrieved for this design, so the system should use a conservative application budget, record every request/response and 429, and make the budget configurable rather than assuming a vendor limit. [WebSocket overview](https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/websocket/websocket-overview), [WebSocket rate limits](https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/websocket/websocket-rate-limits)

Recommended initial schedule per symbol:

| Event | Local action | Jev call |
|---|---|---:|
| Every trade/book update | Update local state, stops, flow accumulators | 0 |
| 1m candle close | Recompute 1m/5m/15m/1h features | 0 or 1 entry/exit call |
| Deterministic entry pre-filter fires while flat | Freeze snapshot and call entry questions | 1 |
| Position open, 1m close, no local stop | Freeze snapshot and call exit questions | 1 |
| Local hard/trailing stop fires | Submit/record exit immediately | 0 |
| Stale data, sequence gap, missing candle | Freeze new entries; reconcile | 0 |

Start with a ceiling of one Jev entry/exit call per symbol per minute, two symbols, and a global ceiling of four calls per minute. Add a 15–30 second debounce after `WAIT`, plus an input-hash cache so the same snapshot is never charged twice. Increase only after observing latency, errors, and decision quality.

## Timeframe choice

Use 1m as the decision clock, not necessarily as the sole signal. A 5m-only strategy is less noisy but can enter late; 1m-only decisions are more sensitive to microstructure noise. The proposed hierarchy is:

- 1m: trigger and immediate flow/volatility.
- 5m: confirmation and setup quality.
- 15m: local structure and trend alignment.
- 1h: regime/context and overextension.

The backtester must build these bars from the same event/candle stream used live. It must call Jev only after the relevant bar closes, then enter on the next bar/open or a clearly modelled close fill. Otherwise the historical result will contain look-ahead.

## Architecture change recommended

1. Add a WebSocket collector and reconnect/sequence-gap handling.
2. Add a candle/flow feature store keyed by product and timeframe.
3. Replace the current generic `Observation` with a versioned `DecisionSnapshot`.
4. Make TypeSafe question packs versioned (`entry-v1`, `exit-v1`) and store the full request/response hash.
5. Add deterministic pre-filters so Jev is called on candidate boundaries, not continuously.
6. Add fee, spread, slippage, partial-fill, and next-bar execution assumptions to backtests.
7. Run deterministic replay first, then a small real-Jev replay using cached snapshots, then shadow live.

The current repository already has the TypeSafe System One endpoint and typed questions wired at a basic level. It still needs the WebSocket feature collector, versioned multi-timeframe snapshot, and realistic execution-cost model before it is suitable for a near-real-time paper loop.

