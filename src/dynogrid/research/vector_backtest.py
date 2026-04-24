from __future__ import annotations

from dataclasses import replace
from itertools import product
from pathlib import Path
from typing import Iterable

import pandas as pd

from dynogrid.market_data import load_candles_csv
from dynogrid.models import BotConfig
from dynogrid.strategy.grid import calculate_ev_min_spacing


def run_parameter_sweep(
    candles_path: str | Path,
    base_config: BotConfig,
    grid_counts: Iterable[int],
    atr_multipliers: Iterable[float],
    order_sizes: Iterable[float],
    atr_periods: Iterable[int],
    ema_fast_periods: Iterable[int],
    ema_slow_periods: Iterable[int],
    bb_windows: Iterable[int],
) -> pd.DataFrame:
    candles = load_candles_csv(candles_path)
    frame = pd.DataFrame(
        {
            "timestamp": [c.timestamp for c in candles],
            "open": [c.open for c in candles],
            "high": [c.high for c in candles],
            "low": [c.low for c in candles],
            "close": [c.close for c in candles],
        }
    )
    rows: list[dict[str, float | int]] = []
    for (
        grid_count,
        atr_multiplier,
        order_size,
        atr_period,
        ema_fast_period,
        ema_slow_period,
        bb_window,
    ) in product(
        grid_counts,
        atr_multipliers,
        order_sizes,
        atr_periods,
        ema_fast_periods,
        ema_slow_periods,
        bb_windows,
    ):
        config = replace(
            base_config,
            grid_count=int(grid_count),
            atr_multiplier=float(atr_multiplier),
            order_size=float(order_size),
            atr_fast_period=max(1, int(atr_period // 2)),
            atr_slow_period=int(atr_period),
            ema_fast_period=int(ema_fast_period),
            ema_slow_period=int(ema_slow_period),
        )
        rows.append(
            _simulate_parameter_set(
                frame,
                config,
                atr_period=int(atr_period),
                bb_window=int(bb_window),
            )
        )
    return pd.DataFrame(rows)


def _simulate_parameter_set(
    frame: pd.DataFrame,
    config: BotConfig,
    atr_period: int,
    bb_window: int,
) -> dict[str, float | int]:
    data = frame.copy()
    previous_close = data["close"].shift(1)
    true_range = pd.concat(
        [
            data["high"] - data["low"],
            (data["high"] - previous_close).abs(),
            (data["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    period = max(1, min(atr_period, len(data) - 1))
    data["atr"] = true_range.rolling(period, min_periods=period).mean()
    window = max(2, min(bb_window, len(data)))
    data["bb_mid"] = data["close"].rolling(window, min_periods=window).mean()
    data["bb_sigma"] = data["close"].rolling(window, min_periods=window).std(ddof=0)
    data["bb_upper"] = data["bb_mid"] + 2.0 * data["bb_sigma"]
    data["bb_lower"] = data["bb_mid"] - 2.0 * data["bb_sigma"]
    data["ema_fast"] = data["close"].ewm(span=config.ema_fast_period, adjust=False).mean()
    data["ema_slow"] = data["close"].ewm(span=config.ema_slow_period, adjust=False).mean()

    quote = config.starting_quote
    base = config.starting_base
    starting_equity = quote + base * float(data["close"].iloc[0])
    equity_peak = starting_equity
    max_drawdown = 0.0
    fills = 0
    fees = 0.0
    ev_pauses = 0
    stop_events = 0
    skew_cost = 0.0

    for row in data.dropna().itertuples(index=False):
        close = float(row.close)
        atr = float(row.atr)
        ev_min_spacing = calculate_ev_min_spacing(config, close)
        if ev_min_spacing > close * config.max_ev_spacing_pct:
            ev_pauses += 1
            continue
        spacing = max(atr * config.atr_multiplier, ev_min_spacing)
        inventory_ratio = base / config.max_inventory if config.max_inventory else 1.0
        if inventory_ratio > config.inventory_spacing_threshold:
            skew_cost += (spacing * inventory_ratio) * base

        buy_price = close - spacing
        sell_price = close + spacing
        quantity = config.order_size
        if float(row.low) <= buy_price and base + quantity <= config.max_inventory:
            notional = buy_price * quantity
            fee = notional * config.maker_fee_rate
            if quote >= notional + fee:
                quote -= notional + fee
                base += quantity
                fills += 1
                fees += fee
        if float(row.high) >= sell_price and base >= quantity:
            notional = sell_price * quantity
            fee = notional * config.maker_fee_rate
            quote += notional - fee
            base -= quantity
            fills += 1
            fees += fee

        equity = quote + base * close
        equity_peak = max(equity_peak, equity)
        max_drawdown = max(max_drawdown, equity_peak - equity)
        if equity < starting_equity * (1.0 - config.stop_loss_pct):
            stop_events += 1
            quote += base * close * (1.0 - config.maker_fee_rate)
            base = 0.0
            break

    end_equity = quote + base * float(data["close"].iloc[-1])
    pnl = end_equity - starting_equity
    return {
        "grid_count": config.grid_count,
        "atr_multiplier": config.atr_multiplier,
        "order_size": config.order_size,
        "atr_period": atr_period,
        "ema_fast_period": config.ema_fast_period,
        "ema_slow_period": config.ema_slow_period,
        "bb_window": bb_window,
        "pnl": pnl,
        "pnl_pct": pnl / starting_equity * 100.0 if starting_equity else 0.0,
        "max_drawdown": max_drawdown,
        "fill_count": fills,
        "total_fees": fees,
        "stop_events": stop_events,
        "ev_pause_count": ev_pauses,
        "skew_cost": skew_cost,
    }
