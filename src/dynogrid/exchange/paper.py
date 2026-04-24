from __future__ import annotations

from dynogrid.models import (
    Balance,
    BotConfig,
    Candle,
    DesiredOrder,
    Fill,
    Order,
    OrderStatus,
    Side,
)


class PaperExchangeGateway:
    def __init__(self, config: BotConfig) -> None:
        self.config = config
        self._balance = Balance(
            base_free=config.starting_base,
            quote_free=config.starting_quote,
        )
        self._orders: dict[str, Order] = {}

    async def open_orders(self) -> list[Order]:
        return [order for order in self._orders.values() if order.status == OrderStatus.OPEN]

    async def create_order(self, order: DesiredOrder, timestamp: int) -> Order:
        if not order.post_only:
            raise ValueError("paper gateway only accepts post-only desired orders")
        if order.price < self.config.min_price:
            raise ValueError("order price below min_price")
        if order.quantity < self.config.min_quantity:
            raise ValueError("order quantity below min_quantity")

        if order.side == Side.BUY:
            reserve = order.price * order.quantity
            fee = reserve * self.config.maker_fee_rate
            if self._balance.quote_free < reserve + fee:
                raise ValueError("insufficient quote balance for paper buy order")
            self._balance = Balance(
                base_free=self._balance.base_free,
                quote_free=self._balance.quote_free - reserve - fee,
                base_locked=self._balance.base_locked,
                quote_locked=self._balance.quote_locked + reserve + fee,
            )
        else:
            if self._balance.base_free < order.quantity:
                raise ValueError("insufficient base balance for paper sell order")
            self._balance = Balance(
                base_free=self._balance.base_free - order.quantity,
                quote_free=self._balance.quote_free,
                base_locked=self._balance.base_locked + order.quantity,
                quote_locked=self._balance.quote_locked,
            )

        created = Order(
            client_order_id=order.client_order_id,
            exchange_order_id=f"paper-{order.client_order_id}",
            side=order.side,
            price=order.price,
            quantity=order.quantity,
            status=OrderStatus.OPEN,
            created_at=timestamp,
            updated_at=timestamp,
        )
        self._orders[created.client_order_id] = created
        return created

    async def cancel_order(self, client_order_id: str, timestamp: int) -> Order | None:
        order = self._orders.get(client_order_id)
        if order is None or order.status != OrderStatus.OPEN:
            return None
        if order.side == Side.BUY:
            reserve = order.price * order.quantity
            fee = reserve * self.config.maker_fee_rate
            self._balance = Balance(
                base_free=self._balance.base_free,
                quote_free=self._balance.quote_free + reserve + fee,
                base_locked=self._balance.base_locked,
                quote_locked=self._balance.quote_locked - reserve - fee,
            )
        else:
            self._balance = Balance(
                base_free=self._balance.base_free + order.quantity,
                quote_free=self._balance.quote_free,
                base_locked=self._balance.base_locked - order.quantity,
                quote_locked=self._balance.quote_locked,
            )
        canceled = Order(
            client_order_id=order.client_order_id,
            exchange_order_id=order.exchange_order_id,
            side=order.side,
            price=order.price,
            quantity=order.quantity,
            status=OrderStatus.CANCELED,
            created_at=order.created_at,
            updated_at=timestamp,
        )
        self._orders[client_order_id] = canceled
        return canceled

    async def process_candle(self, candle: Candle) -> list[Fill]:
        fills: list[Fill] = []
        for order in list(await self.open_orders()):
            should_fill = (
                order.side == Side.BUY
                and candle.low <= order.price
                or order.side == Side.SELL
                and candle.high >= order.price
            )
            if not should_fill:
                continue
            fills.append(self._fill_order(order, candle.timestamp))
        return fills

    async def flatten(self, price: float, timestamp: int) -> Fill | None:
        for order in list(await self.open_orders()):
            await self.cancel_order(order.client_order_id, timestamp)
        quantity = round(self._balance.base_free, self.config.quantity_precision)
        if quantity < self.config.min_quantity:
            return None
        proceeds = price * quantity
        fee = proceeds * self.config.maker_fee_rate
        self._balance = Balance(
            base_free=0.0,
            quote_free=self._balance.quote_free + proceeds - fee,
            base_locked=self._balance.base_locked,
            quote_locked=self._balance.quote_locked,
        )
        return Fill(
            client_order_id="paper-flatten",
            side=Side.SELL,
            price=price,
            quantity=quantity,
            fee=fee,
            timestamp=timestamp,
        )

    async def balance(self) -> Balance:
        return self._balance

    def _fill_order(self, order: Order, timestamp: int) -> Fill:
        notional = order.price * order.quantity
        fee = notional * self.config.maker_fee_rate
        if order.side == Side.BUY:
            self._balance = Balance(
                base_free=self._balance.base_free + order.quantity,
                quote_free=self._balance.quote_free,
                base_locked=self._balance.base_locked,
                quote_locked=self._balance.quote_locked - notional - fee,
            )
        else:
            self._balance = Balance(
                base_free=self._balance.base_free,
                quote_free=self._balance.quote_free + notional - fee,
                base_locked=self._balance.base_locked - order.quantity,
                quote_locked=self._balance.quote_locked,
            )
        filled = Order(
            client_order_id=order.client_order_id,
            exchange_order_id=order.exchange_order_id,
            side=order.side,
            price=order.price,
            quantity=order.quantity,
            status=OrderStatus.FILLED,
            created_at=order.created_at,
            updated_at=timestamp,
        )
        self._orders[order.client_order_id] = filled
        return Fill(
            client_order_id=order.client_order_id,
            side=order.side,
            price=order.price,
            quantity=order.quantity,
            fee=fee,
            timestamp=timestamp,
        )
