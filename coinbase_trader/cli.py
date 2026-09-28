from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .backtest import load_csv, run, write_csv
from .config import Settings
from .jev import JevDecisionEngine
from .market import CoinbaseMarketData, observe


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
    args = parser.parse_args()
    settings = Settings()
    if args.command == "snapshot":
        symbol = settings.validate_product(args.symbol)
        candles = CoinbaseMarketData().candles(symbol, settings.lookback_bars, settings.granularity)
        observation = observe(candles, symbol)
        print(json.dumps({"observation": observation.__dict__, "decision": JevDecisionEngine().decide(observation).__dict__}, default=str, indent=2))
    elif args.command == "download":
        symbol = settings.validate_product(args.symbol)
        end = datetime.now(timezone.utc)
        candles = CoinbaseMarketData().candles_between(symbol, end - timedelta(days=args.days), end, args.granularity)
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        write_csv(candles, args.out)
        print(json.dumps({"symbol": symbol, "bars": len(candles), "out": args.out}, indent=2))
    else:
        symbol = settings.validate_product(args.symbol)
        result = run(load_csv(args.csv, symbol), settings)
        result.write_json(args.report)
        print(json.dumps({"product_id": result.product_id, "bars": result.bars, "entries": result.entries, "exits": result.exits, "wins": result.wins, "losses": result.losses, "final_return": result.final_return, "report": args.report}, indent=2))


if __name__ == "__main__":
    main()
