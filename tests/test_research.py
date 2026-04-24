from __future__ import annotations

from pathlib import Path

from dynogrid.models import BotConfig
from dynogrid.research.vector_backtest import run_parameter_sweep


def test_vectorized_parameter_sweep_runs_multiple_parameter_sets() -> None:
    config = BotConfig(
        symbol="BTC/USDT",
        timeframe="1m",
        grid_count=2,
        atr_multiplier=1.0,
        order_size=0.001,
        max_inventory=0.01,
        maker_fee_rate=0.001,
        starting_base=0.0,
        starting_quote=1000.0,
        db_path=":memory:",
    )

    results = run_parameter_sweep(
        candles_path=Path(__file__).parent / "fixtures" / "candles.csv",
        base_config=config,
        grid_counts=[2, 3],
        atr_multipliers=[1.0],
        order_sizes=[0.001],
        atr_periods=[14],
        ema_fast_periods=[9],
        ema_slow_periods=[21],
        bb_windows=[20],
    )

    assert len(results) == 2
    assert {
        "pnl",
        "pnl_pct",
        "max_drawdown",
        "fill_count",
        "total_fees",
        "stop_events",
        "ev_pause_count",
        "skew_cost",
    }.issubset(results.columns)
