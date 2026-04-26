from __future__ import annotations

from dynogrid.models import Balance, Bias, BotConfig, Candle, IndicatorSnapshot, Side
from dynogrid.strategy.grid import (
    build_grid_state,
    calculate_ev_min_spacing,
    compute_risk_state,
    calculate_spacing,
    determine_bias,
    determine_bias_with_mode,
    generate_desired_orders,
    structural_exit_signal,
    update_center_price,
    update_center_price_with_hysteresis,
    update_spacing_with_hysteresis,
)
from dynogrid.strategy.indicators import calculate_atr, calculate_bollinger


def config() -> BotConfig:
    return BotConfig(
        symbol="BTC/USDT",
        timeframe="1m",
        grid_count=3,
        atr_multiplier=1.0,
        order_size=0.1,
        max_inventory=0.2,
        maker_fee_rate=0.001,
        starting_base=0.1,
        starting_quote=1000.0,
        db_path=":memory:",
        price_precision=2,
        quantity_precision=4,
        min_price=1.0,
        min_quantity=0.0001,
    )


def candles(count: int = 25) -> list[Candle]:
    return [
        Candle(
            timestamp=1700000000 + index * 60,
            open=100 + index,
            high=105 + index,
            low=95 + index,
            close=100 + index,
            volume=1.0,
        )
        for index in range(count)
    ]


def test_atr_and_bollinger_calculate_from_known_candles() -> None:
    sample = candles()

    assert calculate_atr(sample) == 10.0
    mid, upper, lower = calculate_bollinger(sample)

    assert round(mid, 2) == 114.5
    assert round(upper, 4) == 126.0326
    assert round(lower, 4) == 102.9674


def test_spacing_uses_fee_barrier_when_fee_is_wider() -> None:
    spacing, applied = calculate_spacing(
        atr=1.0,
        atr_multiplier=1.0,
        current_price=1000.0,
        maker_fee_rate=0.001,
    )

    assert spacing == 2.5
    assert applied is True


def test_center_moves_only_beyond_half_atr() -> None:
    assert update_center_price(104.0, 100.0, 10.0) == 100.0
    assert update_center_price(106.0, 100.0, 10.0) == 106.0


def test_bollinger_bias_mapping() -> None:
    indicators = IndicatorSnapshot(
        atr14=10.0,
        bollinger_mid=100.0,
        bollinger_upper=110.0,
        bollinger_lower=90.0,
    )

    assert determine_bias(89.0, indicators) == Bias.LONG_ONLY
    assert determine_bias(111.0, indicators) == Bias.SELL_ONLY
    assert determine_bias(100.0, indicators) == Bias.NEUTRAL


def test_desired_orders_respect_inventory_and_spot_sells() -> None:
    cfg = config()
    indicators = IndicatorSnapshot(atr14=10.0, bollinger_mid=100.0, bollinger_upper=120.0, bollinger_lower=80.0)
    balance = Balance(base_free=0.1, quote_free=1000.0)
    grid, fee_barrier = build_grid_state(cfg, indicators, 100.0, None, balance)
    risk = cfg_risk(buys_enabled=True, sells_enabled=True, fee_barrier_applied=fee_barrier)

    desired = generate_desired_orders(cfg, grid, risk, balance)

    assert [order.side for order in desired].count(Side.BUY) == 1
    assert [order.side for order in desired].count(Side.SELL) == 1


def test_dual_atr_and_ev_spacing_drive_effective_spacing() -> None:
    cfg = config()
    indicators = IndicatorSnapshot(
        atr14=1.0,
        atr_fast=4.0,
        atr_slow=2.0,
        bollinger_mid=100.0,
        bollinger_upper=120.0,
        bollinger_lower=80.0,
    )
    grid, _ = build_grid_state(cfg, indicators, 100.0, None, Balance(0.0, 1000.0))

    assert grid.effective_atr == 4.0
    assert grid.spacing == 4.0
    assert round(calculate_ev_min_spacing(cfg, 100.0), 4) == 0.11


def test_ev_spacing_uses_maker_only_roundtrip_divided_by_two() -> None:
    cfg = BotConfig(
        **{
            **config().__dict__,
            "maker_fee_rate": 0.001,
            "taker_fee_rate": 0.01,
            "simulated_slippage_bps": 50.0,
            "ev_safety_multiplier": 1.10,
        }
    )

    assert round(calculate_ev_min_spacing(cfg, 77_800.0), 2) == 85.58


def test_ev_pause_when_spacing_cap_is_exceeded() -> None:
    cfg = BotConfig(**{**config().__dict__, "max_ev_spacing_pct": 0.001})
    indicators = IndicatorSnapshot(
        atr14=0.01,
        atr_fast=0.01,
        atr_slow=0.01,
        bollinger_mid=100.0,
        bollinger_upper=120.0,
        bollinger_lower=80.0,
    )
    balance = Balance(0.0, 1000.0)
    grid, fee_barrier = build_grid_state(cfg, indicators, 100.0, None, balance)
    risk = compute_risk_state(cfg, balance, 100.0, 1000.0, False, fee_barrier, grid.ev_positive)

    assert grid.ev_positive is False
    assert risk.buys_enabled is False
    assert risk.reason == "negative ev spacing cap"


