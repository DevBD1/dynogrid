from __future__ import annotations

import asyncio
import csv
import time
from pathlib import Path
from typing import Protocol

import ccxt.async_support as ccxt

from dynogrid.models import BotConfig, Candle


class MarketDataSource(Protocol):
    async def next_candle(self) -> Candle | None:
        ...

    async def close(self) -> None:
        ...


class CsvMarketDataSource:
    def __init__(self, candles: list[Candle]) -> None:
        self._candles = candles
        self._cursor = 0

    async def next_candle(self) -> Candle | None:
        if self._cursor >= len(self._candles):
            return None
        candle = self._candles[self._cursor]
        self._cursor += 1
        return candle

    async def close(self) -> None:
        return None


class CcxtClosedCandleSource:
    def __init__(self, config: BotConfig, warmup_limit: int = 100) -> None:
        self.config = config
        self.warmup_limit = warmup_limit
        exchange_class = getattr(ccxt, config.exchange_id)
        self.exchange = exchange_class({"enableRateLimit": True})
        self._buffer: list[Candle] = []
        self._last_timestamp: int | None = None

    async def seed_candles(self) -> list[Candle]:
        candles = await self._fetch_recent_closed()
        if candles:
            self._last_timestamp = candles[-1].timestamp
        return candles

    async def next_candle(self) -> Candle | None:
        while True:
            if self._buffer:
                candle = self._buffer.pop(0)
                self._last_timestamp = candle.timestamp
                return candle
            await self._fetch_closed_candles()
            if not self._buffer:
                await asyncio.sleep(5)

    async def close(self) -> None:
        await self.exchange.close()

    async def _fetch_closed_candles(self) -> None:
        closed = await self._fetch_recent_closed()
        if self._last_timestamp is not None:
            closed = [candle for candle in closed if candle.timestamp > self._last_timestamp]
        self._buffer.extend(closed)

    async def _fetch_recent_closed(self) -> list[Candle]:
        ohlcv = await self._fetch_ohlcv_with_backoff()
        now_ms = int(time.time() * 1000)
        return [
            _to_candle(row)
            for row in ohlcv
            if int(row[0]) + _timeframe_ms(self.config.timeframe) <= now_ms
        ]

    async def _fetch_ohlcv_with_backoff(self) -> list[list[float]]:
        delay = 1.0
        for attempt in range(5):
            try:
                return await self.exchange.fetch_ohlcv(
                    self.config.symbol,
                    timeframe=self.config.timeframe,
                    limit=self.warmup_limit,
                )
            except (ccxt.RateLimitExceeded, ccxt.NetworkError):
                if attempt == 4:
                    raise
                await asyncio.sleep(delay)
                delay *= 2
        raise RuntimeError("unreachable ccxt fetch retry state")


def load_candles_csv(path: str | Path) -> list[Candle]:
    candles: list[Candle] = []
    with Path(path).open(newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            candles.append(
                Candle(
                    timestamp=int(row["timestamp"]),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                )
            )
    return candles


def _to_candle(row: list[float]) -> Candle:
    return Candle(
        timestamp=int(row[0] // 1000),
        open=float(row[1]),
        high=float(row[2]),
        low=float(row[3]),
        close=float(row[4]),
        volume=float(row[5]),
    )


def _timeframe_ms(timeframe: str) -> int:
    if timeframe != "1m":
        raise ValueError("V1 live paper mode only supports timeframe=1m")
    return 60_000
