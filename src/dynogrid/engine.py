from __future__ import annotations

import asyncio
from pathlib import Path

from dynogrid.config import config_hash, load_config
from dynogrid.exchange.paper import PaperExchangeGateway
from dynogrid.market_data import (
    CcxtClosedCandleSource,
    CsvMarketDataSource,
    MarketDataSource,
    load_candles_csv,
)
from dynogrid.models import Candle, Order, OrderStatus
from dynogrid.persistence.sqlite import SQLiteRepository
from dynogrid.strategy.grid import (
    build_grid_state,
    compute_risk_state,
    generate_desired_orders,
    mark_equity,
)
from dynogrid.strategy.indicators import calculate_indicators
from dynogrid.strategy.reconcile import diff_orders


class DynoGridEngine:
    def __init__(
        self,
        config_path: str | Path,
        repository: SQLiteRepository,
        gateway: PaperExchangeGateway,
        market_data: MarketDataSource,
        run_id: int,
        initial_candles: list[Candle] | None = None,
    ) -> None:
        self.config_path = Path(config_path)
        self.repository = repository
        self.gateway = gateway
        self.market_data = market_data
        self.run_id = run_id
        self._candles: list[Candle] = list(initial_candles or [])
        self._previous_center: float | None = None
        self._starting_equity: float | None = None
        self._stop_event_written = False

    async def run(self, max_cycles: int | None = None, sleep: bool = False) -> None:
        completed = 0
        try:
            while max_cycles is None or completed < max_cycles:
                config = load_config(self.config_path)
                self.gateway.config = config
                config_hash_value = await self.repository.upsert_config_version(config)

                candle = await self.market_data.next_candle()
                if candle is None:
                    break

                await self.repository.persist_candle(self.run_id, config.symbol, candle)
                self._candles.append(candle)

                balance = await self.gateway.balance()
                if self._starting_equity is None:
                    self._starting_equity = mark_equity(balance, candle.close)

                await self._handle_flatten_if_requested(candle)

                if len(self._candles) < 20:
                    balance = await self.gateway.balance()
                    await self.repository.persist_balance(
                        self.run_id, candle.timestamp, balance, mark_equity(balance, candle.close)
                    )
                    await self.repository.event(
                        self.run_id,
                        "warmup",
                        "waiting for enough candles to calculate indicators",
                        {"candles": len(self._candles)},
                    )
                    completed += 1
                    await self._maybe_sleep(config.loop_interval_seconds, sleep)
                    continue

                indicators = calculate_indicators(self._candles)
                balance = await self.gateway.balance()
                grid, fee_barrier_applied = build_grid_state(
                    config=config,
                    indicators=indicators,
                    current_price=candle.close,
                    previous_center=self._previous_center,
                    balance=balance,
                )
                self._previous_center = grid.center_price

                paused = await self.repository.runtime_state("paused", "0") == "1"
                risk = compute_risk_state(
                    config=config,
                    balance=balance,
                    current_price=candle.close,
                    starting_equity=self._starting_equity,
                    paused=paused,
                    fee_barrier_applied=fee_barrier_applied,
                )
                if risk.paper_stop_loss_breached and not self._stop_event_written:
                    await self.repository.event(
                        self.run_id,
                        "paper_stop_loss",
                        "paper stop loss threshold breached",
                        {"equity": mark_equity(balance, candle.close)},
                    )
                    self._stop_event_written = True

                desired = generate_desired_orders(config, grid, risk, balance)
                open_orders = await self.gateway.open_orders()
                plan = diff_orders(open_orders, desired)

                for client_order_id in plan.cancel_order_ids:
                    canceled = await self.gateway.cancel_order(client_order_id, candle.timestamp)
                    if canceled is not None:
                        await self.repository.persist_order(self.run_id, canceled)

                for desired_order in plan.create_orders:
                    try:
                        created = await self.gateway.create_order(desired_order, candle.timestamp)
                    except ValueError as exc:
                        await self.repository.event(
                            self.run_id,
                            "order_rejected",
                            str(exc),
                            {"client_order_id": desired_order.client_order_id},
                        )
                    else:
                        await self.repository.persist_order(self.run_id, created)

                fills = await self.gateway.process_candle(candle)
                for fill in fills:
                    await self.repository.persist_fill(self.run_id, fill)
                    await self.repository.persist_order(
                        self.run_id,
                        Order(
                            client_order_id=fill.client_order_id,
                            exchange_order_id=f"paper-{fill.client_order_id}",
                            side=fill.side,
                            price=fill.price,
                            quantity=fill.quantity,
                            status=OrderStatus.FILLED,
                            created_at=fill.timestamp,
                            updated_at=fill.timestamp,
                        ),
                    )

                balance = await self.gateway.balance()
                await self.repository.persist_snapshot(
                    run_id=self.run_id,
                    config_hash_value=config_hash_value,
                    candle=candle,
                    indicators=indicators,
                    grid=grid,
                    risk=risk,
                    desired_count=len(desired),
                )
                await self.repository.persist_balance(
                    self.run_id,
                    candle.timestamp,
                    balance,
                    mark_equity(balance, candle.close),
                )

                completed += 1
                await self._maybe_sleep(config.loop_interval_seconds, sleep)
        except Exception:
            await self.repository.finish_run(self.run_id, "failed")
            raise
        else:
            await self.repository.finish_run(self.run_id, "finished")
        finally:
            await self.market_data.close()

    async def _handle_flatten_if_requested(self, candle: Candle) -> None:
        requested = await self.repository.runtime_state("flatten_requested", "0") == "1"
        if not requested:
            return
        for order in await self.gateway.open_orders():
            canceled = await self.gateway.cancel_order(order.client_order_id, candle.timestamp)
            if canceled is not None:
                await self.repository.persist_order(self.run_id, canceled)
        fill = await self.gateway.flatten(candle.close, candle.timestamp)
        if fill is not None:
            await self.repository.persist_fill(self.run_id, fill)
        await self.repository.set_runtime_state("flatten_requested", "0")
        await self.repository.event(
            self.run_id,
            "flatten",
            "paper position flattened",
            {"price": candle.close, "filled": fill is not None},
        )

    @staticmethod
    async def _maybe_sleep(seconds: int, enabled: bool) -> None:
        if enabled:
            await asyncio.sleep(seconds)