def test_hard_fee_barrier_still_applies_when_ev_spacing_is_lower() -> None:
    cfg = config()
    indicators = IndicatorSnapshot(
        atr14=0.01,
        atr_fast=0.01,
        atr_slow=0.01,
        bollinger_mid=100.0,
        bollinger_upper=120.0,
        bollinger_lower=80.0,
    )

    grid, fee_barrier = build_grid_state(cfg, indicators, 100.0, None, Balance(0.0, 1000.0))

    assert grid.ev_min_spacing == 0.11000000000000001
    assert grid.spacing == 0.25
    assert fee_barrier is True


def test_center_hysteresis_requires_atr_and_percent_gates() -> None:
    center, recentered = update_center_price_with_hysteresis(100.2, 100.0, 0.1, 0.01)
    assert center == 100.0
    assert recentered is False

    center, recentered = update_center_price_with_hysteresis(101.2, 100.0, 0.1, 0.01)
    assert center == 101.2
    assert recentered is True


def test_spacing_hysteresis_keeps_grid_from_repricing_on_tiny_atr_changes() -> None:
    spacing, changed = update_spacing_with_hysteresis(
        raw_spacing=100.5,
        previous_spacing=100.0,
        hard_min_spacing=50.0,
        spacing_hysteresis_pct=0.01,
    )
    assert spacing == 100.0
    assert changed is False

    spacing, changed = update_spacing_with_hysteresis(
        raw_spacing=102.0,
        previous_spacing=100.0,
        hard_min_spacing=50.0,
        spacing_hysteresis_pct=0.01,
    )
    assert spacing == 102.0
    assert changed is True

    spacing, changed = update_spacing_with_hysteresis(
        raw_spacing=101.0,
        previous_spacing=100.0,
        hard_min_spacing=100.5,
        spacing_hysteresis_pct=0.01,
    )
    assert spacing == 101.0
    assert changed is True


def test_trend_following_bias_and_counter_trend_pause() -> None:
    cfg = BotConfig(**{**config().__dict__, "bias_mode": "trend_following"})
    indicators = IndicatorSnapshot(
        atr14=1.0,
        atr_fast=1.0,
        atr_slow=1.0,
        bollinger_mid=100.0,
        bollinger_upper=110.0,
        bollinger_lower=90.0,
        ema_fast=105.0,
        ema_slow=100.0,
        closes_above_upper=3,
    )
    balance = Balance(base_free=0.1, quote_free=1000.0)
    grid, fee_barrier = build_grid_state(cfg, indicators, 112.0, None, balance)
    risk = cfg_risk(True, True, fee_barrier)
    desired = generate_desired_orders(cfg, grid, risk, balance)

    assert determine_bias_with_mode(112.0, indicators, "trend_following", "bullish_momentum") == Bias.LONG_ONLY
    assert grid.trend_state == "bullish_momentum"
    assert all(order.side == Side.BUY for order in desired)


def test_inventory_weighted_spacing_widens_buy_side() -> None:
    cfg = config()
    indicators = IndicatorSnapshot(
        atr14=10.0,
        atr_fast=10.0,
        atr_slow=10.0,
        bollinger_mid=100.0,
        bollinger_upper=120.0,
        bollinger_lower=80.0,
    )
    grid, _ = build_grid_state(cfg, indicators, 100.0, None, Balance(0.18, 1000.0))

    assert round(grid.inventory_ratio, 4) == 0.9
    assert grid.buy_spacing > grid.sell_spacing
    assert grid.inventory_skew_cost_quote > 0


def test_structural_exit_signal_on_bearish_break() -> None:
    cfg = config()
    sample = [
        Candle(1700000000 + index * 60, 100.0, 101.0, 99.0, 100.0, 1.0)
        for index in range(21)
    ]
    sample.append(Candle(1700001260, 98.0, 99.0, 90.0, 90.0, 1.0))
    indicators = IndicatorSnapshot(
        atr14=10.0,
        atr_fast=10.0,
        atr_slow=10.0,
        bollinger_mid=100.0,
        bollinger_upper=120.0,
        bollinger_lower=80.0,
        ema_fast=90.0,
        ema_slow=100.0,
    )

    assert structural_exit_signal(cfg, sample, indicators, Balance(0.1, 1000.0)) == "structure_break"


def cfg_risk(
    buys_enabled: bool,
    sells_enabled: bool,
    fee_barrier_applied: bool,
):
    from dynogrid.models import RiskState

    return RiskState(
        buys_enabled=buys_enabled,
        sells_enabled=sells_enabled,
        fee_barrier_applied=fee_barrier_applied,
        paper_stop_loss_breached=False,
        paused=False,
    )
