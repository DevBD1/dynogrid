from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from dynogrid.config import load_config
from dynogrid.models import Balance, Candle
from dynogrid.persistence.sqlite import SQLiteRepository


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

    status = await repo.latest_status()

    assert status["run"]["id"] == run_id
    assert status["balance"]["equity"] == 1000.0


def test_cli_config_check_and_backtest_smoke(tmp_path: Path) -> None:
    config_path = write_config(tmp_path)
    candles_path = Path(__file__).parent / "fixtures" / "candles.csv"

    config_check = subprocess.run(
        [sys.executable, "-m", "dynogrid.cli", "--config", str(config_path), "config-check"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(config_check.stdout)["ok"] is True

    backtest = subprocess.run(
        [
            sys.executable,
            "-m",
            "dynogrid.cli",
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
    assert json.loads(backtest.stdout)["mode"] == "backtest"

    with sqlite3.connect(tmp_path / "dynogrid.sqlite3") as db:
        snapshots = db.execute("SELECT COUNT(*) FROM strategy_snapshots").fetchone()[0]
        fills = db.execute("SELECT COUNT(*) FROM fills").fetchone()[0]

    assert snapshots > 0
    assert fills >= 0