async def run_historical(
    config_path: str | Path,
    candles_path: str | Path,
    mode: str,
    max_cycles: int | None = None,
    sleep: bool = False,
) -> int:
    config = load_config(config_path)
    repository = SQLiteRepository(config.db_path)
    await repository.init()
    run_id = await repository.create_run(mode, config)
    market_data = CsvMarketDataSource(load_candles_csv(candles_path))
    gateway = PaperExchangeGateway(config)
    engine = DynoGridEngine(config_path, repository, gateway, market_data, run_id)
    await engine.run(max_cycles=max_cycles, sleep=sleep)
    return run_id


async def run_live_paper(
    config_path: str | Path,
    max_cycles: int | None = None,
) -> int:
    config = load_config(config_path)
    repository = SQLiteRepository(config.db_path)
    await repository.init()
    run_id = await repository.create_run("live-paper", config)
    market_data = CcxtClosedCandleSource(config)
    initial_candles = await market_data.seed_candles()
    await repository.event(
        run_id,
        "live_paper_seed",
        "loaded closed candles for indicator warmup",
        {"candles": len(initial_candles)},
    )
    gateway = PaperExchangeGateway(config)
    engine = DynoGridEngine(
        config_path,
        repository,
        gateway,
        market_data,
        run_id,
        initial_candles=initial_candles,
    )
    await engine.run(max_cycles=max_cycles, sleep=False)
    return run_id
