from __future__ import annotations

from dynogrid.models import Balance, Bias, BotConfig, Candle, IndicatorSnapshot, Side
from dynogrid.strategy.grid import (
    build_grid_state,
    calculate_spacing,
    determine_bias,
    generate_desired_orders,
    update_center_price,
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
