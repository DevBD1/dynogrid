from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Callable

from dynogrid.config import load_config
from dynogrid.exchange.base import ExchangeGateway
from dynogrid.exchange.ccxt_binance import BinanceCcxtGateway, LiveTradingDisabledError
from dynogrid.exchange.paper import PaperExchangeGateway
from dynogrid.market_data import (
    CcxtClosedCandleSource,
    CsvMarketDataSource,
    MarketDataSource,
    aggregate_candles,
    load_candles_csv,
)
from dynogrid.models import BotConfig, Candle, Fill, Order, OrderStatus
from dynogrid.persistence.sqlite import SQLiteRepository
from dynogrid.strategy.grid import (
    build_grid_state,
    compute_risk_state,
    generate_desired_orders,
    mark_equity,
    structural_exit_signal,
)
from dynogrid.strategy.indicators import calculate_indicators
from dynogrid.strategy.reconcile import diff_orders

ProgressReporter = Callable[[str], None]


class DynoGridEngine:
    def __init__(
        self,
        config_path: str | Path,
        repository: SQLiteRepository,
        gateway: ExchangeGateway,
        market_data: MarketDataSource,
        run_id: int,
        initial_candles: list[Candle] | None = None,
        reporter: ProgressReporter | None = None,
    ) -> None:
        self.config_path = Path(config_path)
        self.repository = repository
        self.gateway = gateway
        self.market_data = market_data
        self.run_id = run_id
        self._candles: list[Candle] = list(initial_candles or [])
        self._strategy_candles: list[Candle] = []
        self._last_strategy_timestamp: int | None = None
        self._previous_center: float | None = None
        self._previous_spacing: float | None = None
        self._starting_equity: float | None = None
        self._stop_event_written = False
        self._ev_event_written = False
        self._reporter = reporter

    async def run(self, max_cycles: int | None = None, sleep: bool = False) -> None:
        completed = 0
        self._report(
            f"run {self.run_id} started; warmup_candles={len(self._candles)} "
            f"target_cycles={max_cycles if max_cycles is not None else 'unlimited'}"
        )
        try:
            while max_cycles is None or completed < max_cycles:
                config = load_config(self.config_path)
                self.gateway.config = config
                config_hash_value = await self.repository.upsert_config_version(config)

                self._report("waiting for next closed candle")
                candle = await self.market_data.next_candle()
                if candle is None:
                    self._report("no more candles from market data source")
                    break

                await self.repository.persist_candle(self.run_id, config.symbol, candle)
                self._candles.append(candle)

                balance = await self.gateway.balance()
                if self._starting_equity is None:
                    self._starting_equity = mark_equity(balance, candle.close)

                await self._handle_flatten_if_requested(candle)

                fills = await self._process_fills_for_candle(candle)
                if await self._handle_intrabar_stop_loss(config, candle):
                    completed += 1
                    return
                strategy_candle = self._next_strategy_candle(config)
                if strategy_candle is None:
                    balance = await self.gateway.balance()
                    await self.repository.persist_balance(
                        self.run_id, candle.timestamp, balance, mark_equity(balance, candle.close)
                    )
                    completed += 1
                    self._report(
                        f"cycle={completed} candle={candle.timestamp} close={candle.close:.2f} "
                        f"fills={len(fills)} strategy_wait={config.strategy_timeframe} "
                        f"equity={mark_equity(balance, candle.close):.2f}"
                    )
                    await self._maybe_sleep(config.loop_interval_seconds, sleep)
                    continue

                if len(self._strategy_candles) < 20:
                    balance = await self.gateway.balance()
                    await self.repository.persist_balance(
                        self.run_id, candle.timestamp, balance, mark_equity(balance, candle.close)
                    )
                    await self.repository.event(
                        self.run_id,
                        "warmup",
                        "waiting for enough candles to calculate indicators",
                        {
                            "candles": len(self._strategy_candles),
                            "strategy_timeframe": config.strategy_timeframe,
                        },
                    )
                    completed += 1
                    self._report(
                        f"cycle={completed} candle={candle.timestamp} close={candle.close:.2f} "
                        f"warmup={len(self._strategy_candles)}/20 "
                        f"strategy_timeframe={config.strategy_timeframe} fills={len(fills)} "
                        f"equity={mark_equity(balance, candle.close):.2f}"
                    )
                    await self._maybe_sleep(config.loop_interval_seconds, sleep)
                    continue

                indicators = calculate_indicators(
                    self._strategy_candles,
                    atr_fast_period=config.atr_fast_period,
                    atr_slow_period=config.atr_slow_period,
                    ema_fast_period=config.ema_fast_period,
                    ema_slow_period=config.ema_slow_period,
                )
                balance = await self.gateway.balance()
                grid, fee_barrier_applied = build_grid_state(
                    config=config,
                    indicators=indicators,
                    current_price=strategy_candle.close,
                    previous_center=self._previous_center,
                    balance=balance,
                    previous_spacing=self._previous_spacing,
                )
                self._previous_center = grid.center_price
                self._previous_spacing = grid.spacing

                paused = await self.repository.runtime_state("paused", "0") == "1"
                exit_signal = structural_exit_signal(
                    config, self._strategy_candles, indicators, balance
                )
                equity = mark_equity(balance, strategy_candle.close)
                if self._starting_equity is not None and equity < self._starting_equity * (
                    1.0 - config.stop_loss_pct
                ):
                    exit_signal = "paper_stop_loss"
                risk = compute_risk_state(
                    config=config,
                    balance=balance,
                    current_price=strategy_candle.close,
                    starting_equity=self._starting_equity,
                    paused=paused,
                    fee_barrier_applied=fee_barrier_applied,
                    ev_positive=grid.ev_positive,
                    trend_state=grid.trend_state,
                    exit_signal=exit_signal,
                )
                if risk.paper_stop_loss_breached and not self._stop_event_written:
                    await self.repository.event(
                        self.run_id,
                        "paper_stop_loss",
                        "paper stop loss threshold breached",
                        {"equity": mark_equity(balance, candle.close)},
                    )
                    self._stop_event_written = True
                if not grid.ev_positive and not self._ev_event_written:
                    await self.repository.event(
                        self.run_id,
                        "ev_pause",
                        "EV minimum spacing exceeds configured cap; entries paused",
                        {
                            "ev_min_spacing": grid.ev_min_spacing,
                            "max_spacing": strategy_candle.close * config.max_ev_spacing_pct,
                        },
                    )
                    self._ev_event_written = True

                desired = generate_desired_orders(config, grid, risk, balance)
                if exit_signal:
                    desired = []
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

                if exit_signal:
                    await self._cancel_all_and_flatten(candle, exit_signal)

                balance = await self.gateway.balance()
                equity = mark_equity(balance, candle.close)
                await self.repository.persist_snapshot(
                    run_id=self.run_id,
                    config_hash_value=config_hash_value,
                    candle=strategy_candle,
                    indicators=indicators,
                    grid=grid,
                    risk=risk,
                    desired_count=len(desired),
                )
                await self.repository.persist_strategy_metrics(
                    run_id=self.run_id,
                    timestamp=strategy_candle.timestamp,
                    grid=grid,
                    exit_signal=exit_signal,
                )
                await self.repository.persist_balance(
                    self.run_id,
                    candle.timestamp,
                    balance,
                    equity,
                )

                completed += 1
                self._report(
                    f"cycle={completed} candle={candle.timestamp} strategy_candle={strategy_candle.timestamp} "
                    f"close={strategy_candle.close:.2f} "
                    f"bias={grid.bias.value} center={grid.center_price:.2f} "
                    f"spacing={grid.spacing:.2f} desired={len(desired)} "
                    f"created={len(plan.create_orders)} canceled={len(plan.cancel_order_ids)} "
                    f"fills={len(fills)} open={len(await self.gateway.open_orders())} "
                    f"equity={equity:.2f} trend={grid.trend_state} ev={grid.ev_positive}"
                )
                if exit_signal:
                    await self.repository.finish_run(self.run_id, "stopped")
                    self._report(f"run {self.run_id} stopped by {exit_signal}")
                    return
                await self._maybe_sleep(config.loop_interval_seconds, sleep)
        except asyncio.CancelledError:
            await self.repository.finish_run(self.run_id, "stopped")
            self._report(f"run {self.run_id} stopped")
            raise
        except Exception:
            await self.repository.finish_run(self.run_id, "failed")
            self._report(f"run {self.run_id} failed")
            raise
        else:
            await self.repository.finish_run(self.run_id, "finished")
            self._report(f"run {self.run_id} finished after {completed} cycles")
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

    async def _process_fills_for_candle(self, candle: Candle) -> list[Fill]:
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
        return fills

    async def _handle_intrabar_stop_loss(self, config: BotConfig, candle: Candle) -> bool:
        if self._starting_equity is None:
            return False
        balance = await self.gateway.balance()
        equity = mark_equity(balance, candle.close)
        if equity >= self._starting_equity * (1.0 - config.stop_loss_pct):
            return False
        if not self._stop_event_written:
            await self.repository.event(
                self.run_id,
                "paper_stop_loss",
                "paper stop loss threshold breached",
                {"equity": equity, "candle_timeframe": config.timeframe},
            )
            self._stop_event_written = True
        await self._cancel_all_and_flatten(candle, "paper_stop_loss")
        balance = await self.gateway.balance()
        await self.repository.persist_balance(
            self.run_id, candle.timestamp, balance, mark_equity(balance, candle.close)
        )
        await self.repository.finish_run(self.run_id, "stopped")
        self._report(f"run {self.run_id} stopped by paper_stop_loss")
        return True

    async def _cancel_all_and_flatten(self, candle: Candle, reason: str) -> None:
        for order in await self.gateway.open_orders():
            canceled = await self.gateway.cancel_order(order.client_order_id, candle.timestamp)
            if canceled is not None:
                await self.repository.persist_order(self.run_id, canceled)
        fill = await self.gateway.flatten(candle.close, candle.timestamp)
        if fill is not None:
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
        await self.repository.event(
            self.run_id,
            reason,
            "paper position auto-flattened",
            {"price": candle.close, "filled": fill is not None},
        )

    @staticmethod
    async def _maybe_sleep(seconds: int, enabled: bool) -> None:
        if enabled:
            await asyncio.sleep(seconds)

    def _report(self, message: str) -> None:
        if self._reporter is not None:
            self._reporter(message)

    def _next_strategy_candle(self, config: BotConfig) -> Candle | None:
        aggregated = aggregate_candles(self._candles, config.strategy_timeframe)
        if not aggregated:
            return None
        if self._last_strategy_timestamp is None:
            self._strategy_candles = aggregated
            self._last_strategy_timestamp = aggregated[-1].timestamp
            return aggregated[-1]
        new_candles = [
            candle for candle in aggregated if candle.timestamp > self._last_strategy_timestamp
        ]
        if not new_candles:
            return None
        self._strategy_candles.extend(new_candles)
        self._last_strategy_timestamp = new_candles[-1].timestamp
        return new_candles[-1]


