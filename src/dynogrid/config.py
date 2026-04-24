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
    )
    validate_config(config)
    return config


def validate_config(config: BotConfig) -> None:
    if config.timeframe != "1m":
        raise ValueError("V1 only supports timeframe=1m")
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


def config_hash(config: BotConfig) -> str:
    payload = json.dumps(asdict(config), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def config_json(config: BotConfig) -> str:
    return json.dumps(asdict(config), sort_keys=True)
