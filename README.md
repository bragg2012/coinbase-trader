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
python -m coinbase_trader.cli backtest --csv examples/btc-usd-1m.csv --symbol BTC-USD
pytest -q
```

Market data uses Coinbase Advanced Trade's public candles endpoint, so the snapshot and backtest paths do not need credentials. For the execution path, install and configure Coinbase for Agents separately:

```bash
npm install -g @coinbase/coinbase-cli
coinbase env live --key-file /absolute/path/to/cdp-key.json
coinbase env
coinbase balance
```

Create a dedicated Coinbase Advanced portfolio and scope the CDP key to that portfolio. Keep the downloaded JSON outside this repository. The official setup reference is [Coinbase for Agents](https://www.coinbase.com/en-gb/blog/coinbase-for-agents) and the [Coinbase CLI/MCP guide](https://docs.cdp.coinbase.com/coinbase-cli/skill.md).

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

The initial JEV implementation is deterministic and auditable. It emits `ACCEPT`, `WATCH`, or `REJECT` with reasons and an input hash. A future JEV service/model can replace the decision provider without changing market, risk, backtest, or ledger contracts.

## Roadmap

1. Validate candle ingestion, setups, JEV decisions, and shadow ledger with BTC/ETH.
2. Add websocket market events and persisted append-only storage.
3. Add replayable decision/outcome evaluation and richer flow/order-book features.
4. Add a Coinbase for Agents order adapter with small, explicit limits and operator confirmation.
5. Add more Coinbase-listed products only after the BTC/ETH paper acceptance gate passes.