async def run_historical(
    config_path: str | Path,
    candles_path: str | Path,
    mode: str,
    max_cycles: int | None = None,
    sleep: bool = False,
    reporter: ProgressReporter | None = None,
) -> int:
    config = load_config(config_path)
    repository = SQLiteRepository(config.db_path)
    await repository.init()
    run_id = await repository.create_run(mode, config)
    market_data = CsvMarketDataSource(load_candles_csv(candles_path))
    gateway = create_gateway(mode, config)
    engine = DynoGridEngine(
        config_path, repository, gateway, market_data, run_id, reporter=reporter
    )
    await engine.run(max_cycles=max_cycles, sleep=sleep)
    return run_id


async def run_live_paper(
    config_path: str | Path,
    max_cycles: int | None = None,
    reporter: ProgressReporter | None = None,
) -> int:
    repository, run_id, engine = await prepare_live_paper_engine(config_path, reporter)
    await engine.run(max_cycles=max_cycles, sleep=False)
    return run_id


async def prepare_live_paper_engine(
    config_path: str | Path,
    reporter: ProgressReporter | None = None,
) -> tuple[SQLiteRepository, int, DynoGridEngine]:
    config = load_config(config_path)
    repository = SQLiteRepository(config.db_path)
    await repository.init()
    run_id = await repository.create_run("live-paper", config)
    if reporter is not None:
        reporter(f"run {run_id} created in live-paper mode for {config.symbol}")
    market_data = CcxtClosedCandleSource(config)
    if reporter is not None:
        reporter("fetching closed candles for indicator warmup")
    initial_candles = await market_data.seed_candles()
    if reporter is not None:
        reporter(f"seeded {len(initial_candles)} closed candles; next cycles use new live candles")
    await repository.event(
        run_id,
        "live_paper_seed",
        "loaded closed candles for indicator warmup",
        {"candles": len(initial_candles)},
    )
    gateway = create_gateway("live-paper", config)
    engine = DynoGridEngine(
        config_path,
        repository,
        gateway,
        market_data,
        run_id,
        initial_candles=initial_candles,
        reporter=reporter,
    )
    return repository, run_id, engine


def create_gateway(mode: str, config: BotConfig) -> ExchangeGateway:
    if mode in {"paper", "backtest", "live-paper"}:
        return PaperExchangeGateway(config)
    if mode == "live":
        return BinanceCcxtGateway(config)
    raise ValueError(f"unknown execution mode: {mode}")


async def run_live(
    config_path: str | Path,
    max_cycles: int | None = None,
    reporter: ProgressReporter | None = None,
) -> int:
    raise LiveTradingDisabledError(
        "live trading disabled until safety gates are implemented"
    )
