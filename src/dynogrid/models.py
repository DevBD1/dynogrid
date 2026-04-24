from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


class Bias(str, Enum):
    NEUTRAL = "neutral"
    LONG_ONLY = "long_only"
    SELL_ONLY = "sell_only"


class BiasMode(str, Enum):
    AUTO = "auto"
    MEAN_REVERSION = "mean_reversion"
    TREND_FOLLOWING = "trend_following"


class OrderStatus(str, Enum):
    OPEN = "open"
    CANCELED = "canceled"
    FILLED = "filled"


@dataclass(frozen=True)
class BotConfig:
    symbol: str
    timeframe: str
    grid_count: int
    atr_multiplier: float
    order_size: float
    max_inventory: float
    maker_fee_rate: float
    starting_base: float
    starting_quote: float
    db_path: str
    exchange_id: str = "binance"
    price_precision: int = 2
    quantity_precision: int = 6
    min_price: float = 0.0
    min_quantity: float = 0.0
    stop_loss_pct: float = 0.10
    loop_interval_seconds: int = 60
    recenter_hysteresis_pct: float = 0.001
    atr_fast_period: int = 7
    atr_slow_period: int = 28
    taker_fee_rate: float = 0.001
    simulated_slippage_bps: float = 1.0
    ev_safety_multiplier: float = 1.10
    max_ev_spacing_pct: float = 0.02
    bias_mode: str = BiasMode.AUTO.value
    ema_fast_period: int = 9
    ema_slow_period: int = 21
    outside_band_consecutive: int = 3
    structure_lookback: int = 20
    structure_break_atr_buffer: float = 0.25
    inventory_spacing_threshold: float = 0.70
    inventory_spacing_max_multiplier: float = 1.0


@dataclass(frozen=True)
class Candle:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class IndicatorSnapshot:
    atr14: float
    bollinger_mid: float
    bollinger_upper: float
    bollinger_lower: float
    atr_fast: float = 0.0
    atr_slow: float = 0.0
    ema_fast: float = 0.0
    ema_slow: float = 0.0
    closes_above_upper: int = 0
    closes_below_lower: int = 0


@dataclass(frozen=True)
class GridState:
    center_price: float
    spacing: float
    bias: Bias
    current_inventory: float
    max_inventory: float
    buy_spacing: float = 0.0
    sell_spacing: float = 0.0
    effective_atr: float = 0.0
    atr_fast: float = 0.0
    atr_slow: float = 0.0
    ev_min_spacing: float = 0.0
    ev_positive: bool = True
    volatility_ratio: float = 1.0
    inventory_ratio: float = 0.0
    grid_recentered: bool = False
    trend_state: str = "neutral"
    counter_trend_paused: bool = False
    inventory_skew_cost_quote: float = 0.0


@dataclass(frozen=True)
class DesiredOrder:
    client_order_id: str
    side: Side
    price: float
    quantity: float
    post_only: bool = True


@dataclass(frozen=True)
class Order:
    client_order_id: str
    side: Side
    price: float
    quantity: float
    status: OrderStatus
    created_at: int
    updated_at: int
    exchange_order_id: str | None = None


@dataclass(frozen=True)
class Fill:
    client_order_id: str
    side: Side
    price: float
    quantity: float
    fee: float
    timestamp: int


@dataclass(frozen=True)
class Balance:
    base_free: float
    quote_free: float
    base_locked: float = 0.0
    quote_locked: float = 0.0

    @property
    def base_total(self) -> float:
        return self.base_free + self.base_locked

    @property
    def quote_total(self) -> float:
        return self.quote_free + self.quote_locked


@dataclass(frozen=True)
class RiskState:
    buys_enabled: bool
    sells_enabled: bool
    fee_barrier_applied: bool
    paper_stop_loss_breached: bool
    paused: bool
    reason: str = ""
    ev_positive: bool = True
    trend_state: str = "neutral"
    exit_signal: str = ""
