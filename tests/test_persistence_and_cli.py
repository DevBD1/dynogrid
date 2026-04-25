from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import asyncio
from pathlib import Path

import pytest
import yaml

from dynogrid.cli import build_parser
from dynogrid.config import load_config
from dynogrid.engine import DynoGridEngine
from dynogrid.exchange.paper import PaperExchangeGateway
from dynogrid.market_data import aggregate_candles
from dynogrid.models import Balance, Bias, Candle, Fill, GridState, Order, OrderStatus, Side
from dynogrid.persistence.sqlite import SQLiteRepository


class BlockingMarketDataSource:
    def __init__(self) -> None:
        self.closed = False

    async def next_candle(self) -> Candle | None:
        await asyncio.Event().wait()
        return None

    async def close(self) -> None:
        self.closed = True


class ListMarketDataSource:
    def __init__(self, candles: list[Candle]) -> None:
        self.candles = candles
        self.closed = False

    async def next_candle(self) -> Candle | None:
        if not self.candles:
            return None
        return self.candles.pop(0)

    async def close(self) -> None:
        self.closed = True


def minute_candles(count: int, start: int = 1700000000, close: float = 100.0) -> list[Candle]:
    return [
        Candle(start + index * 60, close, close + 1.0, close - 1.0, close, 1.0)
        for index in range(count)
    ]


def write_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "config.yaml"
    payload = {
        "symbol": "BTC/USDT",
        "timeframe": "1m",
        "exchange_id": "binance",
        "db_path": str(tmp_path / "dynogrid.sqlite3"),
        "grid_count": 2,
        "atr_multiplier": 1.0,
        "order_size": 0.01,
        "max_inventory": 0.03,
        "maker_fee_rate": 0.001,
        "starting_base": 0.0,
        "starting_quote": 1000.0,
        "price_precision": 2,
        "quantity_precision": 6,
        "min_price": 1.0,
        "min_quantity": 0.0001,
        "loop_interval_seconds": 60,
    }
    config_path.write_text(yaml.safe_dump(payload))
    return config_path


def test_aggregate_candles_builds_complete_5m_bars_only() -> None:
    sample = [
        Candle(0, 100.0, 101.0, 99.0, 100.5, 1.0),
        Candle(60, 100.5, 102.0, 100.0, 101.0, 2.0),
        Candle(120, 101.0, 103.0, 100.5, 102.0, 3.0),
        Candle(180, 102.0, 104.0, 101.5, 103.0, 4.0),
        Candle(240, 103.0, 105.0, 102.5, 104.0, 5.0),
        Candle(300, 104.0, 106.0, 103.5, 105.0, 6.0),
    ]

    aggregated = aggregate_candles(sample, "5m")

    assert len(aggregated) == 1
    assert aggregated[0] == Candle(0, 100.0, 105.0, 99.0, 104.0, 15.0)


@pytest.mark.asyncio
async def test_sqlite_round_trip_for_core_tables(tmp_path: Path) -> None:
    config_path = write_config(tmp_path)
    config = load_config(config_path)
    repo = SQLiteRepository(config.db_path)

    await repo.init()
    run_id = await repo.create_run("test", config)
    candle = Candle(1, 100.0, 101.0, 99.0, 100.0, 1.0)
    await repo.persist_candle(run_id, config.symbol, candle)
    await repo.persist_balance(run_id, 1, Balance(0.0, 1000.0), 1000.0)
    await repo.persist_strategy_metrics(
        run_id,
        1,
        GridState(
            center_price=100.0,
            spacing=1.0,
            bias=Bias.NEUTRAL,
            current_inventory=0.0,
            max_inventory=0.03,
            buy_spacing=1.0,
            sell_spacing=1.0,
            effective_atr=1.0,
            atr_fast=0.8,
            atr_slow=1.0,
            volatility_ratio=1.0,
            ev_min_spacing=0.5,
            ev_positive=True,
            inventory_ratio=0.0,
            inventory_skew_cost_quote=0.0,
            trend_state="neutral",
        ),
        "",
    )
    await repo.persist_order(
        run_id,
        Order(
            client_order_id="open-buy",
            exchange_order_id="paper-open-buy",
            side=Side.BUY,
            price=99.0,
            quantity=0.01,
            status=OrderStatus.OPEN,
            created_at=1,
            updated_at=1,
        ),
    )
    await repo.persist_fill(
        run_id,
        Fill(
            client_order_id="open-buy",
            side=Side.BUY,
            price=99.0,
            quantity=0.01,
            fee=0.001,
            timestamp=2,
        ),
    )

    status = await repo.latest_status()
    latest_run_id = await repo.latest_run_id()
    orders = await repo.list_orders(run_id, "open")
    fills = await repo.list_fills(run_id, 5)
    await repo.event(run_id, "test", "event")
    latest_balance = await repo.latest_balance(run_id)
    latest_snapshot = await repo.latest_snapshot(run_id)
    latest_metrics = await repo.latest_strategy_metrics(run_id)
    latest_events = await repo.latest_events(run_id, 5)
    watch = await repo.watch_snapshot(run_id)

    assert status["run"]["id"] == run_id
    assert status["balance"]["equity"] == 1000.0
    assert latest_run_id == run_id
    assert orders[0]["client_order_id"] == "open-buy"
    assert fills[0]["client_order_id"] == "open-buy"
    assert latest_balance["equity"] == 1000.0
    assert latest_snapshot is None
    assert latest_metrics["ev_positive"] == 1
    assert latest_events[0]["message"] == "event"
    assert watch["run"]["id"] == run_id
    assert watch["balance"]["equity"] == 1000.0
    assert watch["orders"][0]["client_order_id"] == "open-buy"
    assert watch["metrics"]["trend_state"] == "neutral"


