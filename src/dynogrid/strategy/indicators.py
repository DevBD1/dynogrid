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


def calculate_ema(candles: list[Candle], period: int) -> float:
    if len(candles) < 1:
        raise ValueError("Need at least 1 candle for EMA")
    close = _to_frame(candles)["close"]
    effective_period = min(period, len(candles))
    ema = close.ewm(span=effective_period, adjust=False).mean().iloc[-1]
    if pd.isna(ema):
        raise ValueError(f"Could not calculate EMA({period})")
    return float(ema)


def calculate_consecutive_band_closes(
    candles: list[Candle], period: int = 20, stddev: float = 2.0
) -> tuple[int, int]:
    if len(candles) < period:
        raise ValueError(f"Need at least {period} candles for Bollinger close counts")
    close = _to_frame(candles)["close"]
    mid = close.rolling(window=period, min_periods=period).mean()
    sigma = close.rolling(window=period, min_periods=period).std(ddof=0)
    upper = mid + stddev * sigma
    lower = mid - stddev * sigma
    above = 0
    below = 0
    for price, upper_value, lower_value in zip(
        reversed(close.tolist()), reversed(upper.tolist()), reversed(lower.tolist())
    ):
        if pd.isna(upper_value) or pd.isna(lower_value):
            break
        if price > upper_value:
            above += 1
            if below == 0:
                continue
        elif price < lower_value:
            below += 1
            if above == 0:
                continue
        break
    return above, below


def calculate_indicators(
    candles: list[Candle],
    atr_fast_period: int = 7,
    atr_slow_period: int = 28,
    ema_fast_period: int = 9,
    ema_slow_period: int = 21,
) -> IndicatorSnapshot:
    atr = calculate_atr(candles, period=14)
    atr_fast = calculate_atr(candles, period=min(atr_fast_period, len(candles) - 1))
    atr_slow = calculate_atr(candles, period=min(atr_slow_period, len(candles) - 1))
    mid, upper, lower = calculate_bollinger(candles, period=20, stddev=2.0)
    ema_fast = calculate_ema(candles, ema_fast_period)
    ema_slow = calculate_ema(candles, ema_slow_period)
    above, below = calculate_consecutive_band_closes(candles, period=20, stddev=2.0)
    return IndicatorSnapshot(
        atr14=atr,
        bollinger_mid=mid,
        bollinger_upper=upper,
        bollinger_lower=lower,
        atr_fast=atr_fast,
        atr_slow=atr_slow,
        ema_fast=ema_fast,
        ema_slow=ema_slow,
        closes_above_upper=above,
        closes_below_lower=below,
    )


def _to_frame(candles: list[Candle]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "high": [candle.high for candle in candles],
            "low": [candle.low for candle in candles],
            "close": [candle.close for candle in candles],
        }
    )
