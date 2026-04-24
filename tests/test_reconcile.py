from __future__ import annotations

from dynogrid.models import DesiredOrder, Order, OrderStatus, Side
from dynogrid.strategy.reconcile import diff_orders


def test_reconcile_keeps_matching_and_replaces_stale_orders() -> None:
    existing = [
        Order("keep", Side.BUY, 99.0, 1.0, OrderStatus.OPEN, 1, 1),
        Order("stale", Side.SELL, 105.0, 1.0, OrderStatus.OPEN, 1, 1),
    ]
    desired = [
        DesiredOrder("new-keep-id", Side.BUY, 99.0, 1.0),
        DesiredOrder("create", Side.SELL, 106.0, 1.0),
    ]

    plan = diff_orders(existing, desired)

    assert plan.keep_order_ids == ["keep"]
    assert plan.cancel_order_ids == ["stale"]
    assert [order.client_order_id for order in plan.create_orders] == ["create"]
