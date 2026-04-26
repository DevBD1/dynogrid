from __future__ import annotations

import argparse
import asyncio
import json
from contextlib import suppress
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from dynogrid.config import config_hash, load_config
from dynogrid.engine import prepare_live_paper_engine, run_historical, run_live, run_live_paper
from dynogrid.exchange.ccxt_binance import LiveTradingDisabledError
from dynogrid.persistence.sqlite import SQLiteRepository
from dynogrid.terminal_dashboard import watch_run


def build_parser() -> argparse.ArgumentParser:
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
    live_paper.add_argument("--watch", action="store_true")
    live_paper.add_argument("--refresh", type=float, default=2.0)

    live = subparsers.add_parser("run-live")
    live.add_argument("--cycles", type=int)

    backtest = subparsers.add_parser("backtest")
    backtest.add_argument("--candles", required=True)
    backtest.add_argument("--cycles", type=int)

    subparsers.add_parser("status")
    performance = subparsers.add_parser("performance")
    performance.add_argument("--run-id", type=int, required=True)
    orders = subparsers.add_parser("orders")
    orders.add_argument("--run-id", type=int)
    orders.add_argument(
        "--status",
        choices=("open", "filled", "canceled", "all"),
        default="open",
    )
    fills = subparsers.add_parser("fills")
    fills.add_argument("--run-id", type=int)
    fills.add_argument("--limit", type=int, default=20)
    subparsers.add_parser("pause")
    subparsers.add_parser("resume")
    subparsers.add_parser("flatten")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        asyncio.run(_run(args))
    except KeyboardInterrupt:
        if not args.json:
            print("\nstopped")


