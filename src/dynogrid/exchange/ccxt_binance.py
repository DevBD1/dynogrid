from __future__ import annotations

from dynogrid.models import DesiredOrder


class LiveTradingDisabledError(RuntimeError):
    pass


class BinanceCcxtGateway:
    """Boundary for a future Binance CCXT adapter.

    V1 is paper-first. This class exists so live execution work has an explicit
    place to enforce post-only orders, precision filters, and CCXT backoff.
    """

    async def create_order(self, order: DesiredOrder, timestamp: int) -> None:
        if not order.post_only:
            raise ValueError("live orders must be post-only")
        raise LiveTradingDisabledError("live order placement is disabled in V1")
