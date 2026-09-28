from __future__ import annotations

import argparse
import json

from .backtest import load_csv, run
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
    args = parser.parse_args()
    settings = Settings()
    if args.command == "snapshot":
        symbol = settings.validate_product(args.symbol)
        candles = CoinbaseMarketData().candles(symbol, settings.lookback_bars, settings.granularity)
        observation = observe(candles, symbol)
        print(json.dumps({"observation": observation.__dict__, "decision": JevDecisionEngine().decide(observation).__dict__}, default=str, indent=2))
    else:
        symbol = settings.validate_product(args.symbol)
        result = run(load_csv(args.csv, symbol), settings)
        print(json.dumps(result.__dict__, indent=2))

