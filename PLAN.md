# DynoGrid Rebuild Plan

## 1. Overview
DynoGrid is being completely rebuilt from the ground up to address fundamental flaws in its original time-based, synchronous, and reactive center-determination logic. 

The new architecture is a fully decoupled, asynchronous, event-driven pipeline specifically designed for perpetual futures (e.g., Hyperliquid). It relies on continuous data streams and statistical volatility (Bollinger Bands) rather than lagging, arbitrary percentage thresholds.

## 2. Core Mathematics (The Fundamentals)
*   **Grid Center:** The Bollinger Band mid-line (SMA). This provides a dynamic, continuously updating equilibrium that smooths out noise naturally.
*   **Grid Spacing:** Derived directly from the Bollinger Band's standard deviation ($\sigma$). The spacing perfectly subdivides the bands: `spacing = (bollinger_upper - bollinger_mid) / grid_count`. This ensures the outermost grid levels rest exactly on the statistical boundaries of the Bollinger Bands.
*   **Inventory Management:** **Global Inventory**. The bot tracks a single consolidated position (average entry price and total size) matching the native behavior of perpetual futures exchanges, rather than tracking individual matched buy/sell pairs.

## 3. Architecture Pipeline (Event-Driven & Async)
The system processes tick/trade data through a strictly unidirectional, agnostic pipeline: `{A1/A2} -> B -> C -> D -> {E1/E2}`.

### Module A: Data Ingestion
*   **A1 (Backtest/Fake):** Feeds historical tick or low-timeframe data for accurate simulation.
*   **A2 (Live Market):** Streams real-time WebSocket tick/trade data from Hyperliquid (Testnet or Livenet).

### Module B: Indicators (Agnostic)
*   Receives price events from Module A.
*   Strictly calculates mathematical indicators on every tick/event: Bollinger Bands (Mid, Upper, Lower), Standard Deviation ($\sigma$), and ATR.
*   Unaffected by execution state or environment.

### Module C: Strategy (Agnostic)
*   Takes indicator data from Module B and calculates the *desired* ideal grid levels.
*   Applies **Tier 1 Risk Defense (Soft Pause):** If the price breaks sharply outside the Bollinger Bands with strong momentum, it temporarily halts the emission of new counter-trend grid entries while keeping take-profit exit levels active.

### Module D: Reconciliation (Agnostic)
*   Acts as the hysteresis/anti-thrashing layer.
*   Compares the *desired* grid levels (from C) against the *currently active* grid levels (previously sent to E).
*   **Rule:** It only emits a grid update to Module E if a specific grid level has shifted by at least `Y * ATR` (where `Y` is a configured multiplier).
*   **No Time Cooldowns:** Relies purely on price/volatility distance to manage exchange rate limits, ensuring critical grid shifts are never skipped due to arbitrary timers.

### Module E: Execution & State Tracking
*   **E1 (Paper):** Simulates order fills based on the incoming data stream for backtesting.
*   **E2 (Live Execution):** Interacts directly with the Hyperliquid API/WS to place, cancel, and track limit orders and global position state.
*   Applies **Tier 2 Risk Defense (Hard Stop):** Continuously monitors the global position's unrealized PnL. If the total account drawdown exceeds a hard-coded percentage limit (e.g., -10%), it aggressively market-flattens the entire position and halts trading to prevent liquidation.

## 4. Next Steps (When Implementation Begins)
1. Set up the foundational async framework and project structure.
2. Build Module B (Indicators) and write unit tests for pure math logic.
3. Build Module C (Strategy) to generate the ideal grid layout.
4. Build Module D (Reconciliation) with the `Y * ATR` distance logic.
5. Build Module A (Data feed interfaces) and Module E (Paper/Live Execution).
6. Connect the pipeline and run end-to-end simulated backtests (A1 -> E1).
