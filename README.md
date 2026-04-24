# DynoGrid

DynoGrid is a dynamic grid algorithmic trading bot designed to profit from Bitcoin's volatility using adaptive price levels. Unlike traditional static grid bots, DynoGrid recalculates its grid parameters every minute based on real-time market volatility and trend indicators.

## Core Strategy

### 1-Minute Heartbeat
The bot operates on a strict 1-minute cycle:
1.  **Ingestion**: Fetch 1m OHLCV data.
2.  **Analysis**: Calculate ATR (14) and Bollinger Bands (20, 2).
3.  **Adaptive Spacing**: Set grid width as a multiple of ATR (\$S = ATR \times k\$).
4.  **EV Gate**: Widen or pause if round-trip expected value cannot cover fees and simulated slippage.
5.  **Trend Filter**: Adjust grid bias with Bollinger Bands plus EMA momentum confirmation.
6.  **Re-centering**: Shift the grid center only if both ATR and percent hysteresis gates pass.
7.  **Sync**: Update exchange limit orders to match the new grid.

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

Run live paper trading with a live terminal dashboard. Leave `--cycles` out to
keep it running until you press `Ctrl+C`:

```bash
dynogrid --config config.yaml run-live-paper --watch
dynogrid --config config.yaml run-live-paper --watch --refresh 2
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
dynogrid --config config.yaml performance --run-id 4
dynogrid --config config.yaml orders
dynogrid --config config.yaml orders --run-id 4 --status all
dynogrid --config config.yaml fills --run-id 4 --limit 20
dynogrid --config config.yaml pause
dynogrid --config config.yaml resume
dynogrid --config config.yaml flatten
```

Use `--json` before the command when you want machine-readable output:

```bash
dynogrid --json --config config.yaml status
dynogrid --json --config config.yaml performance --run-id 4
dynogrid --json --config config.yaml orders --run-id 4
dynogrid --json --config config.yaml fills --run-id 4
```

### Experiment Knobs

Tune experiments in `config.yaml`:

```yaml
grid_count: 3
atr_multiplier: 1.2
order_size: 0.001
recenter_hysteresis_pct: 0.001
atr_fast_period: 7
atr_slow_period: 28
taker_fee_rate: 0.001
simulated_slippage_bps: 1.0
ev_safety_multiplier: 1.10
max_ev_spacing_pct: 0.02
bias_mode: auto
ema_fast_period: 9
ema_slow_period: 21
outside_band_consecutive: 3
inventory_spacing_threshold: 0.70
```

Then run the bot and compare results:

```bash
dynogrid --config config.yaml config-check
dynogrid --config config.yaml run-live-paper --cycles 5
dynogrid --config config.yaml performance --run-id RUN_ID
dynogrid --config config.yaml orders --run-id RUN_ID --status all
dynogrid --config config.yaml fills --run-id RUN_ID
```

All commands:

```bash
dynogrid --config config.yaml config-check
dynogrid --config config.yaml run-live-paper [--cycles N] [--watch] [--refresh seconds]
dynogrid --config config.yaml backtest --candles tests/fixtures/candles.csv [--cycles N]
dynogrid --config config.yaml run-paper --candles tests/fixtures/candles.csv [--cycles N] [--sleep]
dynogrid --config config.yaml status
dynogrid --config config.yaml performance --run-id RUN_ID
dynogrid --config config.yaml orders [--run-id RUN_ID] [--status open|filled|canceled|all]
dynogrid --config config.yaml fills [--run-id RUN_ID] [--limit N]
dynogrid --config config.yaml pause
dynogrid --config config.yaml resume
dynogrid --config config.yaml flatten
dynogrid --config config.yaml run-live
```

SQLite remains the operational source of truth. You can browse `dynogrid.sqlite3`
directly to inspect `runs`, `candles`, `strategy_snapshots`, `orders`, `fills`,
`balances`, `events`, `strategy_metrics`, and `config_versions`.

Research sweeps can be run from code or the notebook:

```python
from dynogrid.config import load_config
from dynogrid.research.vector_backtest import run_parameter_sweep

config = load_config("config.yaml")
results = run_parameter_sweep(
    "tests/fixtures/candles.csv",
    config,
    grid_counts=[2, 3],
    atr_multipliers=[1.0, 1.2],
    order_sizes=[0.001],
    atr_periods=[14, 28],
    ema_fast_periods=[9],
    ema_slow_periods=[21],
    bb_windows=[20],
)
```

`run-live` is a future live-trading command stub. It exits with a safety error
until live exchange order placement has precision checks, post-only enforcement,
exchange sync, CCXT backoff, and global stop-loss auto-flatten.

### Tests

```bash
pytest -q
```

## Risk Warning
Trading cryptocurrencies involves significant risk. This bot is provided for educational and research purposes. Never trade more than you can afford to lose.
