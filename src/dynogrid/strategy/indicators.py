from __future__ import annotations

import pandas as pd

from dynogrid.models import Candle, IndicatorSnapshot


def calculate_atr(candles: list[Candle], period: int = 14) -> float:
    if len(candles) < period + 1:
        raise ValueError(f"Need at least {period + 1} candles for ATR({period})")
    frame = _to_frame(candles)
    previous_close = frame["close"].shift(1)
    true_range = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = true_range.rolling(window=period, min_periods=period).mean().iloc[-1]
    if pd.isna(atr):
        raise ValueError(f"Could not calculate ATR({period})")
    return float(atr)


def calculate_bollinger(
    candles: list[Candle], period: int = 20, stddev: float = 2.0
) -> tuple[float, float, float]:
    if len(candles) < period:
        raise ValueError(f"Need at least {period} candles for Bollinger Bands({period})")
    close = _to_frame(candles)["close"]
    mid = close.rolling(window=period, min_periods=period).mean().iloc[-1]
    sigma = close.rolling(window=period, min_periods=period).std(ddof=0).iloc[-1]
    if pd.isna(mid) or pd.isna(sigma):
        raise ValueError("Could not calculate Bollinger Bands")
    upper = mid + stddev * sigma
    lower = mid - stddev * sigma
    return float(mid), float(upper), float(lower)


def calculate_indicators(candles: list[Candle]) -> IndicatorSnapshot:
    atr = calculate_atr(candles, period=14)
    mid, upper, lower = calculate_bollinger(candles, period=20, stddev=2.0)
    return IndicatorSnapshot(
        atr14=atr,
        bollinger_mid=mid,
        bollinger_upper=upper,
        bollinger_lower=lower,
    )


def _to_frame(candles: list[Candle]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "high": [candle.high for candle in candles],
            "low": [candle.low for candle in candles],
            "close": [candle.close for candle in candles],
        }
    )