async def _run(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    repository = SQLiteRepository(config.db_path)

    if args.command == "config-check":
        _print(
            args,
            {"ok": True, "config_hash": config_hash(config), "config": asdict(config)},
            "Config OK\n"
            f"symbol={config.symbol} timeframe={config.timeframe} "
            f"strategy_timeframe={config.strategy_timeframe} "
            f"db={config.db_path} hash={config_hash(config)}\n"
            f"grid_count={config.grid_count} atr_multiplier={config.atr_multiplier} "
            f"order_size={config.order_size}\n"
            f"recenter_hysteresis_pct={config.recenter_hysteresis_pct} "
            f"spacing_hysteresis_pct={config.spacing_hysteresis_pct} "
            f"atr_fast_period={config.atr_fast_period} atr_slow_period={config.atr_slow_period}\n"
            "paper_ev_mode=maker_only_roundtrip "
            f"taker_fee_rate={config.taker_fee_rate} "
            f"simulated_slippage_bps={config.simulated_slippage_bps} "
            f"ev_safety_multiplier={config.ev_safety_multiplier} "
            f"max_ev_spacing_pct={config.max_ev_spacing_pct}\n"
            f"bias_mode={config.bias_mode} ema_fast_period={config.ema_fast_period} "
            f"ema_slow_period={config.ema_slow_period} "
            f"outside_band_consecutive={config.outside_band_consecutive}\n"
            f"structure_lookback={config.structure_lookback} "
            f"structure_break_atr_buffer={config.structure_break_atr_buffer} "
            f"inventory_spacing_threshold={config.inventory_spacing_threshold} "
            f"inventory_spacing_max_multiplier={config.inventory_spacing_max_multiplier}",
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
        await _print_run_result(args, repository, run_id, "paper")
        return

    if args.command == "run-live-paper":
        if args.json and args.watch:
            _print(
                args,
                {"ok": False, "error": "--json cannot be used with --watch"},
                "--json cannot be used with --watch",
            )
            raise SystemExit(2)
        if args.watch:
            if args.refresh <= 0:
                _print(
                    args,
                    {"ok": False, "error": "--refresh must be > 0"},
                    "--refresh must be > 0",
                )
                raise SystemExit(2)
            repository, run_id, engine = await prepare_live_paper_engine(
                config_path=args.config,
                reporter=None,
            )
            engine_task = asyncio.create_task(
                engine.run(max_cycles=args.cycles, sleep=False)
            )
            try:
                await watch_run(repository, run_id, engine_task, args.refresh)
            except asyncio.CancelledError:
                engine_task.cancel()
                with suppress(asyncio.CancelledError):
                    await engine_task
                raise
            if not engine_task.cancelled():
                await _print_run_result(args, repository, run_id, "live-paper")
            return

        run_id = await run_live_paper(
            config_path=args.config,
            max_cycles=args.cycles,
            reporter=None if args.json else _progress,
        )
        await _print_run_result(args, repository, run_id, "live-paper")
        return

    if args.command == "run-live":
        try:
            await run_live(
                config_path=args.config,
                max_cycles=args.cycles,
                reporter=None if args.json else _progress,
            )
        except LiveTradingDisabledError as exc:
            _print(args, {"ok": False, "error": str(exc)}, str(exc))
            raise SystemExit(2) from exc
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
        await _print_run_result(args, repository, run_id, "backtest")
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

    if args.command == "orders":
        orders = await repository.list_orders(run_id=args.run_id, status=args.status)
        _print(args, {"orders": orders}, _format_orders(orders, args.status))
        return

    if args.command == "fills":
        fills = await repository.list_fills(run_id=args.run_id, limit=args.limit)
        _print(args, {"fills": fills}, _format_fills(fills))
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


async def _print_run_result(
    args: argparse.Namespace, repository: SQLiteRepository, run_id: int, mode: str
) -> None:
    performance = await repository.performance(run_id)
    _print(
        args,
        {"run_id": run_id, "mode": mode, "performance": performance},
        f"run {run_id} finished in {mode} mode\n\n{_format_performance(performance)}",
    )


def _print(args: argparse.Namespace, payload: Any, human: str) -> None:
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(human)


def _format_status(status: dict[str, Any]) -> str:
    run = status.get("run") or {}
    balance = status.get("balance") or {}
    snapshot = status.get("snapshot") or {}
    metrics = status.get("metrics") or {}
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
    if metrics:
        metric_values = dict(metrics)
        metric_values["ev_positive"] = bool(metrics["ev_positive"])
        lines.append(
            "ev_positive={ev_positive} trend={trend_state} volatility_ratio={volatility_ratio:.4f} "
            "buy_spacing={buy_spacing:.2f} sell_spacing={sell_spacing:.2f} "
            "skew_cost={inventory_skew_cost_quote:.8f} exit_signal={exit_signal}".format(
                **metric_values,
            )
        )
    return "\n".join(lines)


def _format_performance(performance: dict[str, Any]) -> str:
    run = performance["run"]
    fills = performance.get("fills", {})
    orders = performance.get("orders", {})
    metrics = performance.get("metrics", {})
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
            "ev_pauses={ev_pause_count} stop_events={stop_events} "
            "skew_cost={skew_cost:.8f}".format(
                ev_pause_count=int(metrics.get("ev_pause_count", 0)),
                stop_events=int(metrics.get("stop_events", 0)),
                skew_cost=float(metrics.get("skew_cost", 0.0)),
            ),
            "last_balance base_free={base_free:.8f} quote_free={quote_free:.2f} "
            "base_locked={base_locked:.8f} quote_locked={quote_locked:.2f}".format(
                **last_balance
            )
            if last_balance
            else "last_balance unavailable",
        ]
    )


def _format_orders(orders: list[dict[str, Any]], status: str) -> str:
    if not orders:
        if status == "all":
            return "No orders found."
        return f"No {status} orders found."
    lines = [_table_header(["side", "price", "qty", "status", "updated", "client_order_id"])]
    for order in orders:
        lines.append(
            _table_row(
                [
                    str(order["side"]),
                    f"{float(order['price']):.2f}",
                    f"{float(order['quantity']):.8f}",
                    str(order["status"]),
                    str(order["updated_at"]),
                    str(order["client_order_id"]),
                ]
            )
        )
    return "\n".join(lines)


def _format_fills(fills: list[dict[str, Any]]) -> str:
    if not fills:
        return "No fills found."
    lines = [_table_header(["time", "side", "price", "qty", "fee", "client_order_id"])]
    for fill in fills:
        lines.append(
            _table_row(
                [
                    str(fill["timestamp"]),
                    str(fill["side"]),
                    f"{float(fill['price']):.2f}",
                    f"{float(fill['quantity']):.8f}",
                    f"{float(fill['fee']):.8f}",
                    str(fill["client_order_id"]),
                ]
            )
        )
    return "\n".join(lines)


def _table_header(columns: list[str]) -> str:
    return _table_row(columns)


def _table_row(values: list[str]) -> str:
    widths = [6, 12, 12, 10, 12, 0]
    padded = [
        value.ljust(width) if width else value
        for value, width in zip(values, widths, strict=True)
    ]
    return "  ".join(padded)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


if __name__ == "__main__":
    main()
