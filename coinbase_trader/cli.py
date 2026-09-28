from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .backtest import load_csv, run, run_trend_momentum, write_csv
from .config import Settings
from .jev import HttpJevDecisionEngine, JevDecisionEngine
from .market import CoinbaseMarketData, observe
from .features import synthetic_coinbase_candles
from .listings import CoinbaseAdvancedPublic, rank_quote_pairs, scan_new_listings


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
    listings = subparsers.add_parser("listing-scan", help="diff Coinbase spot listings/status into a shadow candidate report")
    listings.add_argument("--state", default="storage/listing-catalog.json")
    listings.add_argument("--report", default="reports/listing-scan.json")
    pair_scan = subparsers.add_parser("pair-scan", help="compare USD/USDC quote books and report the lowest-cost eligible routes")
    pair_scan.add_argument("--assets", default="")
    pair_scan.add_argument("--report", default="reports/quote-pair-scan.json")
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
    elif args.command == "dummy-backtest":
        symbol = settings.validate_product(args.symbol)
        candles = synthetic_coinbase_candles(symbol, args.hours)
        rules_only = run_trend_momentum(candles, settings, use_jev=False)
        with_jev = run_trend_momentum(candles, settings, use_jev=True)
        payload = {"rules_only": as_summary(rules_only), "with_jev": as_summary(with_jev), "bars": len(candles), "symbol": symbol}
        Path(args.report).write_text(json.dumps(payload, indent=2))
        print(json.dumps({**payload, "report": args.report}, indent=2))
    elif args.command == "listing-scan":
        client = CoinbaseAdvancedPublic()
        result = scan_new_listings(client.products(), args.state)
        result["report"] = args.report
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps(result, indent=2))
        print(json.dumps(result, indent=2))
    else:
        client = CoinbaseAdvancedPublic()
        products = client.products()
        assets = tuple(item.strip().upper() for item in args.assets.split(",") if item.strip()) or tuple(sorted({item.split("-", 1)[0] for item in settings.products}))
        conversion_costs = {"USD": settings.usd_conversion_cost_bps, "USDC": settings.usdc_conversion_cost_bps}
        by_asset = {}
        for asset in assets:
            ranked = rank_quote_pairs(products, asset, client, quotes=settings.discovery_quote_currencies, entry_fee_rate=settings.entry_fee_rate, exit_fee_rate=settings.exit_fee_rate, target_quote=settings.max_position_quote, min_depth_quote=settings.min_listing_depth_quote, conversion_cost_bps=conversion_costs)
            by_asset[asset] = [asdict(item) for item in ranked]
        common = {}
        for quote in settings.discovery_quote_currencies:
            best_costs = [next((row["estimated_round_trip_bps"] for row in by_asset[asset] if row["quote"] == quote and row["eligible"]), None) for asset in assets]
            if best_costs and all(cost is not None for cost in best_costs):
                common[quote] = sum(best_costs) / len(best_costs)
        common_quote = min(common, key=common.get) if common else None
        result = {"assets": list(assets), "entry_fee_rate_assumption": settings.entry_fee_rate, "exit_fee_rate_assumption": settings.exit_fee_rate, "conversion_cost_bps_assumptions": conversion_costs, "min_top10_depth_quote": settings.min_listing_depth_quote, "per_asset_rankings": by_asset, "common_quote_cost_bps": common, "recommended_common_quote": common_quote, "policy": "report-only; pin a selected quote per asset or use the common quote policy before funding; never rotate quotes automatically"}
        result["report"] = args.report
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps(result, indent=2))
        print(json.dumps(result, indent=2))


def as_summary(result) -> dict:
    return {"entries": result.entries, "exits": result.exits, "wins": result.wins, "losses": result.losses, "final_return": result.final_return, "jev_calls": len(result.jev_calls), "trades": [trade.__dict__ for trade in result.trades]}


if __name__ == "__main__":
    main()
