# DynoGrid: Agent Guidelines

This document provides instructions for coding agents working on the DynoGrid repository. Follow these rules strictly to maintain system integrity and trading safety.

## 1. Tech Stack & Architecture
- **Language**: Python (Asyncio).
- **Exchange Interface**: CCXT.
- **Persistence**: SQLite.
- **Pattern**: Feature-first structure. Separate strategy logic (math) from execution logic (exchange API calls).

## 2. Core Trading Logic
Every minute, the bot must:
1. Fetch latest 1m OHLCV.
2. Calculate ATR(14).
3. Update spacing: \$S = ATR \times k\$.
4. Apply re-centering buffer: Shift center \$P_{center}\$ only if \$|P_{current} - P_{center}| > 0.5 \times ATR\$.

## 3. Risk Management Rules
- **Inventory Delta**: Never exceed \`MAX_INVENTORY\`. If Delta is too high, disable Buy orders.
- **Fee Barrier**: Enforce \$S > 2.5 \times \text{Exchange Fee}\$.
- **Post-Only**: All limit orders MUST be "Post-Only" (Maker) to ensure lower fees and predictable execution.
- **Global Stop Loss**: Exit all positions if total account value drops >10%.

## 4. Coding Standards (Strict)
- **Asyncio**: Use non-blocking calls for all network and I/O operations.
- **Error Handling**: Never swallow \`ccxt\` errors. Implement exponential backoff for rate limits.
- **Types**: Use Python type hints (\`typing\`) for all function signatures.
- **Testing**: Prioritize testing the "Grid Calculation Engine" (pure functions) before the execution layer.
- **Correctness over Speed**: Trading safety is the #1 priority.

## 5. Workflow
1. Read this \`AGENTS.md\` and \`README.md\`.
2. Ensure you understand the current Inventory Delta before placing any order.
3. Validate order price and quantity against exchange filters (precision) before calling \`create_order\`.
