from __future__ import annotations

import pytest

from dynogrid.exchange.paper import PaperExchangeGateway
from dynogrid.models import BotConfig, Candle, DesiredOrder, Side


def config() -> BotConfig:
    return BotConfig(
        symbol="BTC/USDT",
        timeframe="1m",
        grid_count=1,
        atr_multiplier=1.0,
        order_size=1.0,
        max_inventory=2.0,
        maker_fee_rate=0.001,
        starting_base=0.0,
        starting_quote=200.0,
        db_path=":memory:",
        min_price=1.0,
        min_quantity=0.1,
    )


@pytest.mark.asyncio
async def test_paper_buy_fills_on_candle_touch_and_applies_fee() -> None:
    gateway = PaperExchangeGateway(config())
    order = DesiredOrder("buy-1", Side.BUY, 100.0, 1.0)

    await gateway.create_order(order, timestamp=1)
    fills = await gateway.process_candle(
        Candle(timestamp=2, open=101.0, high=102.0, low=99.0, close=101.0, volume=1.0)
    )
    balance = await gateway.balance()

    assert len(fills) == 1
    assert fills[0].fee == 0.1
    assert balance.base_free == 1.0
    assert round(balance.quote_total, 8) == 99.9
