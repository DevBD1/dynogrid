from __future__ import annotations

from typing import Protocol

from dynogrid.models import Balance, Candle, DesiredOrder, Fill, Order


class ExchangeGateway(Protocol):
    async def open_orders(self) -> list[Order]:
        ...

    async def create_order(self, order: DesiredOrder, timestamp: int) -> Order:
        ...

    async def cancel_order(self, client_order_id: str, timestamp: int) -> Order | None:
        ...

    async def process_candle(self, candle: Candle) -> list[Fill]:
        ...

    async def balance(self) -> Balance:
        ...
