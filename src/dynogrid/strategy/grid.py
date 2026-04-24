from __future__ import annotations

from dynogrid.models import (
    Balance,
    Bias,
    BotConfig,
    DesiredOrder,
    GridState,
    IndicatorSnapshot,
    RiskState,
    Side,
)


def calculate_spacing(
    atr: float, atr_multiplier: float, current_price: float, maker_fee_rate: float
) -> tuple[float, bool]:
    atr_spacing = atr * atr_multiplier
    fee_spacing = current_price * maker_fee_rate * 2.5
    return max(atr_spacing, fee_spacing), fee_spacing > atr_spacing


def update_center_price(
    current_price: float, previous_center: float | None, atr: float
) -> float:
    if previous_center is None:
        return current_price
    if abs(current_price - previous_center) > 0.5 * atr:
        return current_price
    return previous_center


def determine_bias(close_price: float, indicators: IndicatorSnapshot) -> Bias:
    if close_price < indicators.bollinger_lower:
        return Bias.LONG_ONLY
    if close_price > indicators.bollinger_upper:
        return Bias.SELL_ONLY
    return Bias.NEUTRAL


def compute_risk_state(
    config: BotConfig,
    balance: Balance,
    current_price: float,
    starting_equity: float,
    paused: bool,
    fee_barrier_applied: bool,
) -> RiskState:
    equity = mark_equity(balance, current_price)
    stop_breached = equity < starting_equity * (1.0 - config.stop_loss_pct)
    buys_enabled = balance.base_total < config.max_inventory and not paused and not stop_breached
    sells_enabled = balance.base_free >= config.min_quantity and not paused and not stop_breached
    reason = ""
    if paused:
        reason = "paused"
    elif stop_breached:
        reason = "paper stop loss breached"
    elif not buys_enabled:
        reason = "max inventory reached"
    return RiskState(
        buys_enabled=buys_enabled,
        sells_enabled=sells_enabled,
        fee_barrier_applied=fee_barrier_applied,
        paper_stop_loss_breached=stop_breached,
        paused=paused,
        reason=reason,
    )


def mark_equity(balance: Balance, current_price: float) -> float:
    return balance.quote_total + balance.base_total * current_price


def build_grid_state(
    config: BotConfig,
    indicators: IndicatorSnapshot,
    current_price: float,
    previous_center: float | None,
    balance: Balance,
) -> tuple[GridState, bool]:
    spacing, fee_barrier_applied = calculate_spacing(
        indicators.atr14,
        config.atr_multiplier,
        current_price,
        config.maker_fee_rate,
    )
    center = update_center_price(current_price, previous_center, indicators.atr14)
    bias = determine_bias(current_price, indicators)
    return (
        GridState(
            center_price=center,
            spacing=spacing,
            bias=bias,
            current_inventory=balance.base_total,
            max_inventory=config.max_inventory,
        ),
        fee_barrier_applied,
    )


def generate_desired_orders(
    config: BotConfig,
    grid: GridState,
    risk: RiskState,
    balance: Balance,
) -> list[DesiredOrder]:
    desired: list[DesiredOrder] = []
    planned_base = balance.base_total
    available_base = balance.base_free

    if grid.bias in {Bias.NEUTRAL, Bias.LONG_ONLY} and risk.buys_enabled:
        for level in range(1, config.grid_count + 1):
            if planned_base + config.order_size > config.max_inventory:
                break
            price = normalize_price(config, grid.center_price - level * grid.spacing)
            quantity = normalize_quantity(config, config.order_size)
            if price >= config.min_price and quantity >= config.min_quantity:
                desired.append(
                    DesiredOrder(
                        client_order_id=client_order_id(config, Side.BUY, level, price, quantity),
                        side=Side.BUY,
                        price=price,
                        quantity=quantity,
                        post_only=True,
                    )
                )
                planned_base += quantity

    if grid.bias in {Bias.NEUTRAL, Bias.SELL_ONLY} and risk.sells_enabled:
        for level in range(1, config.grid_count + 1):
            quantity = normalize_quantity(config, config.order_size)
            if available_base < quantity:
                break
            price = normalize_price(config, grid.center_price + level * grid.spacing)
            if price >= config.min_price and quantity >= config.min_quantity:
                desired.append(
                    DesiredOrder(
                        client_order_id=client_order_id(config, Side.SELL, level, price, quantity),
                        side=Side.SELL,
                        price=price,
                        quantity=quantity,
                        post_only=True,
                    )
                )
                available_base -= quantity

    return desired


def normalize_price(config: BotConfig, price: float) -> float:
    return round(price, config.price_precision)


def normalize_quantity(config: BotConfig, quantity: float) -> float:
    return round(quantity, config.quantity_precision)


def client_order_id(
    config: BotConfig, side: Side, level: int, price: float, quantity: float
) -> str:
    symbol = config.symbol.replace("/", "")
    return f"dg-{symbol}-{side.value}-{level}-{price:.{config.price_precision}f}-{quantity:.{config.quantity_precision}f}"
