from __future__ import annotations

from dynogrid.models import Balance, BotConfig, Candle, DesiredOrder, Fill, Order


class LiveTradingDisabledError(RuntimeError):
    pass


class BinanceCcxtGateway:
    """Boundary for a future Binance CCXT adapter.

    V1 is paper-first. This class exists so live execution work has an explicit
    place to enforce post-only orders, precision filters, and CCXT backoff.
    """

    def __init__(self, config: BotConfig) -> None:
        self.config = config

    async def open_orders(self) -> list[Order]:
        raise LiveTradingDisabledError(
            "live trading disabled until safety gates are implemented"
        )

    async def create_order(self, order: DesiredOrder, timestamp: int) -> Order:
        if not order.post_only:
            raise ValueError("live orders must be post-only")
        raise LiveTradingDisabledError(
            "live trading disabled until safety gates are implemented"
        )

    async def cancel_order(self, client_order_id: str, timestamp: int) -> Order | None:
        raise LiveTradingDisabledError(
            "live trading disabled until safety gates are implemented"
        )

    async def process_candle(self, candle: Candle) -> list[Fill]:
        raise LiveTradingDisabledError(
            "live trading disabled until safety gates are implemented"
        )

    async def balance(self) -> Balance:
        raise LiveTradingDisabledError(
            "live trading disabled until safety gates are implemented"
        )

    async def flatten(self, price: float, timestamp: int) -> Fill | None:
        raise LiveTradingDisabledError(
            "live trading disabled until safety gates are implemented"
        )
