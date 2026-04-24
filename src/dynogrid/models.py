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


@dataclass(frozen=True)
class GridState:
    center_price: float
    spacing: float
    bias: Bias
    current_inventory: float
    max_inventory: float


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