@pytest.mark.asyncio
async def test_engine_cancellation_marks_run_stopped(tmp_path: Path) -> None:
    config_path = write_config(tmp_path)
    config = load_config(config_path)
    repo = SQLiteRepository(config.db_path)
    await repo.init()
    run_id = await repo.create_run("live-paper", config)
    market_data = BlockingMarketDataSource()
    engine = DynoGridEngine(
        config_path=config_path,
        repository=repo,
        gateway=PaperExchangeGateway(config),
        market_data=market_data,
        run_id=run_id,
    )

    task = asyncio.create_task(engine.run())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    status = await repo.latest_status()
    assert status["run"]["status"] == "stopped"
    assert market_data.closed is True


@pytest.mark.asyncio
async def test_engine_stop_loss_auto_flattens_and_stops_run(tmp_path: Path) -> None:
    config_path = write_config(tmp_path)
    payload = yaml.safe_load(config_path.read_text())
    payload["starting_base"] = 1.0
    payload["starting_quote"] = 0.0
    payload["max_inventory"] = 2.0
    payload["order_size"] = 0.1
    payload["stop_loss_pct"] = 0.10
    config_path.write_text(yaml.safe_dump(payload))
    config = load_config(config_path)
    repo = SQLiteRepository(config.db_path)
    await repo.init()
    run_id = await repo.create_run("live-paper", config)
    initial = [
        Candle(1700000000 + index * 60, 100.0, 105.0, 95.0, 100.0, 1.0)
        for index in range(20)
    ]
    market_data = ListMarketDataSource(
        [
            Candle(1700001200, 100.0, 101.0, 99.0, 100.0, 1.0),
            Candle(1700001260, 80.0, 81.0, 79.0, 80.0, 1.0),
        ]
    )
    engine = DynoGridEngine(
        config_path=config_path,
        repository=repo,
        gateway=PaperExchangeGateway(config),
        market_data=market_data,
        run_id=run_id,
        initial_candles=initial,
    )

    await engine.run()
    status = await repo.latest_status()
    fills = await repo.list_fills(run_id, 10)
    events = await repo.latest_events(run_id, 10)

    assert status["run"]["status"] == "stopped"
    assert any(fill["client_order_id"] == "paper-flatten" for fill in fills)
    assert any(event["event_type"] == "paper_stop_loss" for event in events)


@pytest.mark.asyncio
async def test_engine_processes_existing_order_fills_before_repricing_grid(tmp_path: Path) -> None:
    config_path = write_config(tmp_path)
    payload = yaml.safe_load(config_path.read_text())
    payload["grid_count"] = 1
    payload["order_size"] = 0.1
    payload["max_inventory"] = 0.1
    payload["maker_fee_rate"] = 0.001
    payload["price_precision"] = 2
    payload["quantity_precision"] = 4
    config_path.write_text(yaml.safe_dump(payload))
    config = load_config(config_path)
    repo = SQLiteRepository(config.db_path)
    await repo.init()
    run_id = await repo.create_run("live-paper", config)
    initial = [
        Candle(1700000000 + index * 60, 100.0, 101.0, 99.0, 100.0, 1.0)
        for index in range(20)
    ]
    market_data = ListMarketDataSource(
        [
            Candle(1700001200, 100.0, 101.0, 99.0, 100.0, 1.0),
            Candle(1700001260, 100.0, 106.0, 98.0, 106.0, 1.0),
        ]
    )
    engine = DynoGridEngine(
        config_path=config_path,
        repository=repo,
        gateway=PaperExchangeGateway(config),
        market_data=market_data,
        run_id=run_id,
        initial_candles=initial,
    )

    await engine.run(max_cycles=2)
    fills = await repo.list_fills(run_id, 10)

    assert fills
    assert fills[0]["price"] == 98.0


