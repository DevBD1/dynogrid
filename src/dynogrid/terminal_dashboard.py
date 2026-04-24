from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from rich import box
from rich.console import Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from dynogrid.persistence.sqlite import SQLiteRepository


async def watch_run(
    repository: SQLiteRepository,
    run_id: int,
    engine_task: asyncio.Task[None],
    refresh_seconds: float,
) -> None:
    with Live(
        await render_dashboard(repository, run_id),
        refresh_per_second=max(1.0 / refresh_seconds, 0.2),
        screen=True,
    ) as live:
        while not engine_task.done():
            await asyncio.sleep(refresh_seconds)
            live.update(await render_dashboard(repository, run_id))
        await engine_task
        live.update(await render_dashboard(repository, run_id))


async def render_dashboard(repository: SQLiteRepository, run_id: int) -> Group:
    data = await repository.watch_snapshot(run_id)
    return Group(
        _header(data),
        _balance_panel(data.get("balance")),
        _strategy_panel(data.get("snapshot"), data.get("metrics")),
        _orders_panel(data.get("orders", [])),
        _fills_panel(data.get("fills", [])),
        _process_panel(data),
        Panel("Ctrl+C stop | separate terminal: pause, resume, flatten, orders, fills"),
    )


def _header(data: dict[str, Any]) -> Panel:
    run = data["run"]
    paused = "yes" if data.get("paused") else "no"
    refreshed = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    text = Text()
    text.append(f"DynoGrid run={run['id']} ", style="bold cyan")
    text.append(f"mode={run['mode']} symbol={run['symbol']} status={run['status']} ")
    text.append(f"paused={paused} refreshed={refreshed}")
    return Panel(text, box=box.SIMPLE)


def _balance_panel(balance: dict[str, Any] | None) -> Panel:
    table = Table(box=box.SIMPLE, expand=True)
    for column in ("equity", "base_free", "base_locked", "quote_free", "quote_locked"):
        table.add_column(column)
    if balance:
        table.add_row(
            _money(balance["equity"]),
            _qty(balance["base_free"]),
            _qty(balance["base_locked"]),
            _money(balance["quote_free"]),
            _money(balance["quote_locked"]),
        )
    else:
        table.add_row("waiting", "-", "-", "-", "-")
    return Panel(table, title="Live Balances")


def _strategy_panel(
    snapshot: dict[str, Any] | None, metrics: dict[str, Any] | None
) -> Panel:
    table = Table(box=box.SIMPLE, expand=True)
    for column in (
        "last_candle",
        "bias",
        "center",
        "spacing",
        "trend",
        "ev",
        "skew_cost",
    ):
        table.add_column(column)
    if snapshot:
        table.add_row(
            str(snapshot["timestamp"]),
            str(snapshot["bias"]),
            _money(snapshot["center_price"]),
            _money(snapshot["spacing"]),
            str(metrics["trend_state"]) if metrics else "-",
            str(bool(metrics["ev_positive"])) if metrics else "-",
            _qty(metrics["inventory_skew_cost_quote"]) if metrics else "-",
        )
    else:
        table.add_row("waiting", "-", "-", "-", "-", "-", "-")
    return Panel(table, title="Strategy")


def _orders_panel(orders: list[dict[str, Any]]) -> Panel:
    table = Table(box=box.SIMPLE, expand=True)
    for column in ("side", "price", "qty", "updated", "client_order_id"):
        table.add_column(column)
    for order in orders[:10]:
        table.add_row(
            str(order["side"]),
            _money(order["price"]),
            _qty(order["quantity"]),
            str(order["updated_at"]),
            str(order["client_order_id"]),
        )
    if not orders:
        table.add_row("none", "-", "-", "-", "-")
    return Panel(table, title="Active Paper Orders")


def _fills_panel(fills: list[dict[str, Any]]) -> Panel:
    table = Table(box=box.SIMPLE, expand=True)
    for column in ("time", "side", "price", "qty", "fee", "client_order_id"):
        table.add_column(column)
    for fill in fills[:10]:
        table.add_row(
            str(fill["timestamp"]),
            str(fill["side"]),
            _money(fill["price"]),
            _qty(fill["quantity"]),
            _qty(fill["fee"]),
            str(fill["client_order_id"]),
        )
    if not fills:
        table.add_row("none", "-", "-", "-", "-", "-")
    return Panel(table, title="Recent Executions")


def _process_panel(data: dict[str, Any]) -> Panel:
    run = data["run"]
    snapshot = data.get("snapshot")
    order_counts = data.get("order_counts", {})
    events = data.get("events", [])
    table = Table(box=box.SIMPLE, expand=True)
    table.add_column("key")
    table.add_column("value")
    table.add_row("started_at", str(run["started_at"]))
    table.add_row("finished_at", str(run["finished_at"] or "-"))
    table.add_row("last_cycle", str(snapshot["timestamp"]) if snapshot else "waiting")
    table.add_row("open_orders", str(order_counts.get("open", 0)))
    table.add_row("filled_orders", str(order_counts.get("filled", 0)))
    table.add_row("canceled_orders", str(order_counts.get("canceled", 0)))
    table.add_row("fills", str(data.get("fill_count", 0)))
    metrics = data.get("metrics")
    if metrics:
        table.add_row("volatility_ratio", f"{float(metrics['volatility_ratio']):.4f}")
        table.add_row("buy_spacing", _money(metrics["buy_spacing"]))
        table.add_row("sell_spacing", _money(metrics["sell_spacing"]))
        table.add_row("exit_signal", str(metrics["exit_signal"] or "-"))
    if events:
        latest = events[0]
        table.add_row("latest_event", f"{latest['event_type']}: {latest['message']}")
    else:
        table.add_row("latest_event", "-")
    return Panel(table, title="Process")


def _money(value: object) -> str:
    return f"{float(value):.2f}"


def _qty(value: object) -> str:
    return f"{float(value):.8f}"
