from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from time import time

import aiosqlite

from dynogrid.config import config_hash, config_json
from dynogrid.models import (
    Balance,
    BotConfig,
    Candle,
    Fill,
    GridState,
    IndicatorSnapshot,
    Order,
    RiskState,
)


class SQLiteRepository:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)

    async def init(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.executescript(SCHEMA)
            await db.execute(
                "INSERT OR IGNORE INTO runtime_state(key, value) VALUES('paused', '0')"
            )
            await db.execute(
                "INSERT OR IGNORE INTO runtime_state(key, value) VALUES('flatten_requested', '0')"
            )
            await db.commit()

    async def create_run(self, mode: str, config: BotConfig) -> int:
        payload_hash = config_hash(config)
        await self.upsert_config_version(config)
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                """
                INSERT INTO runs(started_at, mode, symbol, config_hash, status)
                VALUES (?, ?, ?, ?, ?)
                """,
                (int(time()), mode, config.symbol, payload_hash, "running"),
            )
            await db.commit()
            return int(cursor.lastrowid)

    async def finish_run(self, run_id: int, status: str = "finished") -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE runs SET finished_at = ?, status = ? WHERE id = ?",
                (int(time()), status, run_id),
            )
            await db.commit()

    async def upsert_config_version(self, config: BotConfig) -> str:
        payload_hash = config_hash(config)
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT OR IGNORE INTO config_versions(config_hash, payload, created_at)
                VALUES (?, ?, ?)
                """,
                (payload_hash, config_json(config), int(time())),
            )
            await db.commit()
        return payload_hash

    async def persist_candle(self, run_id: int, symbol: str, candle: Candle) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO candles(
                    run_id, symbol, timestamp, open, high, low, close, volume
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    symbol,
                    candle.timestamp,
                    candle.open,
                    candle.high,
                    candle.low,
                    candle.close,
                    candle.volume,
                ),
            )
            await db.commit()

    async def persist_snapshot(
        self,
        run_id: int,
        config_hash_value: str,
        candle: Candle,
        indicators: IndicatorSnapshot,
        grid: GridState,
        risk: RiskState,
        desired_count: int,
    ) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT INTO strategy_snapshots(
                    run_id, timestamp, config_hash, atr14, bollinger_mid,
                    bollinger_upper, bollinger_lower, center_price, spacing, bias,
                    inventory, max_inventory, risk_json, desired_order_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    candle.timestamp,
                    config_hash_value,
                    indicators.atr14,
                    indicators.bollinger_mid,
                    indicators.bollinger_upper,
                    indicators.bollinger_lower,
                    grid.center_price,
                    grid.spacing,
                    grid.bias.value,
                    grid.current_inventory,
                    grid.max_inventory,
                    json.dumps(asdict(risk), sort_keys=True),
                    desired_count,
                ),
            )
            await db.commit()

    async def persist_order(self, run_id: int, order: Order) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO orders(
                    run_id, client_order_id, exchange_order_id, side, price, quantity,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    order.client_order_id,
                    order.exchange_order_id,
                    order.side.value,
                    order.price,
                    order.quantity,
                    order.status.value,
                    order.created_at,
                    order.updated_at,
                ),
            )
            await db.commit()

    async def persist_fill(self, run_id: int, fill: Fill) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT INTO fills(
                    run_id, client_order_id, side, price, quantity, fee, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    fill.client_order_id,
                    fill.side.value,
                    fill.price,
                    fill.quantity,
                    fill.fee,
                    fill.timestamp,
                ),
            )
            await db.commit()

    async def persist_balance(
        self, run_id: int, timestamp: int, balance: Balance, equity: float
    ) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT INTO balances(
                    run_id, timestamp, base_free, quote_free,
                    base_locked, quote_locked, equity
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    timestamp,
                    balance.base_free,
                    balance.quote_free,
                    balance.base_locked,
                    balance.quote_locked,
                    equity,
                ),
            )
            await db.commit()

    async def event(
        self, run_id: int | None, event_type: str, message: str, payload: dict | None = None
    ) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT INTO events(run_id, timestamp, event_type, message, payload)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    int(time()),
                    event_type,
                    message,
                    json.dumps(payload or {}, sort_keys=True),
                ),
            )
            await db.commit()

    async def set_runtime_state(self, key: str, value: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO runtime_state(key, value) VALUES(?, ?)",
                (key, value),
            )
            await db.commit()

    async def runtime_state(self, key: str, default: str = "") -> str:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("SELECT value FROM runtime_state WHERE key = ?", (key,))
            row = await cursor.fetchone()
        return str(row[0]) if row else default

    async def latest_status(self) -> dict[str, object]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            run_cursor = await db.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1")
            run = await run_cursor.fetchone()
            balance_cursor = await db.execute(
                "SELECT * FROM balances ORDER BY id DESC LIMIT 1"
            )
            balance = await balance_cursor.fetchone()
            snapshot_cursor = await db.execute(
                "SELECT * FROM strategy_snapshots ORDER BY id DESC LIMIT 1"
            )
            snapshot = await snapshot_cursor.fetchone()
            order_cursor = await db.execute(
                """
                SELECT COUNT(*) AS count
                FROM orders
                WHERE status = 'open'
                  AND run_id = (SELECT id FROM runs ORDER BY id DESC LIMIT 1)
                """
            )
            open_orders = await order_cursor.fetchone()
            state_cursor = await db.execute(
                "SELECT value FROM runtime_state WHERE key = 'paused'"
            )
            state = await state_cursor.fetchone()
            paused = str(state["value"]) if state else "0"
        return {
            "run": dict(run) if run else None,
            "balance": dict(balance) if balance else None,
            "snapshot": dict(snapshot) if snapshot else None,
            "open_orders": int(open_orders["count"]) if open_orders else 0,
            "paused": paused == "1",
        }


SCHEMA = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at INTEGER NOT NULL,
    finished_at INTEGER,
    mode TEXT NOT NULL,
    symbol TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS config_versions (
    config_hash TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS candles (
    run_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL,
    PRIMARY KEY (run_id, symbol, timestamp)
);

CREATE TABLE IF NOT EXISTS strategy_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    timestamp INTEGER NOT NULL,
    config_hash TEXT NOT NULL,
    atr14 REAL NOT NULL,
    bollinger_mid REAL NOT NULL,
    bollinger_upper REAL NOT NULL,
    bollinger_lower REAL NOT NULL,
    center_price REAL NOT NULL,
    spacing REAL NOT NULL,
    bias TEXT NOT NULL,
    inventory REAL NOT NULL,
    max_inventory REAL NOT NULL,
    risk_json TEXT NOT NULL,
    desired_order_count INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    run_id INTEGER NOT NULL,
    client_order_id TEXT NOT NULL,
    exchange_order_id TEXT,
    side TEXT NOT NULL,
    price REAL NOT NULL,
    quantity REAL NOT NULL,
    status TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (run_id, client_order_id)
);

CREATE TABLE IF NOT EXISTS fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    client_order_id TEXT NOT NULL,
    side TEXT NOT NULL,
    price REAL NOT NULL,
    quantity REAL NOT NULL,
    fee REAL NOT NULL,
    timestamp INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS balances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    timestamp INTEGER NOT NULL,
    base_free REAL NOT NULL,
    quote_free REAL NOT NULL,
    base_locked REAL NOT NULL,
    quote_locked REAL NOT NULL,
    equity REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER,
    timestamp INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    message TEXT NOT NULL,
    payload TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runtime_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""
