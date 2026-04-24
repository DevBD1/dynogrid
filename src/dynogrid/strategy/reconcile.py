from __future__ import annotations

from dataclasses import dataclass

from dynogrid.models import DesiredOrder, Order, OrderStatus, Side


@dataclass(frozen=True)
class ReconcilePlan:
    cancel_order_ids: list[str]
    create_orders: list[DesiredOrder]
    keep_order_ids: list[str]


def diff_orders(open_orders: list[Order], desired_orders: list[DesiredOrder]) -> ReconcilePlan:
    active = [order for order in open_orders if order.status == OrderStatus.OPEN]
    desired_by_key = {_order_key(order): order for order in desired_orders}
    active_by_key = {_order_key(order): order for order in active}

    cancel_ids = [
        order.client_order_id for key, order in active_by_key.items() if key not in desired_by_key
    ]
    keep_ids = [
        order.client_order_id for key, order in active_by_key.items() if key in desired_by_key
    ]
    create_orders = [
        order for key, order in desired_by_key.items() if key not in active_by_key
    ]
    return ReconcilePlan(
        cancel_order_ids=cancel_ids,
        create_orders=create_orders,
        keep_order_ids=keep_ids,
    )


def _order_key(order: DesiredOrder | Order) -> tuple[Side, float, float]:
    return order.side, order.price, order.quantity
