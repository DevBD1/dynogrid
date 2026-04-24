from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from dynogrid.config import config_hash, load_config
from dynogrid.engine import run_historical, run_live_paper
from dynogrid.persistence.sqlite import SQLiteRepository


def main() -> None:
    parser = argparse.ArgumentParser(prog="dynogrid")
    parser.add_argument("--config", default="config.example.yaml")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
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
    performance = subparsers.add_parser("performance")
    performance.add_argument("--run-id", type=int, required=True)
    subparsers.add_parser("pause")
    subparsers.add_parser("resume")
    subparsers.add_parser("flatten")

    args = parser.parse_args()
    asyncio.run(_run(args))


async def _run(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    repository = SQLiteRepository(config.db_path)

    if args.command == "config-check":
        _print(
            args,
            {"ok": True, "config_hash": config_hash(config), "config": asdict(config)},
            "Config OK\n"
            f"symbol={config.symbol} timeframe={config.timeframe} "
            f"db={config.db_path} hash={config_hash(config)}",
        )
        return

    if args.command == "run-paper":
        run_id = await run_historical(
            config_path=args.config,
            candles_path=args.candles,
            mode="paper",
            max_cycles=args.cycles,
            sleep=args.sleep,
            reporter=None if args.json else _progress,
        )
        _print(args, {"run_id": run_id, "mode": "paper"}, f"run {run_id} finished in paper mode")
        return

    if args.command == "run-live-paper":
        run_id = await run_live_paper(
            config_path=args.config,
            max_cycles=args.cycles,
            reporter=None if args.json else _progress,
        )
        _print(args, {"run_id": run_id, "mode": "live-paper"}, f"run {run_id} finished in live-paper mode")
        return

    if args.command == "backtest":
        run_id = await run_historical(
            config_path=args.config,
            candles_path=args.candles,
            mode="backtest",
            max_cycles=args.cycles,
            sleep=False,
            reporter=None if args.json else _progress,
        )
        _print(args, {"run_id": run_id, "mode": "backtest"}, f"run {run_id} finished in backtest mode")
        return

    await repository.init()

    if args.command == "status":
        status = await repository.latest_status()
        _print(args, status, _format_status(status))
        return

    if args.command == "performance":
        performance = await repository.performance(args.run_id)
        _print(args, performance, _format_performance(performance))
        return

    if args.command == "pause":
        await repository.set_runtime_state("paused", "1")
        await repository.event(None, "operator", "paused")
        _print(args, {"paused": True}, "paused")
        return

    if args.command == "resume":
        await repository.set_runtime_state("paused", "0")
        await repository.event(None, "operator", "resumed")
        _print(args, {"paused": False}, "resumed")
        return

    if args.command == "flatten":
        await repository.set_runtime_state("flatten_requested", "1")
        await repository.event(None, "operator", "flatten requested")
        _print(args, {"flatten_requested": True}, "flatten requested")
        return

    raise ValueError(f"unknown command: {args.command}")


def _progress(message: str) -> None:
    print(f"[{_now()}] {message}", flush=True)


def _print(args: argparse.Namespace, payload: dict[str, Any], human: str) -> None:
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(human)


def _format_status(status: dict[str, Any]) -> str:
    run = status.get("run") or {}
    balance = status.get("balance") or {}
    snapshot = status.get("snapshot") or {}
    if not run:
        return "No runs found."
    lines = [
        f"Run {run.get('id')} {run.get('mode')} {run.get('status')} {run.get('symbol')}",
        f"paused={status.get('paused')} open_orders={status.get('open_orders')}",
    ]
    if balance:
        lines.append(
            "equity={equity:.2f} base_free={base_free:.8f} "
            "quote_free={quote_free:.2f} quote_locked={quote_locked:.2f}".format(**balance)
        )
    if snapshot:
        lines.append(
            "last_candle={timestamp} bias={bias} center={center_price:.2f} "
            "spacing={spacing:.2f} desired_orders={desired_order_count}".format(**snapshot)
        )
    return "\n".join(lines)


def _format_performance(performance: dict[str, Any]) -> str:
    run = performance["run"]
    fills = performance.get("fills", {})
    orders = performance.get("orders", {})
    last_balance = performance.get("last_balance") or {}
    return "\n".join(
        [
            f"Run {run['id']} {run['mode']} {run['status']} {run['symbol']}",
            f"cycles={performance['cycles']} balance_rows={performance['balance_rows']}",
            "start_equity={start_equity:.2f} end_equity={end_equity:.2f} "
            "pnl={pnl:.2f} pnl_pct={pnl_pct:.4f}%".format(**performance),
            "min_equity={min_equity:.2f} max_equity={max_equity:.2f} "
            "max_drawdown={max_drawdown:.2f} max_drawdown_pct={max_drawdown_pct:.4f}%".format(
                **performance
            ),
            "fills={fill_count} bought_qty={bought_qty:.8f} "
            "sold_qty={sold_qty:.8f} fees={total_fees:.8f}".format(
                fill_count=int(fills.get("fill_count", 0)),
                bought_qty=float(fills.get("bought_qty", 0.0)),
                sold_qty=float(fills.get("sold_qty", 0.0)),
                total_fees=float(fills.get("total_fees", 0.0)),
            ),
            f"orders={orders}",
            "last_balance base_free={base_free:.8f} quote_free={quote_free:.2f} "
            "base_locked={base_locked:.8f} quote_locked={quote_locked:.2f}".format(
                **last_balance
            )
            if last_balance
            else "last_balance unavailable",
        ]
    )


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


if __name__ == "__main__":
    main()
