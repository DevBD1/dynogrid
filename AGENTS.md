# DynoGrid: Agent Guidelines

This document provides instructions for coding agents working on the DynoGrid repository. Follow these rules strictly to maintain system integrity.

## 1. Repository Context & Architecture
- **Purpose**: DynoGrid is an asynchronous, event-driven grid trading bot designed for perpetual futures.
- **Architecture Pipeline**: `{A1/A2} -> B -> C -> D -> {E1/E2}`. A strictly unidirectional, agnostic pipeline separating data ingestion, indicator math, strategy logic, state reconciliation, and execution.
- **Pattern**: Feature-first structure. Separate pure mathematical/strategy logic from execution/exchange API calls.

## 2. Tech Stack
- **Language**: Python 3.11+
- **Concurrency**: `asyncio`
- **Exchange Interface**: Exchange specific SDKs (e.g., Hyperliquid) or CCXT
- **Persistence**: SQLite (for state tracking and historical analysis)

## 3. Coding Standards (Strict)
- **Asyncio**: Use non-blocking calls for all network and I/O operations.
- **Error Handling**: Never swallow exchange errors or network exceptions. Implement appropriate error handling and backoff strategies.
- **Types**: Use strict Python type hints (`typing`) for all function signatures and variables.
- **Naming Conventions**: Use `snake_case` for variables/functions and `PascalCase` for classes.
- **Correctness over Speed**: Trading safety, data integrity, and mathematical correctness are the #1 priorities.
- **Purity**: Core modules (Indicators, Strategy, Reconciliation) must be pure functions/classes, fully agnostic to whether they are running in a backtest or live environment.

## 4. Testing Rules
- **Framework**: `pytest` with `pytest-asyncio`
- **Priority**: Prioritize testing the pure mathematical and state-reconciliation engines (Modules B, C, D) before the execution layer.
- **Mocking**: Use mocks or fakes for all exchange interactions and network I/O during unit tests.
- **Coverage**: Ensure high coverage on edge cases (e.g., extreme volatility, disconnected WebSockets, partial state).

## 5. Workflow
1. Read this `AGENTS.md`, `README.md`, and `PLAN.md` before starting any work.
2. Follow the decoupled architectural pipeline when adding new features or fixing bugs.
3. Validate all inputs and enforce strict type boundaries between modules.
