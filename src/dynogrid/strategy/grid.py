from __future__ import annotations

from dynogrid.models import (
    Balance,
    Bias,
    BiasMode,
    BotConfig,
    Candle,
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


def calculate_ev_min_spacing(config: BotConfig, current_price: float) -> float:
    ev_min_roundtrip = current_price * (2.0 * config.maker_fee_rate) * config.ev_safety_multiplier
    return ev_min_roundtrip / 2.0


def calculate_inventory_ratio(balance: Balance, max_inventory: float) -> float:
    if max_inventory <= 0:
        return 1.0
    return min(max(balance.base_total / max_inventory, 0.0), 1.0)


def calculate_inventory_spacing_multiplier(config: BotConfig, inventory_ratio: float) -> float:
    threshold = config.inventory_spacing_threshold
    if inventory_ratio <= threshold:
        return 1.0
    denominator = max(1.0 - threshold, 1e-12)
    pressure = min((inventory_ratio - threshold) / denominator, 1.0)
    return 1.0 + pressure * config.inventory_spacing_max_multiplier


def update_center_price(
    current_price: float, previous_center: float | None, atr: float
) -> float:
    if previous_center is None:
        return current_price
    if abs(current_price - previous_center) > 0.5 * atr:
        return current_price
    return previous_center


def update_center_price_with_hysteresis(
    current_price: float,
    previous_center: float | None,
    effective_atr: float,
    recenter_hysteresis_pct: float,
) -> tuple[float, bool]:
    if previous_center is None:
        return current_price, True
    distance = abs(current_price - previous_center)
    atr_gate = distance > 0.5 * effective_atr
    pct_gate = distance > previous_center * recenter_hysteresis_pct
    if atr_gate and pct_gate:
        return current_price, True
    return previous_center, False


def update_spacing_with_hysteresis(
    raw_spacing: float,
    previous_spacing: float | None,
    hard_min_spacing: float,
    spacing_hysteresis_pct: float,
) -> tuple[float, bool]:
    if previous_spacing is None:
        return raw_spacing, True
    if previous_spacing < hard_min_spacing:
        return raw_spacing, True
    threshold = previous_spacing * spacing_hysteresis_pct
    if abs(raw_spacing - previous_spacing) > threshold:
        return raw_spacing, True
    return previous_spacing, False


def determine_bias(close_price: float, indicators: IndicatorSnapshot) -> Bias:
    if close_price < indicators.bollinger_lower:
        return Bias.LONG_ONLY
    if close_price > indicators.bollinger_upper:
        return Bias.SELL_ONLY
    return Bias.NEUTRAL


def determine_trend_state(
    indicators: IndicatorSnapshot, outside_band_consecutive: int
) -> str:
    bullish_ema = indicators.ema_fast > indicators.ema_slow
    bearish_ema = indicators.ema_fast < indicators.ema_slow
    if indicators.closes_above_upper >= outside_band_consecutive and bullish_ema:
        return "bullish_momentum"
    if indicators.closes_below_lower >= outside_band_consecutive and bearish_ema:
        return "bearish_momentum"
    if bullish_ema:
        return "bullish"
    if bearish_ema:
        return "bearish"
    return "neutral"


def determine_bias_with_mode(
    close_price: float,
    indicators: IndicatorSnapshot,
    bias_mode: str,
    trend_state: str,
) -> Bias:
    mean_reversion_bias = determine_bias(close_price, indicators)
    momentum_bias = Bias.NEUTRAL
    if trend_state.startswith("bullish"):
        momentum_bias = Bias.LONG_ONLY
    elif trend_state.startswith("bearish"):
        momentum_bias = Bias.SELL_ONLY

    if bias_mode == BiasMode.MEAN_REVERSION.value:
        return mean_reversion_bias
    if bias_mode == BiasMode.TREND_FOLLOWING.value:
        return momentum_bias
    if trend_state in {"bullish_momentum", "bearish_momentum"}:
        return momentum_bias
    return mean_reversion_bias


def should_pause_counter_trend_entries(grid: GridState, side: Side) -> bool:
    if not grid.counter_trend_paused:
        return False
    if grid.trend_state == "bullish_momentum" and side == Side.SELL:
        return True
    if grid.trend_state == "bearish_momentum" and side == Side.BUY:
        return True
    return False


def compute_risk_state(
    config: BotConfig,
    balance: Balance,
    current_price: float,
    starting_equity: float,
    paused: bool,
    fee_barrier_applied: bool,
    ev_positive: bool = True,
    trend_state: str = "neutral",
    exit_signal: str = "",
) -> RiskState:
    equity = mark_equity(balance, current_price)
    stop_breached = equity < starting_equity * (1.0 - config.stop_loss_pct)
    blocked = paused or stop_breached or not ev_positive or bool(exit_signal)
    buys_enabled = balance.base_total < config.max_inventory and not blocked
    sells_enabled = balance.base_free >= config.min_quantity and not blocked
    reason = ""
    if paused:
        reason = "paused"
    elif stop_breached:
        reason = "paper stop loss breached"
    elif exit_signal:
        reason = exit_signal
    elif not ev_positive:
        reason = "negative ev spacing cap"
    elif not buys_enabled:
        reason = "max inventory reached"
    return RiskState(
        buys_enabled=buys_enabled,
        sells_enabled=sells_enabled,
        fee_barrier_applied=fee_barrier_applied,
        paper_stop_loss_breached=stop_breached,
        paused=paused,
        reason=reason,
        ev_positive=ev_positive,
        trend_state=trend_state,
        exit_signal=exit_signal,
    )


def mark_equity(balance: Balance, current_price: float) -> float:
    return balance.quote_total + balance.base_total * current_price


def build_grid_state(
    config: BotConfig,
    indicators: IndicatorSnapshot,
    current_price: float,
    previous_center: float | None,
    balance: Balance,
    previous_spacing: float | None = None,
) -> tuple[GridState, bool]:
    effective_atr = max(indicators.atr14, indicators.atr_fast, indicators.atr_slow)
    atr_spacing, _ = calculate_spacing(
        effective_atr,
        config.atr_multiplier,
        current_price,
        0.0,
    )
    ev_min_spacing = calculate_ev_min_spacing(config, current_price)
    fee_spacing = current_price * config.maker_fee_rate * 2.5
    raw_spacing = max(atr_spacing, ev_min_spacing, fee_spacing)
    fee_barrier_applied = fee_spacing > atr_spacing or ev_min_spacing > atr_spacing
    ev_positive = ev_min_spacing <= current_price * config.max_ev_spacing_pct
    center, recentered = update_center_price_with_hysteresis(
        current_price,
        previous_center,
        effective_atr,
        config.recenter_hysteresis_pct,
    )
    spacing, spacing_changed = update_spacing_with_hysteresis(
        raw_spacing=raw_spacing,
        previous_spacing=previous_spacing,
        hard_min_spacing=max(ev_min_spacing, fee_spacing),
        spacing_hysteresis_pct=config.spacing_hysteresis_pct,
    )
    trend_state = determine_trend_state(indicators, config.outside_band_consecutive)
    bias = determine_bias_with_mode(current_price, indicators, config.bias_mode, trend_state)
    inventory_ratio = calculate_inventory_ratio(balance, config.max_inventory)
    buy_multiplier = calculate_inventory_spacing_multiplier(config, inventory_ratio)
    buy_spacing = spacing * buy_multiplier
    sell_spacing = spacing
    volatility_ratio = effective_atr / indicators.atr_slow if indicators.atr_slow else 1.0
    inventory_skew_cost_quote = max(buy_spacing - sell_spacing, 0.0) * balance.base_total
    counter_trend_paused = trend_state in {"bullish_momentum", "bearish_momentum"}
    return (
        GridState(
            center_price=center,
            spacing=spacing,
            bias=bias,
            current_inventory=balance.base_total,
            max_inventory=config.max_inventory,
            buy_spacing=buy_spacing,
            sell_spacing=sell_spacing,
            effective_atr=effective_atr,
            atr_fast=indicators.atr_fast,
            atr_slow=indicators.atr_slow,
            ev_min_spacing=ev_min_spacing,
            ev_positive=ev_positive,
            volatility_ratio=volatility_ratio,
            inventory_ratio=inventory_ratio,
            grid_recentered=recentered or spacing_changed,
            trend_state=trend_state,
            counter_trend_paused=counter_trend_paused,
            inventory_skew_cost_quote=inventory_skew_cost_quote,
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
            if should_pause_counter_trend_entries(grid, Side.BUY):
                break
            if planned_base + config.order_size > config.max_inventory:
                break
            buy_spacing = grid.buy_spacing or grid.spacing
            price = normalize_price(config, grid.center_price - level * buy_spacing)
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
            if should_pause_counter_trend_entries(grid, Side.SELL):
                break
            quantity = normalize_quantity(config, config.order_size)
            if available_base < quantity:
                break
            sell_spacing = grid.sell_spacing or grid.spacing
            price = normalize_price(config, grid.center_price + level * sell_spacing)
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


def structural_exit_signal(
    config: BotConfig,
    candles: list[Candle],
    indicators: IndicatorSnapshot,
    balance: Balance,
) -> str:
    if balance.base_total < config.min_quantity:
        return ""
    if len(candles) < config.structure_lookback + 1:
        return ""
    recent = candles[-config.structure_lookback - 1 : -1]
    structure_low = min(candle.low for candle in recent)
    current = candles[-1]
    buffer = indicators.atr14 * config.structure_break_atr_buffer
    bearish_ema = indicators.ema_fast < indicators.ema_slow
    if bearish_ema and current.close < structure_low - buffer:
        return "structure_break"
    return ""


def normalize_price(config: BotConfig, price: float) -> float:
    return round(price, config.price_precision)


def normalize_quantity(config: BotConfig, quantity: float) -> float:
    return round(quantity, config.quantity_precision)


def client_order_id(
    config: BotConfig, side: Side, level: int, price: float, quantity: float
) -> str:
    symbol = config.symbol.replace("/", "")
    return f"dg-{symbol}-{side.value}-{level}-{price:.{config.price_precision}f}-{quantity:.{config.quantity_precision}f}"
