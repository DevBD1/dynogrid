from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict

from dynogrid.config import config_hash, load_config
from dynogrid.engine import run_historical, run_live_paper
from dynogrid.persistence.sqlite import SQLiteRepository


def main() -> None:
    parser = argparse.ArgumentParser(prog="dynogrid")
    parser.add_argument("--config", default="config.example.yaml")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("config-check")

    run_paper = subparsers.add_parser("run-paper")
    run_paper.add_argument("--candles", required=True)
    run_paper.add_argument("--cycles", type=int)
    run_paper.add_argument("--sleep", action="store_true")

    live_paper = subparsers.add_parser("run-live-paper")
    live_paper.add_argument("--cycles", type=int)

    backtest = subparsers.add_parser("backtest")
    backtest.add_argument("--candles", required=True)
    backtest.add_argument("--cycles", type=int)

    subparsers.add_parser("status")
    subparsers.add_parser("pause")
    subparsers.add_parser("resume")
    subparsers.add_parser("flatten")

    args = parser.parse_args()
    asyncio.run(_run(args))


async def _run(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    repository = SQLiteRepository(config.db_path)

    if args.command == "config-check":
        print(json.dumps({"ok": True, "config_hash": config_hash(config), "config": asdict(config)}, indent=2))
        return

    if args.command == "run-paper":
        run_id = await run_historical(
            config_path=args.config,
            candles_path=args.candles,
            mode="paper",
            max_cycles=args.cycles,
            sleep=args.sleep,
        )
        print(json.dumps({"run_id": run_id, "mode": "paper"}, indent=2))
        return

    if args.command == "run-live-paper":
        run_id = await run_live_paper(
            config_path=args.config,
            max_cycles=args.cycles,
        )
        print(json.dumps({"run_id": run_id, "mode": "live-paper"}, indent=2))
        return

    if args.command == "backtest":
        run_id = await run_historical(
            config_path=args.config,
            candles_path=args.candles,
            mode="backtest",
            max_cycles=args.cycles,
            sleep=False,
        )
        print(json.dumps({"run_id": run_id, "mode": "backtest"}, indent=2))
        return

    await repository.init()

    if args.command == "status":
        print(json.dumps(await repository.latest_status(), indent=2, sort_keys=True))
        return

    if args.command == "pause":
        await repository.set_runtime_state("paused", "1")
        await repository.event(None, "operator", "paused")
        print(json.dumps({"paused": True}, indent=2))
        return

    if args.command == "resume":
        await repository.set_runtime_state("paused", "0")
        await repository.event(None, "operator", "resumed")
        print(json.dumps({"paused": False}, indent=2))
        return

    if args.command == "flatten":
        await repository.set_runtime_state("flatten_requested", "1")
        await repository.event(None, "operator", "flatten requested")
        print(json.dumps({"flatten_requested": True}, indent=2))
        return

    raise ValueError(f"unknown command: {args.command}")


if __name__ == "__main__":
    main()