@pytest.mark.asyncio
async def test_engine_uses_5m_strategy_cadence_with_1m_fill_candles(tmp_path: Path) -> None:
    config_path = write_config(tmp_path)
    payload = yaml.safe_load(config_path.read_text())
    payload["strategy_timeframe"] = "5m"
    payload["grid_count"] = 1
    payload["order_size"] = 0.1
    payload["max_inventory"] = 0.1
    payload["price_precision"] = 2
    payload["quantity_precision"] = 4
    config_path.write_text(yaml.safe_dump(payload))
    config = load_config(config_path)
    repo = SQLiteRepository(config.db_path)
    await repo.init()
    run_id = await repo.create_run("live-paper", config)
    market_data = ListMarketDataSource(minute_candles(6, start=6000, close=100.0))
    engine = DynoGridEngine(
        config_path=config_path,
        repository=repo,
        gateway=PaperExchangeGateway(config),
        market_data=market_data,
        run_id=run_id,
        initial_candles=minute_candles(100, start=0, close=100.0),
    )

    await engine.run(max_cycles=6)

    with sqlite3.connect(config.db_path) as db:
        snapshots = db.execute(
            "SELECT timestamp FROM strategy_snapshots WHERE run_id = ? ORDER BY timestamp",
            (run_id,),
        ).fetchall()
        balances = db.execute(
            "SELECT COUNT(*) FROM balances WHERE run_id = ?",
            (run_id,),
        ).fetchone()[0]

    assert [row[0] for row in snapshots] == [5700, 6000]
    assert balances == 6


def test_cli_parser_accepts_watch_refresh() -> None:
    args = build_parser().parse_args(
        ["--config", "config.yaml", "run-live-paper", "--watch", "--refresh", "2"]
    )

    assert args.command == "run-live-paper"
    assert args.watch is True
    assert args.refresh == 2.0


def test_cli_config_check_and_backtest_smoke(tmp_path: Path) -> None:
    config_path = write_config(tmp_path)
    candles_path = Path(__file__).parent / "fixtures" / "candles.csv"

    config_check = subprocess.run(
        [sys.executable, "-m", "dynogrid.cli", "--config", str(config_path), "config-check"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "Config OK" in config_check.stdout
    assert "strategy_timeframe=1m" in config_check.stdout
    assert "recenter_hysteresis_pct" in config_check.stdout
    assert "spacing_hysteresis_pct" in config_check.stdout

    backtest = subprocess.run(
        [
            sys.executable,
            "-m",
            "dynogrid.cli",
            "--json",
            "--config",
            str(config_path),
            "backtest",
            "--candles",
            str(candles_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    run_id = json.loads(backtest.stdout)["run_id"]
    backtest_payload = json.loads(backtest.stdout)

    with sqlite3.connect(tmp_path / "dynogrid.sqlite3") as db:
        snapshots = db.execute("SELECT COUNT(*) FROM strategy_snapshots").fetchone()[0]
        fills = db.execute("SELECT COUNT(*) FROM fills").fetchone()[0]

    assert snapshots > 0
    assert fills >= 0
    assert backtest_payload["mode"] == "backtest"
    assert backtest_payload["performance"]["run"]["id"] == run_id

    performance = subprocess.run(
        [
            sys.executable,
            "-m",
            "dynogrid.cli",
            "--config",
            str(config_path),
            "performance",
            "--run-id",
            str(run_id),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert f"Run {run_id} backtest finished" in performance.stdout
    assert "pnl=" in performance.stdout
    assert "ev_pauses=" in performance.stdout

    orders = subprocess.run(
        [
            sys.executable,
            "-m",
            "dynogrid.cli",
            "--config",
            str(config_path),
            "orders",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "client_order_id" in orders.stdout or "No open orders found." in orders.stdout

    all_orders = subprocess.run(
        [
            sys.executable,
            "-m",
            "dynogrid.cli",
            "--config",
            str(config_path),
            "orders",
            "--run-id",
            str(run_id),
            "--status",
            "all",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "client_order_id" in all_orders.stdout or "No orders found." in all_orders.stdout

    recent_fills = subprocess.run(
        [
            sys.executable,
            "-m",
            "dynogrid.cli",
            "--config",
            str(config_path),
            "fills",
            "--run-id",
            str(run_id),
            "--limit",
            "5",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "client_order_id" in recent_fills.stdout or "No fills found." in recent_fills.stdout

    live = subprocess.run(
        [
            sys.executable,
            "-m",
            "dynogrid.cli",
            "--config",
            str(config_path),
            "run-live",
            "--cycles",
            "1",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert live.returncode == 2
    assert "live trading disabled until safety gates are implemented" in live.stdout

    json_watch = subprocess.run(
        [
            sys.executable,
            "-m",
            "dynogrid.cli",
            "--json",
            "--config",
            str(config_path),
            "run-live-paper",
            "--watch",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert json_watch.returncode == 2
    assert "--json cannot be used with --watch" in json_watch.stdout
