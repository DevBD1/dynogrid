# DynoGrid

DynoGrid is a dynamic grid algorithmic trading bot designed to profit from Bitcoin's volatility using adaptive price levels. Unlike traditional static grid bots, DynoGrid recalculates its grid parameters every minute based on real-time market volatility and trend indicators.

## Core Strategy

### 1-Minute Heartbeat
The bot operates on a strict 1-minute cycle:
1.  **Ingestion**: Fetch 1m OHLCV data.
2.  **Analysis**: Calculate ATR (14) and Bollinger Bands (20, 2).
3.  **Adaptive Spacing**: Set grid width as a multiple of ATR (\$S = ATR \times k\$).
4.  **Trend Filter**: Adjust grid bias (Neutral, Long-only, or Short-only) based on Bollinger Band position.
5.  **Re-centering**: Shift the grid center if the price drifts beyond the defined buffer.
6.  **Sync**: Update exchange limit orders to match the new grid.

### Key Features
- **Volatility-Aware**: Automatically widens the grid during spikes to reduce risk and narrows it during consolidation to maximize fill frequency.
- **Inventory Management**: Tracks net exposure (Delta) and automatically tilts the grid to rebalance if positions become too one-sided.
- **Fee Optimization**: Enforces a minimum grid width relative to exchange fees to ensure every completed grid is profitable.

## Tech Stack
- **Language**: Python 3.10+
- **Execution**: `asyncio` for non-blocking I/O.
- **Exchange API**: `ccxt` boundary for future live trading. V1 is paper-first.
- **Indicators**: `pandas`.
- **Database**: `sqlite3` with async access through `aiosqlite`.

## Getting Started

### Installation
Create and activate a local virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install DynoGrid in editable mode:

```bash
python3 -m pip install -e '.[dev]'
```

When you come back later, activate the same environment again before running commands:

```bash
source .venv/bin/activate
```

### Configuration
Copy `config.example.yaml` to your own config file and tune it:

```bash
cp config.example.yaml config.yaml
dynogrid --config config.yaml config-check
```

The V1 implementation is paper-first. Live order placement is intentionally disabled.

### Terminal Workflow

Run live paper trading from Binance 1m candles. This fetches live market data
through CCXT, but all balances, orders, and fills are simulated locally:

```bash
dynogrid --config config.yaml run-live-paper
```

Run live paper trading for a fixed number of newly closed candles:

```bash
dynogrid --config config.yaml run-live-paper --cycles 5
```

Run a historical paper simulation from 1m candles:

```bash
dynogrid --config config.yaml backtest --candles tests/fixtures/candles.csv
```

Limit a backtest to a fixed number of candles:

```bash
dynogrid --config config.yaml backtest --candles tests/fixtures/candles.csv --cycles 25
```

Run the same paper engine with optional sleep between cycles:

```bash
dynogrid --config config.yaml run-paper --candles tests/fixtures/candles.csv --sleep
```

Run paper mode without real-time sleeping, or stop after a fixed number of cycles:

```bash
dynogrid --config config.yaml run-paper --candles tests/fixtures/candles.csv
dynogrid --config config.yaml run-paper --candles tests/fixtures/candles.csv --cycles 25
```

Inspect or control the bot through CLI commands backed by SQLite runtime state:

```bash
dynogrid --config config.yaml config-check
dynogrid --config config.yaml status
dynogrid --config config.yaml pause
dynogrid --config config.yaml resume
dynogrid --config config.yaml flatten
```

All commands:

```bash
dynogrid --config config.yaml config-check
dynogrid --config config.yaml run-live-paper [--cycles N]
dynogrid --config config.yaml backtest --candles tests/fixtures/candles.csv [--cycles N]
dynogrid --config config.yaml run-paper --candles tests/fixtures/candles.csv [--cycles N] [--sleep]
dynogrid --config config.yaml status
dynogrid --config config.yaml pause
dynogrid --config config.yaml resume
dynogrid --config config.yaml flatten
```

SQLite remains the operational source of truth. You can browse `dynogrid.sqlite3`
directly to inspect `runs`, `candles`, `strategy_snapshots`, `orders`, `fills`,
`balances`, `events`, and `config_versions`.

### Tests

```bash
pytest -q
```

## Risk Warning
Trading cryptocurrencies involves significant risk. This bot is provided for educational and research purposes. Never trade more than you can afford to lose.
