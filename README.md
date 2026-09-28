# coinbase-trader

An intentionally narrow, local-first BTC/ETH day-trading research and execution skeleton.

The first version has no asset discovery. It watches an allowlist (`BTC-USD`, `ETH-USD` by default), turns market observations into deterministic setups, sends those setups through a JEV decision boundary, and applies protective exit rules. It supports offline backtests from Coinbase candle data and keeps live trading disabled until the paper path has earned an explicit enablement.

## Design

```text
Coinbase market data -> observation -> setup -> JEV decision -> risk gate
                                                       |          |
                                             paper ledger    Coinbase for Agents

historical candles -> same observation/setup/decision path -> backtest report
```

Coinbase for Agents is the execution boundary. The supported setup is the local Coinbase CLI with a dedicated Advanced portfolio and a CDP API key. The repository never stores the key, and the execution adapter refuses live mode unless it is explicitly enabled.

## Safety defaults

- `APP_MODE=SHADOW` is the default.
- Only `BTC-USD` and `ETH-USD` are accepted by the allowlist.
- No discovery, automatic symbol expansion, withdrawals, transfers, leverage, or derivatives.
- Shadow/paper modes never submit orders.
- Live mode requires `ENABLE_LIVE_TRADING=true`, `LIVE_CONFIRMATION=I_UNDERSTAND`, and `COINBASE_CLI_ENABLED=true`.
- Every position has a hard stop, trailing stop, take-profit, and maximum holding period.

This is experimental software, not financial advice. Crypto trading can lose all invested capital.

## Quick start

```bash
python3.11 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env

python -m coinbase_trader.cli snapshot
python -m coinbase_trader.cli download --symbol BTC-USD --days 30 --granularity FIVE_MINUTE --out data/btc-usd-5m.csv
python -m coinbase_trader.cli backtest --csv data/btc-usd-5m.csv --symbol BTC-USD --report reports/btc-jev.json
python -m coinbase_trader.cli dummy-backtest --symbol BTC-USD --hours 72 --report reports/dummy-trend.json
python -m coinbase_trader.cli listing-scan --state storage/listing-catalog.json --report reports/listings.json
python -m coinbase_trader.cli pair-scan --assets BTC,ETH --report reports/quote-pairs.json
pytest -q
```

`dummy-backtest` generates deterministic 1-minute Coinbase-shaped OHLCV data, derives closed 1m/5m/15m/1h trend and momentum features, and reports the same run with rules-only versus Jev-filtered entries/exits. It is intended to verify plumbing and accounting before credentials or Coinbase data are configured; it is not evidence of profitability.

`listing-scan` reads Coinbase Advanced's public spot-product catalog and diffs it against a local snapshot. The first run only establishes the baseline; later runs report newly seen markets and market phase changes, including when post-only markets become fully open. Events are retained in the local state file. The command never trades. Run it on a modest schedule (for example every 5–15 minutes); the eventual always-on service can use Coinbase's WebSocket status feed instead of polling.

`pair-scan` compares USD and USDC markets for selected base assets. Its round-trip estimate combines the configured entry/exit fee assumption with a simulated buy and sell through the top ten book levels for `MAX_POSITION_QUOTE`; it also checks that book depth exceeds the configured threshold. Conversion-cost assumptions can be set with `USD_CONVERSION_COST_BPS` and `USDC_CONVERSION_COST_BPS`. This is a screening estimate, not a fee quote: use the actual account tier and order preview before trading, and account for GBP funding or conversions separately.

For capital management, keep one quote currency for the initial BTC/ETH strategy if both markets are sufficiently liquid and their all-in costs are close. Pair scans report both each asset's lowest-cost route and a common quote currency available for all requested assets. Pin that quote choice; do not switch automatically on every scan. If evidence later supports different quotes per asset, use explicit USD and USDC budget caps and only rebalance between them when the conversion cost is lower than the expected benefit. The portfolio can hold more than one quote asset, but the bot should count only its configured, available quote balance toward new entries.

All implemented Coinbase market data, product discovery, fee lookup, and order placement go through the Coinbase for Agents CLI. Portfolio balance reconciliation is the next part of the shared paper/live runtime. Configure the dedicated portfolio ID and CDP key before running Coinbase-backed commands:

```bash
npm install -g @coinbase/coinbase-cli
coinbase env live --key-file /absolute/path/to/cdp-key.json
coinbase env
coinbase balance
coinbase fees product_type==SPOT
```

Create a dedicated Coinbase Advanced portfolio and scope the CDP key to that portfolio. Set `COINBASE_PORTFOLIO_ID` in `.env` to the selected portfolio UUID. Keep the downloaded JSON outside this repository. The official setup reference is [Coinbase for Agents](https://www.coinbase.com/en-gb/blog/coinbase-for-agents) and the [Coinbase CLI/MCP guide](https://docs.cdp.coinbase.com/coinbase-cli/overview).

## Configuration

Copy `.env.example` to `.env`. Important values:

| Variable | Default | Purpose |
|---|---:|---|
| `APP_MODE` | `SHADOW` | `SHADOW`, `PAPER`, or `LIVE` |
| `COINBASE_PRODUCTS` | `BTC-USD,ETH-USD` | fixed trading allowlist |
| `BAR_GRANULARITY` | `ONE_MINUTE` | Coinbase candle granularity |
| `JEV_MODE` | `DETERMINISTIC` | local JEV-compatible decision boundary |
| `ENABLE_LIVE_TRADING` | `false` | second live-trading guard |
| `COINBASE_CLI_ENABLED` | `false` | permits agent execution adapter |
| `DISCOVERY_QUOTE_CURRENCIES` | `USD,USDC` | quote markets compared by pair-scan |
| `MIN_LISTING_DEPTH_QUOTE` | `5000` | minimum top-ten book depth per side for a pair to qualify |
| `USD_CONVERSION_COST_BPS` | `0` | operator-supplied estimated conversion cost for USD funding |
| `USDC_CONVERSION_COST_BPS` | `0` | operator-supplied estimated conversion cost for USDC funding |

The initial JEV implementation is deterministic and auditable. It emits `ACCEPT`, `WATCH`, or `REJECT` with reasons and an input hash. Set `JEV_MODE=HTTP` and add `TYPESAFE_API_KEY` to call Jev at `https://api.typesafe.ai/v1/systemone`; the adapter sends TypeSafe System One `state` plus typed Choice/Score questions for entry and sell-pressure decisions. Request/response pairs are preserved in the report path for replay. Do not call a live endpoint blindly for a month of bars: the runner only calls JEV at each causal entry/position decision.

The backtest is causal: a candle is only visible after it closes, entries occur at that close, exits are checked on later candles, and an open position is closed at the final bar. The report contains every BUY/SELL marker, reason, JEV input hash, P&L, win/loss count, and return on the configured position size.

## Roadmap

1. Validate candle ingestion, setups, JEV decisions, and shadow ledger with BTC/ETH.
2. Add websocket market events and persisted append-only storage.
3. Add replayable decision/outcome evaluation and richer flow/order-book features.
4. Add a Coinbase for Agents order adapter with small, explicit limits and operator confirmation.
5. Add more Coinbase-listed products only after the BTC/ETH paper acceptance gate passes.
