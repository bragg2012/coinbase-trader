# Quant Trading Vault review for Coinbase Trader

Research date: 2026-09-28

## Recommendation

Use the repository as a source of indicator formulas and strategy hypotheses, not as a production trading system or as a menu of 5,800 strategies to brute-force. Its own README describes the contents as educational/unvalidated research specifications and warns that production execution needs separate order lifecycle, risk, idempotency, reconnect, and test infrastructure. [Vault README](https://github.com/brainbrick-trades/The-Quant-Trading-Vault#risk--disclaimer)

For this project, the efficient design is:

```text
Coinbase events -> closed multi-timeframe bars -> local indicators/features
                                                   |
                                      deterministic setup pre-filter
                                                   |
                                      TypeSafe Jev BUY/WAIT/SELL call
                                                   |
                                      fee/risk/execution gate
```

Jev should see the outputs of several indicators, not raw strategy code. We should not let several strategies independently place trades or use a majority vote as the initial design; that makes attribution and backtesting difficult. Each strategy becomes a named feature family and testable hypothesis, while Jev makes the final contextual decision.

## Best candidates to port first

### 1. Multi-timeframe trend and momentum confirmation

The Vault's multi-timeframe trend strategy scores fast/slow moving-average relationships across timeframes, then confirms with RSI and MACD, ATR stops, and partial/trailing exits. [Strategy spec](https://github.com/brainbrick-trades/The-Quant-Trading-Vault/blob/main/strategies/Multi-Timeframe-Trend-Following-and-Momentum-Confirmation-Quantitative-Trading-Strategy.md)

This is the best first fit. Adapt it to spot-long only:

- 1m: trigger and short-term momentum.
- 5m: primary confirmation.
- 15m: local trend regime.
- 1h: context only.
- Replace the original 50/200 settings with a small, walk-forward-tested parameter set; do not optimise dozens of combinations.
- Feed Jev `trend_score`, MA distances, RSI, MACD state, ATR, and whether the timeframes agree.

### 2. MACD + RSI + range + volume confirmation

The Vault includes a reversal strategy that requires MACD crossover, RSI condition, price outside a range filter, and above-average volume. [Strategy spec](https://github.com/brainbrick-trades/The-Quant-Trading-Vault/blob/main/strategies/Multi-Indicator-Momentum-and-Volume-Based-Trend-Reversal-Strategy.md)

This maps well to Coinbase data because candles provide OHLCV and the live feed can add trade flow. Use it as an entry pre-filter or a reversal feature, not as a standalone order generator. It will likely be too restrictive on 1m and more useful on 5m/15m.

### 3. Bollinger + RSI + ATR mean reversion

The Vault's mean-reversion strategy combines Bollinger Bands, RSI, and ATR-based stops/targets. [Strategy spec](https://github.com/brainbrick-trades/The-Quant-Trading-Vault/blob/main/strategies/Mean-Reversion-Strategy-with-Bollinger-Bands-RSI-and-ATR-Based-Dynamic-Stop-Loss-System.md)

This should be tested as a separate range-regime strategy. It is dangerous to blend it blindly with trend-following: buying lower-band weakness is often exactly wrong during a strong downtrend. Add a regime gate such as higher-timeframe trend score near neutral before this feature can support a BUY.

### 4. RSI-VWAP

The RSI-VWAP strategy is simple and long-only, which makes it directionally compatible with spot trading. [Strategy spec](https://github.com/brainbrick-trades/The-Quant-Trading-Vault/blob/main/strategies/RSI-VWAP-Short-term-Quant-Strategy.md)

It is useful as a single feature (`rsi_vwap`, `crossed_oversold`, `crossed_overbought`) and as a low-complexity baseline. It should not be treated as stronger evidence than flow, spread, and multi-timeframe alignment.

## Deprioritise or exclude initially

- Heatmap/sniper systems: the cited spec uses long-term weekly/monthly context and has high-frequency/slippage assumptions that do not map cleanly to the first BTC/ETH spot loop. [Strategy spec](https://github.com/brainbrick-trades/The-Quant-Trading-Vault/blob/main/strategies/High-Frequency-Quantitative-Multi-Timeframe-Heatmap-Sniper-Strategy.md)
- Fixed-time entries: crypto trades continuously; a clock-based entry is not an evidence-based setup for this system. [Strategy spec](https://github.com/brainbrick-trades/The-Quant-Trading-Vault/blob/main/strategies/Time-based-Strategy-with-ATR-Take-Profit.md)
- Futures, leverage, shorting, grid, market making, and arbitrage strategies: these introduce execution and inventory assumptions outside the current spot-long BTC/ETH scope.
- Any strategy whose source says Binance, futures, or SOL without first translating the market, order type, and fee assumptions.

## How to test the strategies with Jev

Run a controlled matrix, not an unconstrained strategy sweep:

| Variant | Local features | Jev | Purpose |
|---|---|---|---|
| Baseline | none beyond price/flow | no | Measures whether the plumbing has accidental edge |
| Strategy-only | one strategy family | no | Tests raw signal quality |
| Jev-only | snapshot features | yes | Tests Jev's contextual judgement |
| Strategy + Jev | one family + full snapshot | yes | Tests whether the strategy improves Jev selection |
| Strategy + Jev + exits | above + fee-aware stops/trailing | yes | Realistic paper candidate |

For each variant, test BTC-USD and ETH-USD separately across 1m-trigger/5m-confirmation and 5m-trigger/15m-confirmation. Keep 1h as context first. Report net return after entry/exit fees, spread, slippage, number of trades, win rate, average win/loss, profit factor, max drawdown, time in market, and performance by regime.

Use walk-forward splits: tune only on an earlier period, freeze parameters, then evaluate on a later period. Cache each Jev request/response by input hash so replay uses the exact historical judgement and does not silently change because the model or prompt changed.

## Proposed feature contract

The local feature engine should emit versioned fields such as:

- `trend_score_1m_5m_15m_1h`
- `ema_fast_slow_distance_bps` per timeframe
- `rsi`, `macd_line`, `macd_signal`, `macd_histogram`
- `bb_position`, `bb_width`, `vwap_distance_bps`
- `atr_bps` and ATR-derived stop distance
- `volume_z`, buy/sell notional ratio, trade-count imbalance
- order-book imbalance and spread bps
- `regime`: `TREND_UP`, `TREND_DOWN`, `RANGE`, or `UNCERTAIN`
- `estimated_round_trip_fee_bps`, `estimated_slippage_bps`, and `net_target_edge_bps`

Jev then answers atomic questions: entry `BUY/WAIT/REJECT`, entry quality, risk flag, exit `SELL/HOLD`, and sell pressure. The code remains responsible for hard stops, maximum loss, minimum net edge, stale-data denial, and order sizing.

## Bottom line

There is useful material here, especially the multi-timeframe trend/momentum, MACD/RSI/volume confirmation, Bollinger/RSI/ATR mean reversion, and RSI-VWAP ideas. The better experiment is to port those four as small, auditable feature modules and test each with and without Jev. We should not import AgentKit, futures logic, or the repository's execution assumptions, and we should not combine all indicators into one opaque score before measuring each family independently.

