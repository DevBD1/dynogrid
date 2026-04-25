from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml

from dynogrid.models import BotConfig


def load_config(path: str | Path) -> BotConfig:
    raw = yaml.safe_load(Path(path).read_text()) or {}
    return parse_config(raw)


def parse_config(raw: dict[str, Any]) -> BotConfig:
    required = {
        "symbol",
        "timeframe",
        "grid_count",
        "atr_multiplier",
        "order_size",
        "max_inventory",
        "maker_fee_rate",
        "starting_base",
        "starting_quote",
        "db_path",
    }
    missing = sorted(required.difference(raw))
    if missing:
        raise ValueError(f"Missing config keys: {', '.join(missing)}")

    config = BotConfig(
        symbol=str(raw["symbol"]),
        timeframe=str(raw["timeframe"]),
        strategy_timeframe=str(raw.get("strategy_timeframe", raw["timeframe"])),
        grid_count=int(raw["grid_count"]),
        atr_multiplier=float(raw["atr_multiplier"]),
        order_size=float(raw["order_size"]),
        max_inventory=float(raw["max_inventory"]),
        maker_fee_rate=float(raw["maker_fee_rate"]),
        starting_base=float(raw["starting_base"]),
        starting_quote=float(raw["starting_quote"]),
        db_path=str(raw["db_path"]),
        exchange_id=str(raw.get("exchange_id", "binance")),
        price_precision=int(raw.get("price_precision", 2)),
        quantity_precision=int(raw.get("quantity_precision", 6)),
        min_price=float(raw.get("min_price", 0.0)),
        min_quantity=float(raw.get("min_quantity", 0.0)),
        stop_loss_pct=float(raw.get("stop_loss_pct", 0.10)),
        loop_interval_seconds=int(raw.get("loop_interval_seconds", 60)),
        recenter_hysteresis_pct=float(raw.get("recenter_hysteresis_pct", 0.001)),
        atr_fast_period=int(raw.get("atr_fast_period", 7)),
        atr_slow_period=int(raw.get("atr_slow_period", 28)),
        taker_fee_rate=float(raw.get("taker_fee_rate", raw.get("maker_fee_rate", 0.001))),
        simulated_slippage_bps=float(raw.get("simulated_slippage_bps", 1.0)),
        ev_safety_multiplier=float(raw.get("ev_safety_multiplier", 1.10)),
        max_ev_spacing_pct=float(raw.get("max_ev_spacing_pct", 0.02)),
        bias_mode=str(raw.get("bias_mode", "auto")),
        ema_fast_period=int(raw.get("ema_fast_period", 9)),
        ema_slow_period=int(raw.get("ema_slow_period", 21)),
        outside_band_consecutive=int(raw.get("outside_band_consecutive", 3)),
        structure_lookback=int(raw.get("structure_lookback", 20)),
        structure_break_atr_buffer=float(raw.get("structure_break_atr_buffer", 0.25)),
        inventory_spacing_threshold=float(raw.get("inventory_spacing_threshold", 0.70)),
        inventory_spacing_max_multiplier=float(raw.get("inventory_spacing_max_multiplier", 1.0)),
        spacing_hysteresis_pct=float(raw.get("spacing_hysteresis_pct", 0.01)),
    )
    validate_config(config)
    return config


def validate_config(config: BotConfig) -> None:
    if config.timeframe != "1m":
        raise ValueError("V1 ingestion only supports timeframe=1m")
    if config.strategy_timeframe not in {"1m", "5m"}:
        raise ValueError("strategy_timeframe must be 1m or 5m")
    if config.grid_count < 1:
        raise ValueError("grid_count must be >= 1")
    if config.atr_multiplier <= 0:
        raise ValueError("atr_multiplier must be > 0")
    if config.order_size <= 0:
        raise ValueError("order_size must be > 0")
    if config.max_inventory < 0:
        raise ValueError("max_inventory must be >= 0")
    if config.maker_fee_rate < 0:
        raise ValueError("maker_fee_rate must be >= 0")
    if config.starting_base < 0 or config.starting_quote < 0:
        raise ValueError("starting balances must be >= 0")
    if not 0 < config.stop_loss_pct < 1:
        raise ValueError("stop_loss_pct must be between 0 and 1")
    if config.price_precision < 0 or config.quantity_precision < 0:
        raise ValueError("precision values must be >= 0")
    if config.recenter_hysteresis_pct < 0:
        raise ValueError("recenter_hysteresis_pct must be >= 0")
    if config.atr_fast_period < 1 or config.atr_slow_period < 1:
        raise ValueError("ATR periods must be >= 1")
    if config.taker_fee_rate < 0:
        raise ValueError("taker_fee_rate must be >= 0")
    if config.simulated_slippage_bps < 0:
        raise ValueError("simulated_slippage_bps must be >= 0")
    if config.ev_safety_multiplier <= 0:
        raise ValueError("ev_safety_multiplier must be > 0")
    if config.max_ev_spacing_pct <= 0:
        raise ValueError("max_ev_spacing_pct must be > 0")
    if config.bias_mode not in {"auto", "mean_reversion", "trend_following"}:
        raise ValueError("bias_mode must be auto, mean_reversion, or trend_following")
    if config.ema_fast_period < 1 or config.ema_slow_period < 1:
        raise ValueError("EMA periods must be >= 1")
    if config.outside_band_consecutive < 1:
        raise ValueError("outside_band_consecutive must be >= 1")
    if config.structure_lookback < 2:
        raise ValueError("structure_lookback must be >= 2")
    if config.structure_break_atr_buffer < 0:
        raise ValueError("structure_break_atr_buffer must be >= 0")
    if not 0 <= config.inventory_spacing_threshold <= 1:
        raise ValueError("inventory_spacing_threshold must be between 0 and 1")
    if config.inventory_spacing_max_multiplier < 0:
        raise ValueError("inventory_spacing_max_multiplier must be >= 0")
    if config.spacing_hysteresis_pct < 0:
        raise ValueError("spacing_hysteresis_pct must be >= 0")


def config_hash(config: BotConfig) -> str:
    payload = json.dumps(asdict(config), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def config_json(config: BotConfig) -> str:
    return json.dumps(asdict(config), sort_keys=True)
