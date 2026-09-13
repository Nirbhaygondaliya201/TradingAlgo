# Design Document — XAU/USD MT5 Expert Advisor

## Overview

This document describes the complete technical design for a professional XAU/USD (Gold) algorithmic trading Expert Advisor (EA) deployed on MetaTrader 5 (MT5) through XM broker. The system applies multi-timeframe Smart Money Concepts (SMC) analysis — combining 4H regime detection, 1H major structure, 15M liquidity and setup detection, and 5M entry confirmation — alongside a fully independent risk management engine and professional-grade safety controls.

### Design Principles

1. **Correctness over complexity** — every module does exactly one job and can be verified independently.
2. **No look-ahead bias** — all decisions use only data from bar index ≥ 1; bar index 0 is never read for any strategic decision.
3. **No repainting** — structural values (swings, BOS, CHOCH, pools) are computed on confirmed candles and never retroactively revised.
4. **Fail-closed** — in any error, data-unavailability, or ambiguous state, the system defaults to blocking entries and protecting open positions.
5. **Full independence of risk and execution** — the Risk_Manager has no knowledge of order submission mechanics; the Order_Executor has no knowledge of strategy logic.
6. **Deterministic broker interface** — every broker-specific property (point size, lot step, contract size, stop level, freeze level, margin) is obtained from MT5 Symbol_Properties at runtime. No broker constant is hardcoded.
7. **Observable behaviour** — every decision that affects trading is logged with sufficient context for full post-hoc audit.
8. **Walk-forward validation only** — no random train/test splits on time-series data. The Python research environment enforces this at the data-access layer.

### Scope

The system comprises two separate codebases that share logical design:

- **MQL5 EA** — live execution on MetaTrader 5; primary deliverable.
- **Python Research Environment** — mirrors all strategy and risk module logic for backtesting, walk-forward validation, and sensitivity analysis; not connected to live execution.

---

## Architecture

### High-Level Architecture

