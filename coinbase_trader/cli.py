from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .backtest import load_csv, run, run_trend_momentum, write_csv
from .config import Settings
from .jev import HttpJevDecisionEngine, JevDecisionEngine
from .market import CoinbaseMarketData, observe
from .features import synthetic_coinbase_candles


def main() -> None:
    parser = argparse.ArgumentParser(prog="coinbase-trader")
    subparsers = parser.add_subparsers(dest="command", required=True)
    snapshot = subparsers.add_parser("snapshot")
    snapshot.add_argument("--symbol", default="BTC-USD")
    backtest = subparsers.add_parser("backtest")
    backtest.add_argument("--csv", required=True)
    backtest.add_argument("--symbol", default="BTC-USD")
    backtest.add_argument("--report", default="backtest-result.json")
    download = subparsers.add_parser("download")
    download.add_argument("--symbol", default="BTC-USD")
    download.add_argument("--days", type=int, default=30)
    download.add_argument("--granularity", default="FIVE_MINUTE")
    download.add_argument("--out", required=True)
    dummy = subparsers.add_parser("dummy-backtest")
    dummy.add_argument("--symbol", default="BTC-USD")
    dummy.add_argument("--hours", type=int, default=72)
    dummy.add_argument("--report", default="dummy-trend-backtest.json")
    args = parser.parse_args()
    settings = Settings()
    if args.command == "snapshot":
        symbol = settings.validate_product(args.symbol)
        candles = CoinbaseMarketData().candles(symbol, settings.lookback_bars, settings.granularity)
        observation = observe(candles, symbol)
        engine = HttpJevDecisionEngine() if settings.jev_mode == "HTTP" else JevDecisionEngine()
        print(json.dumps({"observation": observation.__dict__, "decision": engine.decide(observation).__dict__}, default=str, indent=2))
    elif args.command == "download":
        symbol = settings.validate_product(args.symbol)
        end = datetime.now(timezone.utc)
        candles = CoinbaseMarketData().candles_between(symbol, end - timedelta(days=args.days), end, args.granularity)
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        write_csv(candles, args.out)
        print(json.dumps({"symbol": symbol, "bars": len(candles), "out": args.out}, indent=2))
    elif args.command == "backtest":
        symbol = settings.validate_product(args.symbol)
        result = run(load_csv(args.csv, symbol), settings)
        result.write_json(args.report)
        print(json.dumps({"product_id": result.product_id, "bars": result.bars, "entries": result.entries, "exits": result.exits, "wins": result.wins, "losses": result.losses, "final_return": result.final_return, "report": args.report}, indent=2))
    else:
        symbol = settings.validate_product(args.symbol)
        candles = synthetic_coinbase_candles(symbol, args.hours)
        rules_only = run_trend_momentum(candles, settings, use_jev=False)
        with_jev = run_trend_momentum(candles, settings, use_jev=True)
        payload = {"rules_only": as_summary(rules_only), "with_jev": as_summary(with_jev), "bars": len(candles), "symbol": symbol}
        Path(args.report).write_text(json.dumps(payload, indent=2))
        print(json.dumps({**payload, "report": args.report}, indent=2))


def as_summary(result) -> dict:
    return {"entries": result.entries, "exits": result.exits, "wins": result.wins, "losses": result.losses, "final_return": result.final_return, "jev_calls": len(result.jev_calls), "trades": [trade.__dict__ for trade in result.trades]}


if __name__ == "__main__":
    main()