The EA is structured as a layered pipeline with strict one-way data flow. No lower layer may call upward into a higher layer.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                          MetaTrader 5 Runtime                                │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │                       Main EA Controller (xauusd_ea.mq5)            │    │
│  │   OnInit / OnTick / OnTimer / OnDeinit event handlers               │    │
│  └──────┬───────────────────────────────────────────────────────────────┘    │
│         │                                                                     │
│  LAYER 1: DATA ACQUISITION                                                   │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │  Symbol_Properties_Reader │ MultiTimeframe_DataFeed                  │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
│         │                                                                     │
│  LAYER 2: ANALYSIS ENGINES (read confirmed candles → produce AnalysisStatus) │
│  ┌───────────────────────┐  ┌────────────────────────┐                       │
│  │ Market_Structure_     │  │  Liquidity_Detector    │                       │
│  │ Analyzer              │  │                        │                       │
│  │  - Swing Detection    │  │  - Pool Detection      │                       │
│  │  - BOS / CHOCH        │  │  - Sweep Detection     │                       │
│  │  - Regime Engine      │  │  - Pool Lifecycle      │                       │
│  └───────────────────────┘  └────────────────────────┘                       │
│  ┌───────────────────────┐  ┌────────────────────────┐                       │
│  │  ATR_Volatility_Engine│  │  Momentum_Engine        │                       │
│  └───────────────────────┘  └────────────────────────┘                       │
│         │ All outputs are AnalysisStatus objects                              │
│  LAYER 3: FILTER LAYER                                                       │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐                 │
│  │ Session_Filter │  │ Spread_Filter  │  │ News_Filter    │                 │
│  └────────────────┘  └────────────────┘  └────────────────┘                 │
│         │ All return AnalysisStatus (ALLOWED / BLOCKED / WARN)               │
│  LAYER 4: ENTRY CONFIRMATION                                                 │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │  Entry_Confirmation_Engine                                           │    │
│  │  Aggregates all AnalysisStatus inputs → produces TradeSignal or NULL │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
│         │ TradeSignal                                                         │
│  LAYER 5: RISK MANAGEMENT                                                    │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │  Risk_Manager                                                        │    │
│  │  Validates signal, sizes position, enforces all drawdown limits      │    │
│  │  → produces TradeOrder or rejection                                  │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
│         │ TradeOrder                                                          │
│  LAYER 6: EXECUTION                                                          │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │  Order_Executor (sole caller of OrderSend / OrderModify / OrderClose)│    │
│  │  Spread_Filter check → submit → verify fill → retry on non-fatal err │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
│                                                                               │
│  CROSS-CUTTING SERVICES (accessible from all layers)                        │
│  ┌──────────────┐  ┌────────────────────┐  ┌────────────────────────────┐   │
│  │   Logger     │  │  State_Manager     │  │  Config_Manager            │   │
│  │  (stateless) │  │  (persistence/     │  │  (validated inputs,        │   │
│  │              │  │   restart/safe mode│  │   Symbol_Properties cache) │   │
│  └──────────────┘  └────────────────────┘  └────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Module Boundary Definitions

Each module maps to exactly one `.mqh` include file and one Python module. Cross-module communication uses only the defined interface objects — no module may call internal functions of another module or share mutable state across module boundaries.

| Module | MQL5 File | Python File | Communication In | Communication Out |
|---|---|---|---|---|
| Market_Structure_Analyzer | MarketStructureAnalyzer.mqh | market_structure.py | OHLCV arrays (confirmed) | AnalysisStatus[] |
| Liquidity_Detector | LiquidityDetector.mqh | liquidity.py | OHLCV arrays, ATR value | AnalysisStatus[] |
| ATR_Volatility_Engine | ATRVolatilityEngine.mqh | atr_engine.py | OHLCV arrays (confirmed) | ATRResult |
| Momentum_Engine | MomentumEngine.mqh | momentum.py | OHLCV arrays (confirmed) | AnalysisStatus |
| Session_Filter | SessionFilter.mqh | session_filter.py | Broker server time | AnalysisStatus (ALLOWED/BLOCKED) |
| Spread_Filter | SpreadFilter.mqh | spread_filter.py | Symbol_Properties, threshold | AnalysisStatus (ALLOWED/BLOCKED) |
| News_Filter | NewsFilter.mqh | news_filter.py | Server time, event list | AnalysisStatus (ALLOWED/BLOCKED/WARN) |
| Entry_Confirmation_Engine | EntryConfirmationEngine.mqh | entry_engine.py | AnalysisStatus[] from all above | TradeSignal or NULL |
| Risk_Manager | RiskManager.mqh | risk_manager.py | TradeSignal, Symbol_Properties, account equity | TradeOrder or RejectionResult |
| Order_Executor | OrderExecutor.mqh | N/A (live only) | TradeOrder | ExecutionResult |
| State_Manager | StateManager.mqh | state_manager.py | Internal EA state | Persisted file, state reads |
| Logger | Logger.mqh | logger.py | Event data from all modules | Log output (Experts log / file) |
| Config_Manager | ConfigManager.mqh | config.py | MQL5 input variables | Validated config struct |
| Symbol_Properties_Reader | SymbolPropertiesReader.mqh | symbol_props.py | MT5 API | SymbolProperties struct |
| MultiTimeframe_DataFeed | MTFDataFeed.mqh | data_feed.py | MT5 CopyRates | OHLCVBars per timeframe |

---

## Components and Interfaces

### 2.1 Symbol_Properties_Reader

**Responsibility:** Retrieve all broker/symbol-specific values from MT5 at runtime. Caches values at initialisation. Provides a single access point for the rest of the EA so that no other module hardcodes broker constants.

**Inputs:** MT5 SymbolInfo API calls for XAUUSD.

**Outputs:** `SymbolProperties` struct (see Data Models).

**Dependencies:** MT5 API only.

**State:** Immutable after successful initialisation. If any property read fails, the EA aborts with INIT_FAILED.

**Failure behavior:** Any property read failure at OnInit causes INIT_FAILED. Post-init, the module exposes a `IsValid()` flag. Other modules check this flag before use; if false they treat the symbol as unavailable and block entries.

**Important edge cases:**
- Broker may return 0 for stop level — this must be treated as 0 (valid), not as an error.
- Contract size and tick value must be validated as > 0 before any position sizing calculation.

**Testing requirements:** Unit test that all five mandatory properties are populated; test that missing any single property triggers INIT_FAILED.

---

### 2.2 MultiTimeframe_DataFeed

**Responsibility:** Provide read-only access to OHLCV data for all four timeframes (4H, 1H, 15M, 5M). Enforces the confirmed-candle rule: exposes a `GetBars(timeframe, count)` function that always returns bars starting at index 1 (never index 0).

**Inputs:** Timeframe identifier, requested bar count.

**Outputs:** `OHLCVBar[]` array; always omits bar[0] (currently forming candle).

**Dependencies:** MT5 `CopyRates` API.

**State:** No internal state — reads live from MT5 on each call.

**Failure behavior:** If fewer bars than requested are available, returns what is available and sets a `BarsAvailable` count. Callers must check this count before proceeding. If zero bars are returned, callers treat the timeframe as UNKNOWN.

**Important edge cases:**
- After terminal start, history for higher timeframes may not yet be synchronised. The module checks `SeriesInfoInteger(symbol, timeframe, SERIES_SYNCHRONIZED)` and returns 0 bars if not yet synchronised.
- No caching — every call to `GetBars` fetches fresh data. This ensures tick-level freshness at the cost of a CopyRates call per module per tick. Acceptable for the tick frequencies involved in XAU/USD.

**Testing requirements:** Unit test that `GetBars` never includes bar[0]; test with unsynchronised series returning 0 bars.

---

### 2.3 Market_Structure_Analyzer

**Responsibility:** Swing detection, BOS identification, CHOCH identification, and 4H regime classification. Operates independently on each timeframe.

**Inputs:** `OHLCVBar[]` arrays from MultiTimeframe_DataFeed (4H, 1H, 15M, 5M). Configuration: `SwingSideCandles` (default 2), `RegimeSwingCount` (default 4), `RangingModeEnabled` (default false).

**Outputs:** `StructureResult` per timeframe containing: confirmed Swing_High list, confirmed Swing_Low list, most recent BOS event (nullable), most recent CHOCH event (nullable), Regime (4H only: Bullish/Bearish/Ranging).

**Dependencies:** MultiTimeframe_DataFeed, Logger.

**State:** Per-timeframe circular buffers holding the last `RegimeSwingCount × 2` confirmed swing points. Buffers are rebuilt on restart from historical data.

**Failure behavior:** If any timeframe has insufficient data (bars < minimum lookback), that timeframe's `StructureResult` has status UNKNOWN. The Entry_Confirmation_Engine treats UNKNOWN as a hard block on new entries.

**Important edge cases:**
- Swing confirmation requires `SwingSideCandles` candles on EACH side. The most recent unconfirmed candidate (within the last `SwingSideCandles` bars) is held pending and never exposed as confirmed.
- Equal highs/lows (to the tick) can appear on both sides of a candle — the rightmost one with the required side candles is taken as the extremum.
- On regime change, the old regime is logged before the new one is applied.

**Testing requirements:**
- Property test: for any OHLCV sequence, no confirmed swing has a timestamp within the last `SwingSideCandles` bars of the last bar in the input.
- Property test: regime classification matches the HH/HL and LH/LL rules for any generated swing sequence.
- Property test: BOS fires at exactly the confirmed-candle close that crosses the prior swing level.
- Edge case test: fewer than minimum bars returns UNKNOWN.

---

### 2.4 Liquidity_Detector

**Responsibility:** Identify Liquidity_Pool zones at clusters of equal highs or lows (within ATR tolerance). Detect Liquidity_Sweep events. Manage pool lifecycle (Active → Swept → Invalidated). Operate on the 15M timeframe.

**Inputs:** `OHLCVBar[]` (15M confirmed candles), `ATRResult` (15M ATR from ATR_Volatility_Engine), configuration: `PoolATRTolerance` (default 0.5×), `MaxActivePools` (default 20).

**Outputs:** `LiquidityStatus` containing: active pools list, latest sweep event (nullable), pool count per side.

**Dependencies:** MultiTimeframe_DataFeed (15M), ATR_Volatility_Engine (15M), Logger.

**State:** Pool registry — a list of `LiquidityPool` objects, each with: price level, tolerance band, status (Active/Swept/Invalidated), creation timestamp, sweep event (nullable). Capped at `MaxActivePools` per direction. Persisted to state file for restart recovery.

**Failure behavior:** If ATR is unavailable, all pool detection is suspended. Existing pools remain but no new pools are created or swept. Entry_Confirmation_Engine is notified via AnalysisStatus with UNKNOWN status.

**Important edge cases:**
- Pool tolerance is computed at pool creation time using the ATR at that moment. ATR changes do not retroactively resize existing pools.
- A pool already marked Swept must not be reactivated unless a new distinct pool forms within tolerance (not the same pool object).
- When `MaxActivePools` is reached, the oldest pool (by creation timestamp) is discarded regardless of direction.
- Never read bar[0] for sweep confirmation.

**Testing requirements:**
- Property test: for any price series with planted equal-high clusters, pools are detected within tolerance.
- Property test: pool status transitions are valid (Active→Swept, Active→Invalidated only).
- Property test: swept pool generates no further sweep events for the same pool object.
- Property test: pool count never exceeds `MaxActivePools`.

---

### 2.5 ATR_Volatility_Engine

**Responsibility:** Compute ATR on the 1H timeframe for volatility filtering and SL distance calculation. Compute the 30-day baseline ATR from the 720 most recent closed 1H candles.

**Inputs:** `OHLCVBar[]` (1H confirmed candles), configuration: `ATRPeriod` (default 14), `BaselineWindow` (720 bars), `ATRMinMultiplier` (default 0.5), `ATRMaxMultiplier` (default 2.5), `ATRSLMultiplier` (default 1.5).

**Outputs:** `ATRResult` struct: current ATR value, baseline ATR value, filter status (ALLOW/BLOCK_LOW/BLOCK_HIGH/UNAVAILABLE), minimum SL distance in price units.

**Dependencies:** MultiTimeframe_DataFeed (1H), Symbol_Properties_Reader (for stop level), Logger.

**State:** Rolling baseline buffer (720 values). No other mutable state.

**Failure behavior:** If fewer than `ATRPeriod` candles are available, `ATRResult.status = UNAVAILABLE`. If fewer than 720 candles for baseline, log warning and use available history (minimum 14). Entry_Confirmation_Engine blocks new entries on UNAVAILABLE.

**Important edge cases:**
- All calculations use only bar index ≥ 1.
- The minimum SL distance is `max(ATR × ATRSLMultiplier, BrokerStopLevel in price units)`.
- ATR = 0 or negative is treated as UNAVAILABLE and logged as an error.

**Testing requirements:**
- Property test: for any ATR value and thresholds, filter returns the correct status.
- Property test: SL distance ≥ max(ATR × multiplier, broker stop level) for all inputs.

---

### 2.6 Momentum_Engine

**Responsibility:** Compute 5M momentum confirmation. Determines whether the most recently closed 5M candle's close falls in the appropriate half of the prior N-candle high-low range for the proposed trade direction.

**Inputs:** `OHLCVBar[]` (5M confirmed candles), configuration: `MomentumLookback` (default 10), proposed direction (Long/Short).

**Outputs:** `MomentumResult`: CONFIRMED / REJECTED / INSUFFICIENT_DATA, computed range value, close position percentage.

**Dependencies:** MultiTimeframe_DataFeed (5M), Logger.

**State:** None (stateless per call).

**Failure behavior:** Fewer than N candles or zero high-low range → INSUFFICIENT_DATA with logged reason.

**Important edge cases:**
- Range = 0 (flat market) must return INSUFFICIENT_DATA, not divide-by-zero.
- The close used is bar[1] (most recently closed 5M candle). Bar[0] is never read.

**Testing requirements:**
- Property test: long approved iff close ≥ range_midpoint; short approved iff close ≤ range_midpoint, for any generated candle sequence.
- Edge case: zero range → INSUFFICIENT_DATA.

---

### 2.7 Session_Filter

**Responsibility:** Return ALLOWED or BLOCKED based on whether the current broker server time falls within any enabled, configured trading session window.

**Inputs:** Broker server time (from MT5 `TimeCurrent()`), configuration: session start/end UTC times for London, New York, London-NY Overlap; enable flags per session; DST offsets per session.

**Outputs:** `FilterStatus` (ALLOWED / BLOCKED).

**Dependencies:** MT5 `TimeCurrent()`, Logger.

**State:** None (stateless per call).

**Failure behavior:** Server time unavailable → BLOCKED + log error. All sessions disabled → BLOCKED + log config warning. Invalid session times (start ≥ end) → that session treated as BLOCKED, log config error.

**Important edge cases:**
- DST transitions must not cause a session to momentarily go invalid. UTC offset is added to the session window boundaries, not to the server time.
- Overlap session is a sub-window of London and NY — it may be enabled independently or as part of either parent session.

**Testing requirements:**
- Property test: for any timestamp, ALLOWED iff it falls within at least one enabled session window.
- Edge case tests: unavailable time, all disabled, invalid window.

---

### 2.8 Spread_Filter

**Responsibility:** At order submission time only, check the current ask-bid spread against the configured maximum. Return BLOCKED if exceeded.

**Inputs:** Live `SymbolInfoDouble(symbol, SYMBOL_ASK)` and `SymbolInfoDouble(symbol, SYMBOL_BID)`, configuration: `MaxSpreadPoints` (default 30), Symbol_Properties for point value.

**Outputs:** `FilterStatus` (ALLOWED / BLOCKED).

**Dependencies:** MT5 SymbolInfo API, Symbol_Properties_Reader, Logger.

**State:** None. No caching. Every call reads fresh.

**Failure behavior:** SymbolInfo unavailable → BLOCKED + log error.

**Important edge cases:**
- Applied only at new order submission, not at modification or closure.
- Spread must be computed as `(Ask - Bid) / Point` and compared against `MaxSpreadPoints`.

**Testing requirements:**
- Property test: BLOCKED iff spread > threshold, for any generated spread/threshold pair.
- Property test: consecutive calls with different spreads return independent results (no caching).

---

### 2.9 News_Filter

**Responsibility:** Block new entries during configurable pre- and post-event windows around high-impact economic events.

**Inputs:** Broker server time, economic event list (loaded from local file or external feed), configuration: `MinImpactLevel` (default High), `PreEventMinutes` (default 30), `PostEventMinutes` (default 15), `NewsProtectionMode` (BLOCK/WARN/DISABLED), `MaxListAgeHours` (default 24), `StaleFallback` (BLOCK/ALLOW, default BLOCK).

**Outputs:** `FilterStatus` (ALLOWED / BLOCKED / WARN).

**Dependencies:** File I/O or HTTP, Logger.

**State:** Cached event list. Stale-after timestamp. Reload trigger (configurable interval or on-demand).

**Failure behavior:** List unloadable or stale → log warning → apply `StaleFallback`. DISABLED mode → always returns ALLOWED.

**Important edge cases:**
- Pre and post windows may overlap if two events are close together — the union of all blocking windows applies.
- Events in the past (beyond `PostEventMinutes`) are cleaned from the active list to prevent unbounded growth.

**Testing requirements:**
- Property test: for any timestamp and event list, BLOCKED iff timestamp falls within at least one blocking window at or above min impact.
- Example test: WARN mode returns WARN (not BLOCKED) with an event in the window.
- Edge case: stale list applies fallback.

---

### 2.10 Entry_Confirmation_Engine

**Responsibility:** Aggregate all AnalysisStatus inputs from analysis engines and filters. Apply all blocking rules. If all conditions pass, generate a TradeSignal and pass it to the Risk_Manager. This module contains no position sizing or order submission logic.

**Inputs:** AnalysisStatus from: Market_Structure_Analyzer (4H regime, 1H BOS/CHOCH, 15M liquidity sweep), Momentum_Engine (5M), ATR_Volatility_Engine (1H filter), Session_Filter, News_Filter. Config: entry-specific parameters.

**Outputs:** `TradeSignal` (or null on block/rejection), logged rejection reason.

**Dependencies:** All analysis and filter modules, Risk_Manager (for TradeSignal pass-through only — no back-calls), Logger.

**State:** None beyond the current analysis snapshot.

**Failure behavior:** Any UNKNOWN or BLOCKED status from any dependency → signal blocked. All blocks are logged with the specific source.

**Entry logic (all conditions must be simultaneously satisfied):**
1. 4H Regime is not Ranging (unless `RangingModeEnabled` = true).
2. 1H has a recent BOS in the direction of the Regime.
3. 15M has an Active Liquidity_Sweep in the direction of the Regime.
4. 5M momentum confirmed in the trade direction.
5. ATR_Volatility_Engine returns ALLOW.
6. Session_Filter returns ALLOWED.
7. News_Filter returns ALLOWED or WARN (configurable whether WARN blocks or not).
8. No daily drawdown block (communicated from Risk_Manager state).
9. No cooldown block (communicated from State_Manager).
10. Free margin above threshold (communicated from Risk_Manager).

**TradeSignal construction (BLOCKER-1 and BLOCKER-2 RESOLVED):**
- **signal_reference_price**: The close price of the confirming candle (bar index 1 on the 5M timeframe). Used for audit and logging only.
- **entry_price**: The live executable Ask (BUY) or Bid (SELL) price read from `SymbolInfoDouble` at the moment of signal generation. This is the price field passed to `OrderSend`. It is re-read again immediately before each `OrderSend` call; the Order_Executor always uses the freshest price.
- **stop_loss_price**: Placed below the sweep's low (BUY) or above the sweep's high (SELL), validated against the ATR minimum SL distance floor. The SL is **static** — it is set once and never modified for the life of the position.
- **take_profit_price**: **Determined by the nearest Active opposing Liquidity_Pool that satisfies the minimum R:R requirement.** Selection algorithm:
  1. Collect all Active Liquidity_Pools on the opposing side (above entry for BUY, below entry for SELL).
  2. Filter to those where `|pool_price_level − entry_price| ≥ MinRR × |entry_price − stop_loss_price|`.
  3. From the filtered set, select the pool with the smallest distance to entry_price (the nearest qualifying pool).
  4. If the filtered set is empty, reject the signal with reason `NO_VALID_TP` and log the closest unqualified pool distance, minimum required distance, and R:R shortfall.
  5. BOS/CHOCH levels are NOT considered as TP candidates.
- **Direction**: Aligned with Regime and 1H BOS direction.
- **computed_rr**: `|take_profit_price − entry_price| / |entry_price − stop_loss_price|` at signal generation time (for audit).

**Important edge cases:**
- All required TradeSignal fields must be non-zero. Any zero field → discard + log invalid field name.
- Signal timestamp is the broker server time at the moment of generation.
- The engine does not hold signals between ticks. A signal generated on tick N is either acted on (passed to Risk_Manager) or discarded on that same tick.
- NO_VALID_TP: If no opposing Active pool satisfies MinRR, the signal is discarded — the trade is not taken. This is logged at INFO level with the shortfall details. The EA does not force a trade by lowering R:R expectations.

**Testing requirements:**
- Property test: signal blocked for any Ranging regime input (unless Ranging_Mode_Enabled).
- Property test: TradeSignal always has all fields populated when approved.
- Property test: no signal generated when any filter returns BLOCKED.

---

### 2.11 Risk_Manager

**Responsibility:** Validate a TradeSignal, calculate position size using floating equity and the fixed-risk formula, enforce all hard limits, and produce a TradeOrder or a rejection with the specific unmet criterion identified. Fully independent of strategy logic.

**Inputs:** `TradeSignal`, Symbol_Properties, account equity (floating), open position list (for combined risk check), configuration: `RiskPerTradePct`, `MaxLotSize`, `MaxOpenTrades`, `DailyMaxDrawdownPct`, `TotalMaxDrawdownPct`, `MinRR`, `MaxConsecutiveLosses`, `CooldownHours`, `MinFreeMarginPct`.

**Outputs:** `TradeOrder` (on approval) or `RejectionResult` (with `UnmetCriterion` field).

**Dependencies:** Symbol_Properties_Reader, State_Manager (for drawdown state, consecutive loss count, cooldown state), Logger.

**State:** None (stateless computation). All persistent state (drawdown accumulators, consecutive loss count) is owned by State_Manager and read by Risk_Manager on each call.

**Position sizing formula:**
```
RiskAmount = FloatingEquity × (RiskPerTradePct / 100)
SLDistancePips = |EntryPrice - StopLossPrice| / SymbolPoint
PipValue = (SymbolPoint × ContractSize) / EntryPrice   [for XAUUSD quoted in USD]
LotSize = RiskAmount / (SLDistancePips × PipValue × ContractSize)
LotSize = RoundDown(LotSize / LotStep) × LotStep
LotSize = Clamp(LotSize, MinLot, MaxLotSize)
```

**Validation sequence (in order, first failure causes rejection):**
1. TradeSignal field validation (non-zero entry, SL, TP, valid direction).
2. R:R check: `(TP - Entry) / (Entry - SL) ≥ MinRR` (long); inverse for short.
3. Daily drawdown limit not reached.
4. Total drawdown circuit breaker not triggered.
5. Max open trades not exceeded.
6. Combined risk of open positions + new trade ≤ `RiskPerTradePct × MaxOpenTrades`.
7. Free margin ≥ `MinFreeMarginPct × RequiredMargin`.
8. Calculated lot size after rounding > 0.

**Prohibited patterns (enforced):**
- No martingale: position size is computed from the formula only; prior trade results are not inputs.
- No grid: the module has no concept of a price ladder; each signal is evaluated in isolation.
- No averaging down: criterion 6 above limits combined exposure regardless of direction of unrealised P&L.

**Failure behavior:** Any validation failure → RejectionResult with the specific criterion name. No TradeOrder is created. All rejections are logged at INFO level with the rejection reason.

**Important edge cases:**
- `LotSize` after rounding = 0 → explicit rejection with pre-rounding value logged.
- `EntryPrice = StopLossPrice` → SL distance is zero → rejection (division by zero prevented).
- Floating equity exactly at circuit breaker threshold → breaker fires (≥ comparison, not >).

**Testing requirements:**
- Property test: for any equity/entry/SL/risk tuple, computed lot size matches formula.
- Property test: lot size always ≤ MaxLotSize and ≥ MinLot (or zero-size rejection fires).
- Property test: lot size is always a valid multiple of LotStep.
- Property test: R:R check rejects iff computed R:R < MinRR.
- Property test: daily and total drawdown blocks fire at the configured threshold.
- Property test: combined risk check enforces the combined exposure limit.

---

### 2.12 Order_Executor

**Responsibility:** The sole module that submits, modifies, and closes orders via MT5 trade API. Validates every order before submission and every fill after execution. Handles non-fatal retries. Manages all open EA positions (SL/TP monitoring on every tick).

**Inputs:** `TradeOrder` from Risk_Manager. MT5 tick events. Configuration: `MaxRetries` (default 3), `RetryDelayMs` (default 500), `SlippagePips` (max acceptable slippage in points), `MagicNumber`.

**Outputs:** `ExecutionResult` (FILLED / REJECTED / FAILED), logged order audit trail. Upward signals to State_Manager for position state updates.

**Dependencies:** MT5 OrderSend/OrderModify/OrderClose APIs, Spread_Filter, Symbol_Properties_Reader, State_Manager (to update position records), Logger.

**State:** Active position list (list of open trades identified by ticket number and Magic_Number). Rebuilt on restart from MT5 order book.

**Submission flow:**
1. Run Spread_Filter — BLOCKED → cancel + log, do not retry.
2. Validate SL distance ≥ broker stop level.
3. Validate all TradeOrder fields non-zero.
4. Submit via `OrderSend`.
5. On success: verify filled SL and TP match submitted values within broker stop level tolerance.
6. If SL/TP mismatch: attempt one correction via `OrderModify`.
7. If correction fails: log CRITICAL, halt management for that ticket.
8. On non-fatal error: wait `RetryDelayMs`, retry up to `MaxRetries`.
9. On fatal error: log with full order details, do not retry.
10. Update State_Manager with new position record.

**SL/TP monitoring (every tick / timer):**
- For every open position with EA's Magic_Number:
  - Verify SL is present and matches expected value.
  - If SL missing: attempt re-attachment via `OrderModify`.
  - If re-attachment fails: close position immediately via `OrderClose`, log CRITICAL.

**Failure behavior:** Order submission failure after all retries → no position opened, full details logged. SL re-attachment failure → position closed immediately.

**Important edge cases:**
- Freeze level: if a position is within `SYMBOL_TRADE_FREEZE_LEVEL` of current price, the Order_Executor SHALL NOT attempt the modification. It SHALL write a structured WARN log entry containing: symbol, ticket/position identifier, operation attempted (e.g., "SL_REATTACH", "SL_MODIFY", "TP_MODIFY"), current relevant price, freeze-level value in points, required distance, reason "FREEZE_LEVEL_ACTIVE", and UTC timestamp. The freeze skip is not an error — it is a normal broker condition. If the skipped operation involves a missing mandatory SL, the re-attachment is deferred to the next monitoring cycle. If the position remains missing its SL after `MaxFreezeSkips` (default 5) consecutive freeze-level skips, the position is force-closed per Requirement 17.5 and a CRITICAL is logged.
- Partial fills: the EA does not use market depth orders, but if a partial fill occurs, the unfilled portion must be handled (cancel remaining, log partial fill).
- Requote: treated as non-fatal, retried up to `MaxRetries`.

**Testing requirements:**
- Property test: every submitted TradeOrder produces a log record with all required fields.
- Property test: SL and TP are always present on submitted orders.
- Example test: non-fatal error retry sequence exhausts retries then cancels.
- Example test: SL missing on open position triggers re-attach attempt.

---

### 2.13 State_Manager

**Responsibility:** Persist and restore all EA state that must survive terminal restarts and connection drops. Manage safe monitoring mode. Provide drawdown accumulators, consecutive loss counter, cooldown state, and day-open equity reference to consuming modules.

**Inputs:** Events from Order_Executor (position opened/closed/modified), daily midnight tick, connection status events. Configuration: `StateFilePath`.

**Outputs:** Persisted state file. State reads for Risk_Manager, Order_Executor, Entry_Confirmation_Engine.

**Dependencies:** File I/O, Logger, MT5 account info API.

**State file format (BLOCKER-4 RESOLVED — native MQL5 key-value with CRC32 checksum):**

The state file is a plain-text UTF-8 file, one `KEY=VALUE` pair per line. No external JSON library is required. Example:

```
VERSION=1
SCHEMA=1
TIMESTAMP_UTC=2026-09-09T07:30:00Z
SYMBOL=XAUUSD
ACCOUNT_SUFFIX=1234
DAILY_DRAWDOWN_PCT=2.14
DAILY_OPEN_EQUITY=10000.00
TOTAL_DRAWDOWN_REF_EQUITY=10000.00
CONSECUTIVE_LOSSES=1
COOLDOWN_START_UTC=0
CIRCUIT_BREAKER_TRIGGERED=0
SAFE_MODE_ACTIVE=0
[POOL_REGISTRY]
0,2950.50,12.30,ACTIVE,ABOVE,2026-09-09T06:00:00Z,0
1,2920.10,11.80,SWEPT,BELOW,2026-09-09T04:00:00Z,2026-09-09T06:45:00Z
[END_POOL_REGISTRY]
CHECKSUM=A3F29C1D
```

**Field rules:**
- `VERSION`: integer — EA binary version that wrote the file
- `SCHEMA`: integer — state file schema version; used for migration logic
- `TIMESTAMP_UTC`: ISO 8601 UTC datetime of last write
- `SYMBOL`: symbol name (must match running EA's symbol)
- `ACCOUNT_SUFFIX`: last 4 digits of account number (must match running EA's account)
- `COOLDOWN_START_UTC`: ISO 8601 datetime or `0` if no cooldown active
- `[POOL_REGISTRY]` section: CSV rows, one pool per line; fields as in `LiquidityPool` struct
- `CHECKSUM`: CRC32 hex string computed over all lines from `VERSION=` up to (not including) `CHECKSUM=`

**Integrity validation (on every file read):**
1. Compute CRC32 of all lines above the CHECKSUM line.
2. Compare to stored CHECKSUM value.
3. If mismatch, missing fields, or unparseable values → enter **SAFE_MODE**.

**SAFE_MODE behaviour:**
- Block all new entry signals.
- Log CRITICAL alert with specific validation failure reason.
- Write `safe_mode=1` sentinel to a separate `xauusd_ea_safemode.flag` file.
- Continue monitoring open positions.
- Require manual deletion of `.flag` file to exit SAFE_MODE.

**Persistence protocol:** File is written atomically (write to `.tmp` file, then rename to final path) immediately after every update to any value. If rename fails, log ERROR and retain the previous state file. At initialisation, check for a `.tmp` file first (indicates interrupted prior write) and attempt to validate it before the main file.

**Restart recovery sequence (OnInit) — CONFLICT-1 RESOLVED:**
1. Check for `.tmp` file → if present and passes CRC32 validation, use it as the primary read source.
2. Read state file → validate schema version, symbol, account suffix, and CRC32 checksum.
3. If any validation fails (missing file where continuity is required, corrupt checksum, symbol/account mismatch, unsupported schema version) → enter SAFE_MODE immediately:
   a. Block all new trade entries.
   b. Log a CRITICAL alert identifying the specific failure.
   c. Persist `SAFE_MODE=1` to sentinel file `xauusd_ea_safemode.flag`.
   d. Proceed to steps 6–7 to reconcile positions from the live MT5 order book.
   e. Do NOT silently reset drawdown accumulators and continue trading.
4. If `circuit_breaker_triggered = true` in a valid state file → EA returns INIT_FAILED (requires manual intervention).
5. If `safe_mode_active = true` in a valid state file → EA enters SAFE_MODE immediately per step 3.
6. Scan MT5 order book for open positions with Magic_Number → rebuild active position list (performed in both normal mode and SAFE_MODE).
7. For any open position without SL → instruct Order_Executor to re-attach SL (performed in both normal mode and SAFE_MODE).
8. If in SAFE_MODE: attempt deterministic state reconstruction using trusted MT5 live order book data and account history. If sufficient trusted data exists to reconstruct daily drawdown, total drawdown reference, and open position state, log the reconstructed values at INFO level for manual review. The EA remains in SAFE_MODE until the trader manually confirms and re-enables.
9. If NOT in SAFE_MODE: restore daily drawdown accumulator from state file. If current day differs from state file date → reset to zero and record new day-open equity.
10. Resume normal operation (SAFE_MODE: position monitoring only; normal: full trading operation).

**Version migration:**
- If `SCHEMA` in file < current `STATE_FILE_VERSION`: apply defined migration function and rewrite.
- If `SCHEMA` in file > current `STATE_FILE_VERSION` (EA downgrade): enter SAFE_MODE.
- If no migration function is defined for the file's schema version: enter SAFE_MODE.

**Safe monitoring mode (connection loss — distinct from SAFE_MODE):**
- Entered on broker connection loss.
- No new entry signals processed.
- Order_Executor polls open positions every 30 seconds.
- Exited only when all open positions have confirmed valid SL orders.

**Failure behavior:** Write failure to state file → log ERROR, continue operation (in-memory state still valid for current session). SAFE_MODE is always the default when file integrity cannot be confirmed. The EA must never silently operate on untrusted state.

**Testing requirements (updated for CONFLICT-1 resolution):**
- Property test: serialize then deserialize state file produces identical state for all field combinations.
- Property test: CRC32 checksum detects any single-byte mutation in any field.
- Property test: daily drawdown restored correctly on restart within same day.
- Edge case: corrupt checksum → SAFE_MODE entered, new entries blocked, CRITICAL logged.
- Edge case: missing state file (where prior state required) → SAFE_MODE entered, not warn-and-reset.
- Edge case: symbol mismatch → SAFE_MODE entered.
- Edge case: account suffix mismatch → SAFE_MODE entered.
- Edge case: unsupported schema version (higher than current) → SAFE_MODE entered.
- Edge case: `.tmp` file present at init with valid checksum → used as primary source.
- Edge case: `.tmp` file present at init with invalid checksum → fall back to main state file.
- Integration test: SAFE_MODE entered → positions reconciled from MT5 order book → SLs verified → manual re-enable required before new entries permitted.
- Integration test: successful state reconstruction in SAFE_MODE → reconstructed values logged → EA remains in SAFE_MODE until manual confirmation.
- Integration test: failed reconstruction (insufficient history) → WARNING logged identifying unresolvable fields → EA remains in SAFE_MODE.
- Property test: cooldown survives restart (start time preserved).

---

### 2.14 Logger

**Responsibility:** Stateless structured logging utility. Writes to MT5 Experts log and optionally to a local file. Callable from all modules without introducing any dependency cycle.

**Inputs:** Log level (DEBUG/INFO/WARN/ERROR/CRITICAL), module name, event type, event-specific field map.

**Outputs:** Log line: `LEVEL | ISO8601_UTC | MODULE | EVENT_TYPE | field1=value1 | field2=value2 ...`

**Dependencies:** MT5 `Print()` function, optional file handle.

**State:** None. The Logger holds no references to other modules.

**Masking rules:**
- Account number: all but last 4 digits replaced with `*`.
- No passwords, API keys, or credentials appear in any log output.

**Failure behavior:** Log write failure is silently ignored (best-effort logging must not crash the EA).

**Testing requirements:**
- Property test: for any account number string, log output masks all but last 4 digits.
- Property test: all required fields are present for each event type in the spec.
- Example test: CRITICAL event includes correct fields.

---

### 2.15 Config_Manager

**Responsibility:** Expose all EA input parameters grouped by module. Validate all parameter values at OnInit. Cache validated values for runtime access. Provide a single validated `Config` struct to all modules.

**Inputs:** MQL5 `input` variables.

**Outputs:** `Config` struct (populated on successful init). INIT_FAILED on any validation error.

**Dependencies:** Logger.

**Validation rules:** Every numeric parameter must be within its documented min/max range. Every enumeration parameter must be one of the documented valid values. Time parameters must represent valid HH:MM clock times.

**Failure behavior:** First invalid parameter causes INIT_FAILED with the parameter name, submitted value, and valid range logged.

**Testing requirements:** Unit test each parameter's boundary conditions (just inside valid range, just outside valid range).

---

## Data Models

### Core Interface Objects

```
// AnalysisStatus — output from each analysis engine / filter
struct AnalysisStatus {
    SignalType    signal_type;      // SWEEP_LONG, SWEEP_SHORT, BOS_LONG, BOS_SHORT,
                                   // REGIME_BULLISH, REGIME_BEARISH, REGIME_RANGING,
                                   // FILTER_ALLOWED, FILTER_BLOCKED, FILTER_WARN, UNKNOWN
    Direction     direction;        // LONG, SHORT, NONE
    int           confidence;       // 0–100
    datetime      timestamp;        // UTC broker server time of the event
    string        source_module;    // for logging / traceability
    string        rejection_reason; // populated if BLOCKED or UNKNOWN
}

// TradeSignal — output from Entry_Confirmation_Engine → input to Risk_Manager
// BLOCKER-1 RESOLVED: entry_price is the live Ask/Bid at signal generation time,
// NOT the triggering candle's close. signal_reference_price holds the candle close for audit only.
// BLOCKER-2 RESOLVED: take_profit_price is always the nearest Active opposing Liquidity_Pool
// that satisfies MinRR. BOS/CHOCH levels are not used as TP targets. If no pool satisfies MinRR,
// the signal is rejected with NO_VALID_TP before this struct is ever populated.
struct TradeSignal {
    double   entry_price;           // LIVE Ask (BUY) or Bid (SELL) at signal generation time
    double   signal_reference_price; // confirming candle close — for audit/logging only
    double   stop_loss_price;       // non-zero, below entry (long) or above entry (short); STATIC for position lifetime
    double   take_profit_price;     // nearest Active opposing Liquidity_Pool satisfying MinRR
    Direction direction;            // LONG or SHORT
    datetime signal_timestamp;      // UTC broker server time
    double   atr_at_signal;         // 1H ATR value at signal time (for audit)
    int      regime;                // 4H regime at signal time (for audit)
    double   computed_rr;           // R:R of this signal (for audit)
    string   tp_pool_level;         // price level of the selected TP pool (for audit)
    string   rejection_reason;      // populated only when signal is rejected; empty on approval
}

// TradeOrder — output from Risk_Manager → input to Order_Executor
struct TradeOrder {
    string   symbol;                // "XAUUSD"
    OrderType order_type;           // MARKET_BUY, MARKET_SELL
    double   volume;                // calculated and validated lot size
    double   entry_price;           // live Ask/Bid from TradeSignal (re-read at OrderSend time)
    double   signal_reference_price; // candle close that triggered signal (for audit only)
    double   stop_loss_price;       // validated against broker stop level; STATIC — never moved
    double   take_profit_price;     // validated against broker stop level
    datetime timestamp;             // UTC time of TradeOrder creation
    int      magic_number;          // EA's Magic_Number
    double   max_slippage_points;   // from Config
}

// ExecutionResult — output from Order_Executor
struct ExecutionResult {
    ExecutionStatus status;         // FILLED, REJECTED, FAILED
    long    ticket;                 // MT5 order ticket (0 if not filled)
    double  filled_price;           // actual fill price
    double  filled_sl;              // actual SL on the filled order
    double  filled_tp;              // actual TP on the filled order
    int     mt5_error_code;         // 0 on success
    string  error_description;
    datetime execution_timestamp;
}

// RejectionResult — output from Risk_Manager when TradeSignal is rejected
struct RejectionResult {
    string  unmet_criterion;        // e.g., "R:R below minimum", "Daily DD limit reached"
    double  computed_value;         // the value that failed the check
    double  required_value;         // the threshold
    datetime timestamp;
}

// SymbolProperties — populated once at OnInit from MT5
struct SymbolProperties {
    double  point;                  // SYMBOL_POINT
    double  lot_step;               // SYMBOL_VOLUME_STEP
    double  min_lot;                // SYMBOL_VOLUME_MIN
    double  max_lot;                // SYMBOL_VOLUME_MAX
    double  contract_size;          // SYMBOL_TRADE_CONTRACT_SIZE
    int     stop_level_points;      // SYMBOL_TRADE_STOPS_LEVEL
    int     freeze_level_points;    // SYMBOL_TRADE_FREEZE_LEVEL
    double  tick_size;              // SYMBOL_TRADE_TICK_SIZE
    double  tick_value;             // SYMBOL_TRADE_TICK_VALUE
    int     digits;                 // SYMBOL_DIGITS
    double  margin_initial;         // SYMBOL_MARGIN_INITIAL
}

// OHLCVBar — confirmed candle data (always bar index ≥ 1)
struct OHLCVBar {
    datetime time;
    double   open;
    double   high;
    double   low;
    double   close;
    long     tick_volume;
}

// SwingPoint
struct SwingPoint {
    datetime time;
    double   price;
    SwingType type;      // HIGH or LOW
    int      timeframe;  // PERIOD_H4, PERIOD_H1, etc.
    bool     confirmed;  // always true (pending swings never exposed externally)
}

// LiquidityPool
struct LiquidityPool {
    double   price_level;           // average price of clustered swing points
    double   tolerance_band;        // ATR × PoolATRTolerance at creation time
    PoolStatus status;              // ACTIVE, SWEPT, INVALIDATED
    datetime created_timestamp;
    datetime swept_timestamp;       // null if not swept
    Direction side;                 // ABOVE (resistance-side) or BELOW (support-side)
    AnalysisStatus sweep_event;     // populated when swept
}

// ATRResult
struct ATRResult {
    double   current_atr;           // current 1H ATR
    double   baseline_atr;          // 30-day average of 1H ATR
    ATRFilterStatus status;         // ALLOW, BLOCK_LOW, BLOCK_HIGH, UNAVAILABLE
    double   min_sl_distance;       // max(ATR × SLMultiplier, StopLevel × Point)
}

// MomentumResult
struct MomentumResult {
    MomentumStatus status;          // CONFIRMED, REJECTED, INSUFFICIENT_DATA
    double   range_high;
    double   range_low;
    double   close_position_pct;    // 0.0 = at range low, 1.0 = at range high
    string   rejection_reason;      // populated on REJECTED or INSUFFICIENT_DATA
}

// EA persistent state — in-memory representation
// BLOCKER-4 RESOLVED: Serialised to a plain-text key-value file with CRC32 checksum.
// File format: one KEY=VALUE line per field; [POOL_REGISTRY] section for pool data.
// See State_Manager design section for full file format specification.
struct EAState {
    double   daily_drawdown_pct;
    double   daily_open_equity;
    double   total_drawdown_ref_equity;
    int      consecutive_losses;
    datetime cooldown_start_utc;    // zero datetime if no cooldown active
    bool     circuit_breaker_triggered;
    bool     safe_mode_active;      // true when state file failed integrity check
    datetime last_update_utc;
    int      state_file_version;    // for forward-compatibility parsing
    string   symbol;                // symbol this state belongs to (for cross-check)
    string   account_suffix;        // last 4 digits of account number (for cross-check)
    uint     checksum;              // CRC32 of all preceding fields (validated on load)
}
```

---

### Multi-Timeframe Data Handling

Each analysis module receives a dedicated pre-filtered confirmed-candle array. The data access layer guarantees:
- Array index 0 of the returned array corresponds to bar index 1 of the MT5 series (the most recently closed candle).
- Bar[0] (currently forming) is never present in any array passed to any analysis module.
- Arrays are re-fetched on every new confirmed candle event (detected by bar count change on the relevant timeframe).

Timeframe-to-module assignment:
```
4H  → Market_Structure_Analyzer (regime)
1H  → Market_Structure_Analyzer (major structure, BOS/CHOCH) + ATR_Volatility_Engine
15M → Market_Structure_Analyzer (setup structure) + Liquidity_Detector
5M  → Momentum_Engine + Market_Structure_Analyzer (entry structure)
```

New-candle detection strategy: the EA tracks the `time` of the last-seen confirmed candle per timeframe. When `OHLCVBar[0].time` (bar[1] in MT5 terms, i.e., the newest confirmed candle) differs from the stored value, a new candle has closed and re-calculation is triggered for that timeframe's modules.

---


## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Confirmed-candle enforcement (no bar[0] access)

*For any* OHLCV time series of any length, every analysis module (Market_Structure_Analyzer, Liquidity_Detector, Momentum_Engine, ATR_Volatility_Engine) SHALL produce identical output whether or not bar[0] (the currently forming candle) is present or mutated — output must depend exclusively on bars at index ≥ 1.

**Validates: Requirements 1.1, 1.6, 2.7, 4.5, 15.5**

---

### Property 2: Swing confirmation side-count invariant

*For any* OHLCV sequence and configured `SwingSideCandles` value N, every swing point in the confirmed swing list must have at least N closed candles strictly before it and at least N closed candles strictly after it within the data window. No swing can be confirmed within the last N bars of the input.

**Validates: Requirements 1.1, 1.2**

---

### Property 3: Regime classification correctness

*For any* sequence of alternating confirmed Swing_High and Swing_Low points of length ≥ N, the regime classification must equal Bullish iff all consecutive swing highs are strictly increasing AND all consecutive swing lows are strictly increasing; Bearish iff all consecutive swing highs are strictly decreasing AND all consecutive swing lows are strictly decreasing; Ranging in all other cases.

**Validates: Requirements 1.3, 3.1, 3.2, 3.3, 3.4**

---

### Property 4: BOS fires at exactly the confirmed-candle close that crosses the swing level

*For any* price series and prior swing level, a BOS event is recorded at the bar whose confirmed close first exceeds the prior swing level — no earlier (false positive) and no later (missed detection).

**Validates: Requirements 1.4, 1.5**

---

### Property 5: Liquidity pool sweep detection round-trip

*For any* price series exhibiting a wick-through-and-close-back-inside pattern at an Active pool, a Liquidity_Sweep event is recorded, and the pool status transitions from Active to Swept. For any series without this pattern, no sweep event is recorded and pool status remains Active.

**Validates: Requirements 2.2, 2.4**

---

### Property 6: Pool lifecycle state machine validity

*For any* sequence of price events applied to a LiquidityPool, the pool's status transitions follow only the valid edges: Active → Swept, Active → Invalidated. No other transitions are permitted (e.g., Swept → Active, Invalidated → Swept).

**Validates: Requirements 2.3, 2.4**

---

### Property 7: MaxActivePools invariant

*For any* sequence of pool creation events exceeding `MaxActivePools`, the count of Active pools in the registry never exceeds `MaxActivePools`, and the oldest pool by creation timestamp is the one removed when the cap is exceeded.

**Validates: Requirements 2.5**

---

### Property 8: Ranging regime blocks all entries (unless Ranging_Mode_Enabled)

*For any* AnalysisStatus snapshot where the 4H regime is Ranging and `RangingModeEnabled = false`, the Entry_Confirmation_Engine must return null (no TradeSignal) regardless of any other signal inputs.

**Validates: Requirements 3.5, 3.6**

---

### Property 9: Momentum approval is symmetric by direction

*For any* 5M candle sequence of length ≥ N with a non-zero high-low range, a Long momentum signal is CONFIRMED iff `close ≥ range_midpoint`, and a Short momentum signal is CONFIRMED iff `close ≤ range_midpoint`. No other close position justifies approval.

**Validates: Requirements 4.1, 4.2, 4.3**

---

### Property 10: ATR filter correctness at all threshold boundaries

*For any* current ATR value and computed baseline ATR, the filter returns BLOCK_LOW iff `current_atr < baseline × min_multiplier`, BLOCK_HIGH iff `current_atr > baseline × max_multiplier`, and ALLOW otherwise. The boundary values (equal to threshold) must return ALLOW (inclusive bounds).

**Validates: Requirements 5.1, 5.2, 5.3**

---

### Property 11: SL distance enforces the ATR-broker floor

*For any* ATR value, SL multiplier, and broker stop level, the computed minimum SL distance in price units equals `max(current_atr × ATRSLMultiplier, stop_level_points × point_size)`. No SL closer than this floor may be passed to the Order_Executor.

**Validates: Requirements 5.4, 9.1, 10.8**

---

### Property 12: Session filter correctness across all timestamps

*For any* UTC timestamp and any configuration of enabled sessions with valid start/end times, the Session_Filter returns ALLOWED iff the timestamp falls within at least one enabled session window, and BLOCKED otherwise. Disabled sessions contribute no ALLOWED windows.

**Validates: Requirements 6.1, 6.2, 6.3, 6.4**

---

### Property 13: Spread filter independence (no cross-call caching)

*For any* pair of sequential calls to the Spread_Filter with different spread values, the result of the second call reflects only the second spread value — the result of the first call has no influence. BLOCKED iff spread_value > threshold.

**Validates: Requirements 7.2, 7.4**

---

### Property 14: News filter blocking windows cover all qualifying events

*For any* UTC timestamp, event list, and configured window parameters, the News_Filter returns BLOCKED iff the timestamp falls within `[event_utc - pre_minutes, event_utc + post_minutes]` for at least one event at or above `MinImpactLevel`. Outside all such windows, the filter returns ALLOWED.

**Validates: Requirements 8.3, 8.4**

---

### Property 15: Position sizing formula correctness

*For any* valid floating equity, entry price, stop-loss price, risk percentage, and symbol properties, the computed lot size equals `floor((RiskAmount / (SL_distance_price × TickValue / TickSize)) / LotStep) × LotStep`, clamped to `[MinLot, MaxLotSize]`.

**Validates: Requirements 9.1, 9.2, 9.8**

---

### Property 16: Lot size is always a valid multiple of LotStep within bounds

*For any* computed lot size and symbol LotStep, MinLot, MaxLotSize: the final lot size is always a non-negative multiple of LotStep, and if greater than zero, falls within `[MinLot, MaxLotSize]`. If the formula produces a value below MinLot after rounding, the TradeOrder is rejected.

**Validates: Requirements 9.8, 9.12**

---

### Property 17: R:R enforcement is symmetric

*For any* TradeSignal with non-zero entry, SL, and TP, the Risk_Manager approves iff the R:R ≥ MinRR. The computed R:R = `|TP - Entry| / |Entry - SL|`. Any TradeSignal with R:R strictly below MinRR is rejected with the computed and required values logged.

**Validates: Requirements 9.7**

---

### Property 18: Drawdown circuit breakers fire at or before threshold

*For any* sequence of position close events that accumulate daily loss or total loss, the appropriate circuit breaker fires at the tick in which the accumulated loss first meets or exceeds the configured threshold — it does not fire early (false positive) and does not miss the threshold.

**Validates: Requirements 9.4, 9.5, 9.6, 17.1**

---

### Property 19: Combined position risk never exceeds the multi-trade limit

*For any* set of open positions plus a proposed new TradeSignal, if accepting the new trade would cause total risk exposure (sum of all position risk amounts as percentage of floating equity) to exceed `RiskPerTradePct × MaxOpenTrades`, the new signal is rejected.

**Validates: Requirements 9.3, 9.11**

---

### Property 20: Every submitted order has SL and TP attached

*For any* TradeOrder that reaches the Order_Executor submission step, the submitted MT5 order must have `stop_loss ≠ 0` and `take_profit ≠ 0`. No order is submitted without both levels.

**Validates: Requirements 10.1, 10.2**

---

### Property 21: Post-fill SL/TP verification triggers correction on deviation

*For any* execution fill result where the filled SL or TP deviates from the submitted values by more than the broker stop level tolerance, the Order_Executor attempts exactly one correction via OrderModify in the same execution cycle. No correction is attempted when deviation is within tolerance.

**Validates: Requirements 10.4, 10.5**

---

### Property 22: State persistence round-trip

*For any* EAState value, serialising to file and then deserialising from the same file produces a value equal to the original in all fields. This must hold for all valid numeric ranges of each field.

**Validates: Requirements 11.4, 11.5, 17.6**

---

### Property 23: Drawdown restoration correctness on same-day restart

*For any* EAState file containing a `daily_drawdown_pct` value recorded on day D, when the EA restarts on day D, the restored `daily_drawdown_pct` equals the persisted value. When restarted on day D+1 or later, the `daily_drawdown_pct` is reset to zero.

**Validates: Requirements 11.4, 11.5, 17.2**

---

### Property 24: Log masking for account numbers

*For any* string containing a numeric account number, the Logger's output replaces all digits except the last four with `*`. The last four digits remain unchanged. The masking must apply consistently regardless of the length of the account number.

**Validates: Requirements 12.6**

---

### Property 25: Structured log entries contain all required fields per event type

*For any* loggable event of a defined type (signal generated, signal approved, signal rejected, order submitted, order filled, order rejected, order modified, order closed, risk limit triggered, filter blocked, EA state change), the log entry contains all required fields for that event type as specified in Requirement 12.1.

**Validates: Requirements 12.1, 12.2, 12.3**

---

### Property 26: Margin threshold blocks entries below the floor

*For any* current free margin value and required margin, entries are blocked iff `free_margin < MinFreeMarginPct × required_margin_all_open_positions`. Above or equal to the threshold, margin is not a blocking factor.

**Validates: Requirements 17.7**

---

### Property 27: Execution entry price is always a live Ask/Bid — never a candle close (BLOCKER-1)

*For any* TradeSignal, the `entry_price` field contains the value of `SymbolInfoDouble(SYMBOL_ASK)` (BUY) or `SymbolInfoDouble(SYMBOL_BID)` (SELL) read at signal generation time — not the close of the triggering candle. The `signal_reference_price` field contains the triggering candle close. These two values will differ and must not be interchanged. The Order_Executor re-reads the live Ask/Bid again immediately before each `OrderSend` call.

**Validates: Requirements 10.11, 10.12**

---

### Property 28: Take-profit is always the nearest qualifying Active opposing Liquidity_Pool (BLOCKER-2)

*For any* TradeSignal where `take_profit_price` is populated, there exists an Active Liquidity_Pool on the opposing side whose `price_level` equals `take_profit_price` AND whose `|price_level − entry_price| / |entry_price − stop_loss_price| ≥ MinRR`. No other pool exists on the opposing side that is closer to `entry_price` and also satisfies this R:R condition. If no qualifying pool exists, the TradeSignal has `rejection_reason = NO_VALID_TP` and the signal is not passed to the Risk_Manager.

**Validates: Requirements 18.1, 18.3, 18.4, 18.5, 18.6**

---

### Property 29: Stop-loss is static for the lifetime of each position (BLOCKER-3)

*For any* filled order managed by the EA, the stop-loss level attached at order submission must equal the stop-loss level observed at every subsequent position-monitoring cycle, unless a CRITICAL correction event is logged. The EA never initiates an `OrderModify` call that changes the stop-loss level as part of normal position management (only SL re-attachment after external removal is permitted).

**Validates: Requirements 18.8, 18.13**

---

### Property 30: State file CRC32 checksum detects corruption (BLOCKER-4)

*For any* valid state file, any mutation of a single character in any line above the CHECKSUM line produces a CRC32 value that does not match the stored CHECKSUM, causing SAFE_MODE to be entered. For any unmodified file, the CRC32 verification passes and the file is accepted as valid.

**Validates: Requirements 19.3, 19.4**

---

### Property 31: Backtest slippage modes produce independent, non-mixed result sets (BLOCKER-5)

*For any* backtest run on the same parameter set and data, the Base, Conservative, and Stress result sets produce different P&L outcomes (Base ≥ Conservative ≥ Stress in aggregate return terms for any non-trivial trade sequence with positive trades). No result set borrows data or metrics from another. Parameter rankings are derived exclusively from Conservative results.

**Validates: Requirements 20.1, 20.3, 20.4, 20.5**

---

### Property 32: Freeze-level skip produces a structured WARN log and never bypasses broker restriction

*For any* Order_Executor monitoring cycle in which a position modification (SL re-attachment, SL modify, TP modify) is blocked because the position is within `SYMBOL_TRADE_FREEZE_LEVEL` of the current price:
1. The modification is not attempted via `OrderModify`.
2. A WARN-level log entry is written containing all seven required fields: symbol, ticket, operation, current price, freeze-level value, required distance, reason="FREEZE_LEVEL_ACTIVE", and UTC timestamp.
3. No new trade or workaround order is opened.
4. If the skipped operation was a mandatory SL re-attachment and the position remains missing its SL after `MaxFreezeSkips` consecutive skips, the position is force-closed per Requirement 17.5.

**Validates: Requirements 10.13, 10.14**

## Error Handling

### Error Classification

| Category | Examples | Response |
|---|---|---|
| Fatal init | Missing symbol property, invalid parameter | INIT_FAILED — EA does not start |
| Fatal runtime | Total drawdown circuit breaker | Close all positions, disable EA, require manual restart |
| Fatal runtime (state integrity) | Corrupt state file, missing state, invalid checksum, unsupported schema, symbol/account mismatch | Enter SAFE_MODE: block new entries, reconcile positions, log CRITICAL, require manual re-enable |
| Critical runtime | Missing SL on open position (re-attach fails), SL/TP mismatch (correction fails) | Close affected position, log CRITICAL |
| Recoverable | Non-fatal order error (requote, price changed) | Retry up to MaxRetries, then cancel |
| Data unavailability | Timeframe UNKNOWN, ATR unavailable, server time unavailable | Block entries, continue monitoring, retry next tick |
| Configuration warning | All sessions disabled, stale news list | Log warning, apply configured fallback |
| Non-blocking | Logger write failure | Silent (logging must not crash EA) |

### Error Propagation Rules

1. Every module returns a typed result that explicitly encodes success or failure — no implicit failures through default values.
2. The Entry_Confirmation_Engine treats any UNKNOWN status from any analysis module as a hard block.
3. The Order_Executor treats any non-successful ExecutionResult as a failure, not a partial success.
4. State_Manager treats a write failure as non-fatal for current session but logs at ERROR.
5. No module catches errors from another module's internal logic — errors propagate through the return type.

### Connection Loss Handling

```
Connection Lost
      │
      ▼
State_Manager enters Safe Monitoring Mode
      │
      ├─ No new entry signals accepted
      ├─ Order_Executor polls open positions every 30s
      └─ Entry_Confirmation_Engine blocked
      
Connection Restored
      │
      ▼
Order_Executor verifies all open positions have valid SL
      │
      ├─ All SLs valid → exit Safe Monitoring Mode
      └─ Any SL missing → re-attach → if fail → close position
                           → THEN exit Safe Monitoring Mode
```

---

## MQL5 Project Structure

```
xauusd-ea/
├── xauusd_ea.mq5                     ← Main EA file: event handlers only
├── include/
│   ├── core/
│   │   ├── Types.mqh                 ← All struct definitions, enums
│   │   ├── Constants.mqh             ← EA-level constants (Magic Number, version)
│   │   └── Interfaces.mqh            ← Abstract interface definitions
│   ├── data/
│   │   ├── SymbolPropertiesReader.mqh
│   │   └── MTFDataFeed.mqh
│   ├── analysis/
│   │   ├── MarketStructureAnalyzer.mqh
│   │   ├── LiquidityDetector.mqh
│   │   ├── ATRVolatilityEngine.mqh
│   │   └── MomentumEngine.mqh
│   ├── filters/
│   │   ├── SessionFilter.mqh
│   │   ├── SpreadFilter.mqh
│   │   └── NewsFilter.mqh
│   ├── engine/
│   │   └── EntryConfirmationEngine.mqh
│   ├── risk/
│   │   └── RiskManager.mqh
│   ├── execution/
│   │   └── OrderExecutor.mqh
│   ├── state/
│   │   └── StateManager.mqh
│   └── utils/
│       ├── Logger.mqh
│       └── ConfigManager.mqh
├── config/
│   └── news_events.csv               ← Economic calendar data file
└── tests/
    └── (MQL5 unit test scripts — one per module)
```

**Include rules:**
- `xauusd_ea.mq5` includes each module `.mqh` exactly once.
- No module includes another module's `.mqh` except through the defined interfaces in `Interfaces.mqh`.
- `Logger.mqh` and `Types.mqh` are the only files included by more than one module.
- Circular includes are prevented by include guards (`#pragma once` or `#ifndef` guards).

---

## Python Research / Backtesting Structure

```
python-research/
├── data/
│   ├── loaders/
│   │   ├── csv_loader.py             ← Load OHLCV from CSV
│   │   ├── mt5_loader.py             ← Load via MT5 Python API
│   │   └── data_feed.py              ← Confirmed-candle enforcing feed (bar[1:])
│   └── raw/                          ← Historical OHLCV files (gitignored)
├── strategy/
│   ├── market_structure.py           ← Mirrors MarketStructureAnalyzer.mqh
│   ├── liquidity.py                  ← Mirrors LiquidityDetector.mqh
│   ├── atr_engine.py                 ← Mirrors ATRVolatilityEngine.mqh
│   ├── momentum.py                   ← Mirrors MomentumEngine.mqh
│   ├── session_filter.py             ← Mirrors SessionFilter.mqh
│   ├── news_filter.py                ← Mirrors NewsFilter.mqh
│   └── entry_engine.py               ← Mirrors EntryConfirmationEngine.mqh
├── risk/
│   └── risk_manager.py               ← Mirrors RiskManager.mqh
├── backtest/
│   ├── engine.py                     ← Backtest loop (confirmed-candle enforcing)
│   ├── trade_log.py                  ← Trade record writer (CSV/JSON)
│   └── walk_forward.py               ← Walk-forward validation orchestrator
├── research/
│   ├── sensitivity_analysis.py       ← Parameter sweep tool
│   └── report_generator.py           ← Results → structured CSV/JSON
├── tests/
│   ├── unit/                         ← One test file per strategy module
│   ├── integration/                  ← Cross-module tests
│   └── strategy/                     ← Walk-forward strategy validation tests
├── config/
│   └── default_config.yaml           ← Default parameter set
└── notebooks/
    └── exploratory/                  ← Jupyter notebooks (not in production path)
```

**No-look-ahead enforcement in Python:**
The `data_feed.py` module wraps all data access. Its `get_bars(timeframe, as_of_index)` method returns `data[0:as_of_index]` — i.e., all data strictly before the current bar index. The backtest engine calls this method and never passes raw arrays to strategy modules directly. This makes it structurally impossible for any strategy module to access future data.

---

## Backtesting Architecture

### Backtest Engine Design

```
BacktestEngine
├── DataFeed (confirmed-candle enforcing slice)
├── StrategyPipeline (mirrors MQL5 analysis layers)
├── RiskManager (Python port — identical logic)
├── TradeSimulator (fill simulation with configurable slippage model)
├── PositionTracker (open/close positions, running P&L)
├── EquityTracker (daily and total drawdown accounting)
└── TradeLogWriter (outputs per Requirement 16.4)
```

**Backtest execution loop:**
```
For each bar from bar[N_warmup] to bar[T-1]:
    1. data_feed.get_bars(tf, current_index) → confirmed history up to current_index - 1
    2. Run all analysis modules on confirmed history
    3. Entry_Confirmation_Engine → TradeSignal or null
    4. Risk_Manager → TradeOrder or rejection
    5. TradeSimulator.fill(TradeOrder) → simulated fill at next bar's open
    6. Check all open positions: SL/TP hit → close, record
    7. Update EquityTracker
    8. Write TradeLog record if any trade opened or closed
```

**Slippage and execution cost model (BLOCKER-5 RESOLVED):**

Every backtest run is executed three times with the same parameter set, using three independently configured execution cost assumptions. Results are reported separately and never mixed:

| Result Set | Slippage Mode | Slippage Value | Commission |
|---|---|---|---|
| **Base** | MODE A (Fixed) | 0 points | $0/lot |
| **Conservative** | MODE A (Fixed) | `SlippageFixedPoints` (default 2) | `CommissionPerLot` (default $7.00/lot round-turn) |
| **Stress** | MODE B (Variable) | Half-normal draw: mean=`SlippageMeanPoints`, σ=`SlippageStdDevPoints` | `CommissionPerLot × 1.5` |

- **MODE A:** Fill price = next bar open ± `SlippageFixedPoints × Point` (adverse direction: + for BUY, + for SELL in absolute cost terms).
- **MODE B:** Slippage draw = `|N(mean, std_dev)|` (half-normal, always ≥ 0, applied as adverse cost). Seeds are fixed per run for reproducibility.
- **Ranking:** "Best parameter" rankings use **Conservative** results only. A parameter combination passes validation only if Conservative drawdown ≤ `FlagDrawdownThreshold`.
- **Output:** Every report header includes the slippage mode name, all cost parameters, and the random seed (MODE B only).
- No look-ahead into the fill bar under any mode.

**Warmup period:** The first `max(ATR_period × timeframe_ratio, RegimeSwingCount × swing_bars)` bars are consumed as warmup to populate indicators. No trades are taken during warmup.

---

## Walk-Forward Validation Architecture

### Design

Walk-forward validation is the only permitted validation methodology for this system. Random train/test splits are explicitly prohibited for time-series data.

```
Walk-Forward Validator
├── Anchor start date
├── In-sample window size (e.g., 12 months)
├── Out-of-sample window size (e.g., 3 months)
├── Step size (e.g., 3 months — rolling or anchored)
└── N folds

For each fold:
    1. Optimise parameters on in-sample window
    2. Evaluate fixed parameters on out-of-sample window (no re-optimisation)
    3. Record out-of-sample metrics
    4. Advance window by step size
    5. Aggregate metrics across all OOS folds → combined equity curve
```

**Metrics per fold and aggregate:**
- Total return (%)
- Maximum drawdown (%)
- Sharpe ratio (annualised)
- Win rate (%)
- Profit factor
- Trade count
- Consecutive loss maximum
- Recovery factor

**Stability criteria:**
- Parameters are considered robust if OOS performance degrades gracefully (within configurable tolerance, e.g., ≤ 30% degradation from IS to OOS across all folds).
- High variance across OOS folds indicates overfitting.

---

## Sensitivity Analysis Architecture

The sensitivity analysis tool in `research/sensitivity_analysis.py` sweeps configurable parameter ranges and records performance metrics for each combination.

**Output columns per parameter set:**
```
param_1, param_2, ..., param_N,
total_return_pct, max_drawdown_pct, sharpe_ratio,
win_rate_pct, profit_factor, trade_count,
flagged (bool: max_DD > DD_threshold)
```

**Flagging rule:** Any parameter combination with `max_drawdown_pct > FlagDrawdownThreshold` (default 20%) is marked `flagged=true` and excluded from automatic "best parameter" ranking.

**Output format:** CSV and JSON (both written by default).

**No look-ahead in sweeps:** The same `data_feed.py` confirmed-candle enforcing wrapper is used during sweeps. Parameter optimisation cannot benefit from future data at any point.

---

## Test Architecture

### Testing Layers

```
Layer 1: Unit Tests (per module, no external dependencies)
         ├── Python: pytest + Hypothesis (property-based testing)
         └── MQL5: custom MQL5 unit test scripts in /tests/

Layer 2: Integration Tests (cross-module, no live broker)
         ├── Python: pytest with synthetic data pipelines
         └── MQL5: MT5 Strategy Tester with scripted inputs

Layer 3: Strategy Tests (walk-forward validation)
         └── Python: walk_forward.py against historical data

Layer 4: Live-Execution Safety Tests (MT5 demo account)
         └── MQL5: EA on MT5 demo with monitored safety scenarios
```

### Unit Tests

Each module has a corresponding test file. Tests are organised as:

**Market_Structure_Analyzer tests:**
- Property: no swing within last N bars (bar-index constraint).
- Property: regime classification for all swing sequence patterns.
- Property: BOS fires at exactly the correct candle.
- Edge case: insufficient bars → UNKNOWN status.
- Edge case: equal highs on both sides of a candle.

**Liquidity_Detector tests:**
- Property: pool detection within ATR tolerance.
- Property: sweep detection only when wick-through + close-back pattern.
- Property: pool state machine — invalid transitions rejected.
- Property: MaxActivePools invariant.
- Property: swept pool generates no further sweep events.
- Edge case: ATR unavailable → no new pools.

**ATR_Volatility_Engine tests:**
- Property: filter output correct at all threshold boundaries.
- Property: SL distance enforces the ATR-broker floor.
- Edge case: fewer than 14 bars → UNAVAILABLE.
- Edge case: ATR = 0 → UNAVAILABLE.

**Momentum_Engine tests:**
- Property: long CONFIRMED iff close ≥ midpoint.
- Property: short CONFIRMED iff close ≤ midpoint.
- Edge case: zero range → INSUFFICIENT_DATA.
- Edge case: fewer than N candles → INSUFFICIENT_DATA.

**Session_Filter tests:**
- Property: ALLOWED iff timestamp in at least one enabled session.
- Edge case: all sessions disabled → BLOCKED.
- Edge case: invalid session times → that session treated as BLOCKED.
- Edge case: server time unavailable → BLOCKED.

**Spread_Filter tests:**
- Property: BLOCKED iff spread > threshold.
- Property: sequential calls with different spreads give independent results.

**News_Filter tests:**
- Property: BLOCKED iff timestamp in any qualifying event window.
- Example: WARN mode returns WARN not BLOCKED.
- Edge case: stale list applies fallback.

**Entry_Confirmation_Engine tests:**
- Property: null signal on any BLOCKED input.
- Property: TradeSignal fields all non-zero when approved.
- Property: Ranging regime always blocks (unless Ranging_Mode_Enabled).

**Risk_Manager tests:**
- Property: lot size formula correctness.
- Property: lot size always valid multiple of LotStep within bounds.
- Property: R:R enforcement.
- Property: daily and total drawdown thresholds.
- Property: combined exposure limit.
- Edge case: lot size rounds to zero → rejection.
- Edge case: SL = entry price → rejection.

**Order_Executor tests (mock MT5):**
- Property: every submitted order has SL and TP.
- Property: post-fill verification triggers correction on deviation.
- Example: retry sequence on non-fatal errors.
- Example: SL missing on open position triggers re-attach.

**State_Manager tests:**
- Property: serialize/deserialize round-trip.
- Property: daily drawdown correctly restored on same-day restart.
- Property: cooldown start time survives restart.
- Edge case: corrupt file → SAFE_MODE entered (not warn-and-reset); positions reconciled; manual re-enable required.

**Logger tests:**
- Property: account number masking.
- Property: all required fields present per event type.

### Integration Tests

Integration tests verify correct data flow across module boundaries:

1. **AnalysisStatus pipeline test:** Feed synthetic OHLCV through Market_Structure_Analyzer + Liquidity_Detector + ATR_Volatility_Engine + Momentum_Engine → verify AnalysisStatus objects have correct types, directions, and confidence values.

2. **TradeSignal generation test:** Combine all analysis outputs through Entry_Confirmation_Engine → verify TradeSignal fields are consistent with the analysis inputs (direction matches regime + BOS, SL distance respects ATR floor, TP meets R:R).

3. **TradeOrder generation test:** Pass TradeSignal through Risk_Manager → verify TradeOrder lot size, SL, and TP.

4. **State persistence integration test:** Simulate a sequence of trades, persist state, reload, verify drawdown state and cooldown are correctly restored.

5. **Restart recovery integration test:** Simulate a set of open positions, restart the EA, verify State_Manager reconstructs all positions with correct state and re-attaches any missing SLs.

6. **Circuit breaker integration test:** Simulate loss sequence reaching total drawdown threshold → verify circuit breaker fires, all positions closed, EA disabled.

### Strategy Tests (walk-forward)

Strategy tests verify that the system produces broadly sensible behaviour on historical data — they do not assert profitability.

1. **No look-ahead bias verification:** Run backtest twice — once with genuine historical data, once with future data injected at each bar. Verify outputs are identical (future data has no effect because the data feed enforces bar[1:] slicing).

2. **Walk-forward stability test:** Run walk-forward across all available history; assert OOS degradation ≤ configured tolerance; assert no single OOS fold has drawdown above the circuit breaker threshold.

3. **Circuit breaker activation test:** Run a scenario with a known losing parameter set; assert the circuit breaker fires before account loss exceeds the total drawdown limit.

4. **Filter coverage test:** Confirm that across a full historical run, each filter (session, spread, news, ATR, momentum, regime) is responsible for at least one signal rejection — verifies filters are being exercised.

### Live-Execution Safety Tests (MT5 Demo)

These tests run on a live MT5 demo account with monitored execution. They verify safety behaviours that cannot be tested in a pure backtest.

1. **SL attachment test:** Manually remove the SL from an EA-managed position; verify the EA re-attaches it within the next tick cycle and logs a CRITICAL event.

2. **Spread spike test:** Wait for or simulate a spread spike above `MaxSpreadPoints`; verify the pending order is cancelled and the cancellation is logged with both spread values.

3. **Connection drop test:** Disconnect the terminal from the broker; reconnect; verify the EA enters and exits safe monitoring mode correctly and all open positions have valid SLs before re-enabling.

4. **Daily drawdown test:** Manually set `DailyMaxDrawdownPct` to a small value; open a test position; let it hit the limit; verify all positions are closed and entries are blocked for the remainder of the day.

5. **Total drawdown circuit breaker test:** Manually set `TotalMaxDrawdownPct` to a small value; trigger it; verify the EA disables itself and does not re-enable automatically.

6. **Restart state recovery test:** Open a position, stop the terminal, restart it, verify the EA reconstructs the position state correctly and SL is present.

7. **Cooldown test:** Set `MaxConsecutiveLosses` to 2; trigger two consecutive losses; verify entries are blocked for `CooldownHours` and the cooldown survives a restart.

---

## Testing Strategy

The system uses four testing layers, each targeting a different scope of verification.

**Layer 1 — Unit Tests (per module, no external dependencies)**
Every module has a corresponding test file. Python modules are tested with pytest and Hypothesis (property-based testing). MQL5 modules use custom MQL5 unit test scripts. Critical risk and confirmed-candle properties are tested with at least 1000 generated cases each. See Appendix F for per-module coverage targets and the full list of correctness properties.

**Layer 2 — Integration Tests (cross-module data flow)**
Integration tests verify that AnalysisStatus objects flow correctly from analysis engines into the Entry_Confirmation_Engine, that TradeSignal fields are consistent with analysis inputs, and that the full pipeline from OHLCV data to TradeOrder behaves correctly for representative scenarios. State persistence and restart recovery are also covered at this layer.

**Layer 3 — Strategy Tests (walk-forward validation)**
Walk-forward validation is the only permitted back-test validation methodology. No random train/test splits are used. The backtest engine enforces no-look-ahead at the data-access layer (confirmed-candle slice, bar[1:] only). A no-look-ahead canary test injects corrupt values into bar[0] on every tick and asserts that strategy outputs are identical — any divergence indicates a look-ahead bug. Walk-forward results must show graceful OOS degradation; high variance across folds flags overfitting.

**Layer 4 — Live-Execution Safety Tests (MT5 demo account)**
Safety behaviours that cannot be tested in a pure backtest are verified on a live MT5 demo account: SL re-attachment after manual SL removal, spread spike order cancellation, connection-drop safe mode entry and exit, daily and total drawdown circuit breakers, restart state recovery, and cooldown persistence across restarts. A minimum of four weeks of observed demo operation is required before any live capital is risked.

See Appendix F for the detailed testing strategy including property-based testing configuration, coverage matrix, and anti-overfitting protocol.

---

## Appendix A: Architecture Diagram (ASCII)

```
╔══════════════════════════════════════════════════════════════════════════════╗
║                        XAU/USD MT5 EA — ARCHITECTURE                        ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  ┌─────────────────────────────────────────────────────────────────────┐    ║
║  │                    MT5 RUNTIME (TICK / TIMER)                       │    ║
║  │                    xauusd_ea.mq5  OnTick / OnTimer                 │    ║
║  └────────────────────────────┬────────────────────────────────────────┘    ║
║                               │                                              ║
║  ┌────────────────────────────▼────────────────────────────────────────┐    ║
║  │  DATA LAYER                                                          │    ║
║  │  SymbolPropertiesReader  ←→  MTFDataFeed (4H / 1H / 15M / 5M)      │    ║
║  │  (init-time, cached)         (per-tick, confirmed bar[1:] only)     │    ║
║  └────────┬────────────────────────────┬───────────────────────────────┘    ║
║           │ OHLCVBar[]                 │ SymbolProperties                   ║
║  ┌────────▼──────────────────────────────────────────────────────────┐      ║
║  │  ANALYSIS LAYER                                                    │      ║
║  │                                                                    │      ║
║  │  ┌───────────────────────┐   ┌──────────────────────────────┐    │      ║
║  │  │ MarketStructureAnalyzer│   │  LiquidityDetector           │    │      ║
║  │  │  4H: Regime           │   │  15M: Pools, Sweeps          │    │      ║
║  │  │  1H: BOS / CHOCH      │   │  Lifecycle management        │    │      ║
║  │  │  15M/5M: structure    │   └──────────────┬───────────────┘    │      ║
║  │  └──────────────┬────────┘                  │                    │      ║
║  │                 │                            │                    │      ║
║  │  ┌──────────────▼──────┐   ┌────────────────▼───────────────┐   │      ║
║  │  │  ATRVolatilityEngine│   │  MomentumEngine                │   │      ║
║  │  │  1H ATR / baseline  │   │  5M close vs range             │   │      ║
║  │  └──────────────┬──────┘   └────────────────┬───────────────┘   │      ║
║  └─────────────────┼────────────────────────────┼───────────────────┘      ║
║                    │  AnalysisStatus             │  AnalysisStatus           ║
║  ┌─────────────────▼────────────────────────────▼───────────────────┐      ║
║  │  FILTER LAYER                                                     │      ║
║  │  SessionFilter  SpreadFilter  NewsFilter                          │      ║
║  │  (all return AnalysisStatus: ALLOWED / BLOCKED / WARN)           │      ║
║  └─────────────────────────────────┬─────────────────────────────────┘      ║
║                                    │  AnalysisStatus[] (all sources)         ║
║  ┌─────────────────────────────────▼─────────────────────────────────┐      ║
║  │  ENTRY CONFIRMATION ENGINE                                         │      ║
║  │  Aggregates all AnalysisStatus inputs                              │      ║
║  │  Applies all blocking rules → TradeSignal or NULL                 │      ║
║  └─────────────────────────────────┬─────────────────────────────────┘      ║
║                                    │  TradeSignal                            ║
║  ┌─────────────────────────────────▼─────────────────────────────────┐      ║
║  │  RISK MANAGER (independent of strategy)                            │      ║
║  │  Validates signal, sizes position, enforces all drawdown limits    │      ║
║  │  → TradeOrder or RejectionResult                                   │      ║
║  └─────────────────────────────────┬─────────────────────────────────┘      ║
║                                    │  TradeOrder                             ║
║  ┌─────────────────────────────────▼─────────────────────────────────┐      ║
║  │  ORDER EXECUTOR (sole MT5 trade caller)                            │      ║
║  │  Spread check → Submit → Verify fill → Retry → SL/TP monitoring  │      ║
║  └─────────────────────────────────────────────────────────────────────┘      ║
║                                                                              ║
║  CROSS-CUTTING (available to all layers, no upward calls)                   ║
║  ┌──────────────┐  ┌─────────────────────┐  ┌──────────────────────────┐   ║
║  │  Logger      │  │   State_Manager      │  │  Config_Manager          │   ║
║  │  (stateless) │  │  (persist/restore)   │  │  (validated inputs)      │   ║
║  └──────────────┘  └─────────────────────┘  └──────────────────────────┘   ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

---

## Appendix B: Module Dependency Diagram (ASCII)

```
Arrows show "depends on" (→ = reads from / calls into).
Cross-cutting services (Logger, Config, StateManager) are not re-drawn per edge for clarity.

  SymbolPropertiesReader ←── Config_Manager
         ↑
  MTFDataFeed ←──────────────────────────────────────────────────────────────┐
         │                                                                    │
         ├──► MarketStructureAnalyzer                                        │
         ├──► LiquidityDetector ←── ATRVolatilityEngine ←── MTFDataFeed    │
         ├──► ATRVolatilityEngine                                            │
         └──► MomentumEngine                                                 │
                                                                             │
  All 4 analysis modules ──► EntryConfirmationEngine                        │
  SessionFilter ────────────► EntryConfirmationEngine                       │
  NewsFilter ───────────────► EntryConfirmationEngine                       │
                                                                             │
  EntryConfirmationEngine ──► RiskManager ←── StateManager                 │
                                         └──► SymbolPropertiesReader        │
                                                                             │
  RiskManager ──────────────► OrderExecutor                                 │
  SpreadFilter ─────────────► OrderExecutor ──────────────────────────────►─┘
  StateManager ─────────────► OrderExecutor

  Logger ◄── (all modules write to Logger; Logger writes to nothing)
  Config_Manager ◄── (read by all modules at init; no writes back)
  StateManager ◄──► (read and written by: RiskManager, OrderExecutor, EntryConfirmationEngine)
```

---

## Appendix C: Data-Flow Diagram (ASCII)

```
MT5 Tick Event
      │
      ▼
MTFDataFeed.GetBars(4H/1H/15M/5M)
      │
      │  OHLCVBar[] per timeframe (bar[1:] only)
      │
      ├──────────────────────────────────────────────────────────────────────┐
      │                                                                      │
      ▼                                                                      ▼
MarketStructureAnalyzer                                          ATRVolatilityEngine
(4H Regime, 1H BOS/CHOCH,                                      (1H ATR, baseline,
 15M/5M swings)                                                  min SL distance)
      │                                                                      │
      │ AnalysisStatus[]                                                     │ ATRResult
      │                                                                      │
      ▼                                                                      ▼
LiquidityDetector ◄────────────────── ATRResult (15M tolerance)   MomentumEngine
(15M pools, sweeps)                                               (5M close vs range)
      │                                                                      │
      │ AnalysisStatus                                                       │ MomentumResult
      │                                                                      │
      ├──────────────────────────────────────────────────────────────────────┤
      │                                                                      │
      │              SessionFilter ──► FilterStatus                         │
      │              SpreadFilter  ──► FilterStatus (at submission only)    │
      │              NewsFilter    ──► FilterStatus                         │
      │                                                                      │
      └──────────────────────► EntryConfirmationEngine ◄───────────────────┘
                                           │
                                    [all pass?]
                                    YES          NO
                                     │            └──► LOG rejection reason
                                     ▼
                                TradeSignal
                                     │
                                     ▼
                               Risk_Manager
                                     │
                             [all checks pass?]
                             YES              NO
                              │               └──► RejectionResult → LOG
                              ▼
                          TradeOrder
                              │
                              ▼
                        Order_Executor
                              │
                    Spread_Filter check
                              │
                    [spread OK?]
                    YES        NO
                     │         └──► Cancel + LOG
                     ▼
               OrderSend → MT5
                     │
               [fill confirmed?]
               YES            NO (non-fatal)
                │              └──► Retry (up to MaxRetries) → Cancel
                ▼
         Verify SL/TP on fill
                │
         [match within tolerance?]
         YES             NO
          │               └──► OrderModify correction → if fail → CRITICAL log
          ▼
    State_Manager.UpdatePosition()
          │
          ▼
    Logger.WriteTradeEvent()
```

---

## Appendix D: State-Machine Design (ASCII)

### EA Operational State Machine

```
                          ┌──────────────────┐
                          │  INIT_FAILED      │ (terminal — requires fix + restart)
                          └──────────────────┘
                                  ▲
                    Invalid param │ or missing symbol prop
                                  │
         ┌──────────────────────────────────────────────────────────┐
         │                      INITIALISING                         │
         │  - Load config (validate all params)                      │
         │  - Read SymbolProperties                                   │
         │  - Read state file (validate checksum, schema, symbol/account)│
         │  - If invalid → enter SAFE_MODE, reconcile positions         │
         │  - Scan MT5 order book → rebuild position state          │
         │  - Re-attach missing SLs                                  │
         └──────────────────────┬───────────────────────────────────┘
                                │ All checks pass
                                ▼
         ┌──────────────────────────────────────────────────────────┐
         │                   RUNNING (NORMAL)                        │
         │  - Process ticks                                          │
         │  - Run full analysis pipeline                             │
         │  - Accept and submit trade signals                        │
         │  - Monitor open positions every tick                      │
         └──┬─────────────────────────────────────────┬─────────────┘
            │                                         │
            │ Connection lost                         │ Daily DD limit reached
            ▼                                         ▼
 ┌──────────────────────────┐           ┌─────────────────────────────────┐
 │   SAFE MONITORING MODE   │           │   DAILY CIRCUIT BREAKER         │
 │  - No new entries        │           │  - All positions closed          │
 │  - Poll positions /30s   │           │  - Entries blocked rest of day   │
 │  - Verify SLs            │           │  - Resets at midnight UTC        │
 └────────────┬─────────────┘           └────────────────┬────────────────┘
              │ All SLs confirmed                         │ Midnight UTC
              │ after reconnection                        ▼
              └──────────────────────────────────► RUNNING (NORMAL)
            
            │ Total DD limit reached
            │ OR circuit_breaker_triggered=true at init
            ▼
 ┌──────────────────────────────────────────────────────────────────────────┐
 │                     HARD DISABLED (circuit breaker)                       │
 │  - All positions closed                                                   │
 │  - circuit_breaker_triggered = true persisted to state file              │
 │  - No trading operations of any kind                                      │
 │  - CRITICAL log written                                                   │
 │  - Requires manual removal and re-attachment of EA to chart               │
 └──────────────────────────────────────────────────────────────────────────┘

            │ Cooldown condition (max consecutive losses)
            ▼
 ┌──────────────────────────────────────────────────────────────────────────┐
 │                          COOLDOWN                                         │
 │  - Entries blocked for CooldownHours                                      │
 │  - Position monitoring continues                                           │
 │  - Cooldown start time persisted to state file                            │
 │  - Automatically exits after cooldown period expires                      │
 └──────────────────────────────────────────────────────────────────────────┘
```

### Position State Machine

```
         OrderSend submitted
               │
               ▼
         ┌───────────┐
         │  PENDING   │
         └─────┬──────┘
               │ Fill confirmed (MT5 returns TRADE_RETCODE_DONE)
               ▼
         ┌───────────┐
         │   OPEN    │ ←─────────────────────────────────────────────┐
         │ (has SL,  │                                                │
         │  has TP)  │ SL missing detected → re-attach attempted      │
         └─────┬─────┘ (if re-attach succeeds, remains OPEN)         │
               │                                                       │
    ┌──────────┼──────────────────────────────────┐                  │
    │          │                                   │                  │
    │ SL hit   │ TP hit    │ Manual close  │ SL re-attach fails       │
    ▼          ▼           ▼               ▼                          │
 ┌─────┐  ┌─────┐    ┌─────────┐  ┌──────────────┐                  │
 │CLOS-│  │CLOS-│    │ CLOSED  │  │ FORCE-CLOSED │                  │
 │ED   │  │ED   │    │(manual) │  │(safety close)│                  │
 │(SL) │  │(TP) │    └─────────┘  └──────────────┘                  │
 └─────┘  └─────┘                                                     │
    All closed states → Update consecutive loss counter               │
                      → Update daily drawdown accumulator             │
                      → Persist state file                            │
```

---

## Appendix E: Risk-Control Hierarchy

The risk controls are layered, with each layer independent of the strategy and each layer capable of acting without any layer above it.

```
╔══════════════════════════════════════════════════════════════════════╗
║  LEVEL 1 — HARD CIRCUIT BREAKER (cannot be bypassed)                ║
║  Total account drawdown from OnInit equity ≥ TotalMaxDrawdownPct     ║
║  → Close ALL positions → Disable EA → Require manual restart         ║
║  → circuit_breaker_triggered = true persisted                        ║
╠══════════════════════════════════════════════════════════════════════╣
║  LEVEL 2 — DAILY CIRCUIT BREAKER (resets at midnight)               ║
║  Intraday loss from day-open equity ≥ DailyMaxDrawdownPct            ║
║  → Close ALL positions → Block entries for rest of day               ║
╠══════════════════════════════════════════════════════════════════════╣
║  LEVEL 3 — CONSECUTIVE LOSS COOLDOWN                                 ║
║  Consecutive losing trades ≥ MaxConsecutiveLosses                    ║
║  → Block entries for CooldownHours                                   ║
║  → Persisted across restarts                                         ║
╠══════════════════════════════════════════════════════════════════════╣
║  LEVEL 4 — OPEN POSITION PROTECTION (per-tick monitoring)            ║
║  Every open EA position checked for valid SL every tick              ║
║  → Missing SL: re-attach immediately                                  ║
║  → Re-attach fails: force-close position                             ║
╠══════════════════════════════════════════════════════════════════════╣
║  LEVEL 5 — POSITION SIZING CAP                                       ║
║  All trades sized by fixed risk formula (RiskPerTradePct × equity)   ║
║  → Hard cap at MaxLotSize regardless of formula                      ║
║  → Combined multi-position risk capped at RiskPerTradePct × MaxTrades║
╠══════════════════════════════════════════════════════════════════════╣
║  LEVEL 6 — R:R MINIMUM FILTER                                        ║
║  TradeSignal rejected if R:R < MinRR                                 ║
╠══════════════════════════════════════════════════════════════════════╣
║  LEVEL 7 — ENTRY FILTER STACK                                        ║
║  Any BLOCKED status from: Session, Spread, News, ATR, Momentum,      ║
║  Regime → No TradeSignal generated                                   ║
╠══════════════════════════════════════════════════════════════════════╣
║  LEVEL 8 — FREE MARGIN GUARD                                         ║
║  Free margin < MinFreeMarginPct × required margin → Entries blocked  ║
╠══════════════════════════════════════════════════════════════════════╣
║  LEVEL 9 — EXECUTION VALIDATION                                      ║
║  Every order: SL required, TP required, stop > broker stop level     ║
║  Every fill: SL/TP verified against submitted values                 ║
║  Spread checked at submission time only                              ║
╚══════════════════════════════════════════════════════════════════════╝
```

**Prohibited practices enforced at every level:**
- No martingale (position size from formula only, prior losses are not inputs).
- No grid (no price-ladder order placement).
- No recovery strategy (new signals evaluated independently, not as recovery of prior losses).
- No averaging down without combined-risk cap (Level 5 governs all combined exposure).

---

## Appendix F: Testing Strategy

### Property-Based Testing Configuration

- Library: **Hypothesis** (Python), custom MQL5 test scripts for MQL5 unit tests.
- Minimum iterations per property: **100** (Hypothesis default; increase to 1000 for critical risk properties).
- Tag format for every property test: `# Feature: xauusd-mt5-ea, Property N: <property_text>`

### Test Coverage Targets

| Module | Unit | Integration | Strategy | Safety |
|---|---|---|---|---|
| Market_Structure_Analyzer | ✓ (Properties 1–4) | ✓ | ✓ | — |
| Liquidity_Detector | ✓ (Properties 5–7) | ✓ | ✓ | — |
| ATR_Volatility_Engine | ✓ (Properties 10–11) | ✓ | — | — |
| Momentum_Engine | ✓ (Property 9) | ✓ | — | — |
| Session_Filter | ✓ (Property 12) | ✓ | — | ✓ |
| Spread_Filter | ✓ (Property 13) | ✓ | — | ✓ |
| News_Filter | ✓ (Property 14) | ✓ | — | — |
| Entry_Confirmation_Engine | ✓ (Properties 8, 20) | ✓ | ✓ | — |
| Risk_Manager | ✓ (Properties 15–19) | ✓ | ✓ | ✓ |
| Order_Executor | ✓ (Properties 20–21) | ✓ | — | ✓ |
| State_Manager | ✓ (Properties 22–23) | ✓ | — | ✓ |
| Logger | ✓ (Properties 24–25) | — | — | — |

### No-Look-Ahead Verification Protocol

All Python backtest tests include a **no-look-ahead canary test**:
1. Run the full pipeline on a test data set.
2. Corrupt bar[0] of every timeframe with extreme values (e.g., OHLC = 999999).
3. Run the pipeline again.
4. Assert that all strategy module outputs are **identical** between runs 1 and 2.
5. If any output differs, the module is accessing bar[0] — test fails.

### Walk-Forward Anti-Overfitting Protocol

1. Never optimise on the full dataset.
2. Report IS and OOS metrics for every fold separately.
3. Flag any fold where OOS Sharpe < 0.
4. Flag any fold where OOS drawdown > IS drawdown × 2.
5. Only proceed to live demo testing if aggregate OOS metrics meet minimum thresholds (configurable).

---

## Appendix G: Implementation Order

The implementation follows a dependency-first sequence. Each component is testable before the next is built.

```
Phase 1 — Foundation (no trading logic)
  1.1  Types.mqh + Constants.mqh (all structs and enums)
  1.2  Logger.mqh (stateless, no dependencies)
  1.3  ConfigManager.mqh (parameter validation)
  1.4  SymbolPropertiesReader.mqh (MT5 API wrapper)
  1.5  MTFDataFeed.mqh (confirmed-candle enforcing data access)
  1.6  StateManager.mqh (file persistence, restart logic)
  → Python equivalents of all above

Phase 2 — Analysis Engines (pure functions, no broker calls)
  2.1  ATRVolatilityEngine.mqh (feeds into LiquidityDetector)
  2.2  MarketStructureAnalyzer.mqh (swing, BOS, CHOCH, regime)
  2.3  LiquidityDetector.mqh (pools, sweeps, lifecycle)
  2.4  MomentumEngine.mqh (5M momentum)
  → Python equivalents + unit tests (Hypothesis) for all above

Phase 3 — Filter Layer
  3.1  SessionFilter.mqh
  3.2  NewsFilter.mqh
  3.3  SpreadFilter.mqh (used at execution time — design here, wire in Phase 5)
  → Python equivalents + unit tests

Phase 4 — Signal and Risk (core trading logic)
  4.1  EntryConfirmationEngine.mqh (aggregation + TradeSignal)
  4.2  RiskManager.mqh (sizing + all limit checks)
  → Integration tests: full pipeline from OHLCV to TradeOrder

Phase 5 — Execution (live broker calls)
  5.1  OrderExecutor.mqh (OrderSend, verify, retry, SL monitoring)
  → Demo account execution tests
  → Safety tests (SL monitoring, circuit breakers)

Phase 6 — Python Backtesting and Walk-Forward
  6.1  backtest/engine.py (confirmed-candle enforcing loop)
  6.2  backtest/walk_forward.py (walk-forward orchestrator)
  6.3  research/sensitivity_analysis.py (parameter sweep)
  → Walk-forward validation runs on historical data

Phase 7 — Integration and Live Safety
  7.1  Full end-to-end integration test on MT5 demo
  7.2  All live-execution safety tests (Appendix F)
  7.3  Minimum 4 weeks of live demo observation before any live capital
```

---

*Design document version: 1.0 — XAU/USD MT5 EA*
*All strategy components are independently testable. Profitability is not assumed or asserted.*
