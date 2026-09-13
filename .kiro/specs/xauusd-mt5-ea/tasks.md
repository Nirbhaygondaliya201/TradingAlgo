# Implementation Plan: XAU/USD MT5 Expert Advisor

## Overview

This plan converts the approved design into 13 sequential implementation phases for a professional
XAU/USD algorithmic trading Expert Advisor running on MetaTrader 5. The MQL5 EA is the primary
deliverable; the Python research environment is a companion system built in parallel where specified.

Implementation language: **MQL5** (EA) + **Python 3.10+** (research environment).

All tasks follow the dependency-first sequence defined in Appendix G of the design document.
No module is implemented before its dependencies are complete and tested.

**26 correctness properties** from the design document each have dedicated property-based test
sub-tasks (§ Phase 11). Property tests use **Hypothesis** (Python) and custom MQL5 script harnesses.

---

## ⚠️ BLOCKER Status

All five blockers have been **RESOLVED** by the trader/architect. Decisions are documented below
and incorporated into the requirements, design, and task specifications. No blockers remain open.

| BLOCKER ID | Status | Decision Summary |
|---|---|---|
| BLOCKER-1 | ✅ RESOLVED | Entry price = live Ask/Bid at signal time; signal_reference_price = candle close for audit only; spread re-checked before every OrderSend |
| BLOCKER-2 | ✅ RESOLVED | TP = nearest Active opposing Liquidity_Pool satisfying MinRR; BOS/CHOCH not used as TP; no qualifying pool → NO_VALID_TP rejection, trade not taken |
| BLOCKER-3 | ✅ RESOLVED | V1 uses static SL only; no trailing stop, no break-even, no partial TP, no averaging |
| BLOCKER-4 | ✅ RESOLVED | State file = native MQL5 plain-text key-value with CRC32 checksum; [POOL_REGISTRY] CSV section; SAFE_MODE on any integrity failure |
| BLOCKER-5 | ✅ RESOLVED | Two slippage modes (MODE A: fixed, MODE B: variable half-normal); three result sets per run (Base / Conservative / Stress); rankings use Conservative only |

---

## Tasks

---

### Phase 1: Foundation

**Objective:** Establish all shared infrastructure — types, constants, logging, configuration
validation, symbol-property access, confirmed-candle data feed, and state persistence — before
any trading logic is written. All subsequent phases depend on this phase being complete and tested.

---

- [ ] 1. Set up MQL5 project structure and core type definitions
  - Create the full directory tree: `xauusd-ea/`, `include/core/`, `include/data/`,
    `include/analysis/`, `include/filters/`, `include/engine/`, `include/risk/`,
    `include/execution/`, `include/state/`, `include/utils/`, `config/`, `tests/`
  - Write `include/core/Types.mqh`: all struct definitions (`AnalysisStatus`, `TradeSignal`,
    `TradeOrder`, `ExecutionResult`, `RejectionResult`, `SymbolProperties`, `OHLCVBar`,
    `SwingPoint`, `LiquidityPool`, `ATRResult`, `MomentumResult`, `EAState`)
  - Write `include/core/Constants.mqh`: Magic Number, EA version string, state file version integer
  - Write `include/core/Interfaces.mqh`: abstract interface definitions for each module
  - Add `#pragma once` include guards to every file
  - _Requirements: 13.1, 13.7, 14.1_

  - [ ] 1.1 Create MQL5 project directory structure and Types.mqh
    - Implement all structs and enums exactly as specified in the Data Models section of the design
    - All enum values: `SignalType`, `Direction`, `PoolStatus`, `ATRFilterStatus`, `MomentumStatus`,
      `ExecutionStatus`, `OrderType`, `SwingType`
    - _Requirements: 13.7_

  - [ ]* 1.2 Unit test: verify all struct fields are accessible and zero-initialise correctly
    - MQL5 test script in `tests/test_types.mq5`
    - _Requirements: 13.1_

  - [ ] 1.3 Create Python research environment directory structure and base types
    - Create `python-research/` tree matching the design's Python structure
    - Write `python-research/strategy/types.py`: Python dataclasses mirroring all MQL5 structs
    - Write `python-research/config/default_config.yaml` with all default parameter values
    - _Requirements: 16.1_

---

- [ ] 2. Implement Logger module
  - Write `include/utils/Logger.mqh`: stateless structured logging
  - Output format: `LEVEL | ISO8601_UTC | MODULE | EVENT_TYPE | field1=value1 | ...`
  - Implement log-level filtering: DEBUG, INFO, WARN, ERROR, CRITICAL
  - Implement account-number masking: all digits except last four replaced with `*`
  - Log write failures are silently ignored (must not crash EA)
  - Optional file output handle
  - _Requirements: 12.1, 12.2, 12.5, 12.6, 13.6_

  - [ ] 2.1 Implement Logger.mqh with masking and level filtering
    - MQL5 `Print()` output + optional file handle
    - All required fields per event type (as per Req 12.1)
    - _Requirements: 12.1, 12.2, 12.5, 12.6_

  - [ ]* 2.2 Write property test for account number masking (Property 24)
    - **Property 24: Log masking for account numbers**
    - **Validates: Requirements 12.6**
    - Generate account numbers of length 4–20 digits; verify all but last 4 are `*`

  - [ ]* 2.3 Write property test for structured log field completeness (Property 25)
    - **Property 25: Structured log entries contain all required fields per event type**
    - **Validates: Requirements 12.1, 12.2, 12.3**
    - For each event type, generate random field values; assert all required fields present in output

  - [ ] 2.4 Implement Python Logger module
    - Write `python-research/strategy/logger.py` mirroring Logger.mqh
    - Same masking and field-completeness rules
    - _Requirements: 16.1_

---

- [ ] 3. Implement Config_Manager module
  - Write `include/utils/ConfigManager.mqh`
  - Expose all EA input parameters grouped by module using MQL5 input group separators
  - Validate all parameters at OnInit: numeric ranges, enum values, time format (HH:MM)
  - On first invalid parameter: log error (name, value, valid range) and return INIT_FAILED
  - Cache validated values in a `Config` struct accessible to all modules
  - _Requirements: 14.1, 14.2, 14.3_

  - [ ] 3.1 Implement ConfigManager.mqh with full parameter validation
    - One input group per module: `=== Risk Settings ===`, `=== Session Settings ===`, etc.
    - All parameters with default values from design document
    - _Requirements: 14.1, 14.2, 14.3_

  - [ ]* 3.2 Unit tests for Config_Manager boundary conditions
    - Test each parameter at: just inside valid range, just outside valid range, exact boundary
    - Confirm INIT_FAILED on any out-of-range value
    - _Requirements: 14.2_

  - [ ] 3.3 Implement Python Config module
    - Write `python-research/config/config.py` using YAML loader with same validation rules
    - _Requirements: 16.1_

---

- [ ] 4. Implement Symbol_Properties_Reader module
  - Write `include/data/SymbolPropertiesReader.mqh`
  - Read at OnInit: `SYMBOL_POINT`, `SYMBOL_VOLUME_STEP`, `SYMBOL_TRADE_CONTRACT_SIZE`,
    `SYMBOL_TRADE_STOPS_LEVEL`, `SYMBOL_MARGIN_INITIAL`
  - Also read: `SYMBOL_VOLUME_MIN`, `SYMBOL_VOLUME_MAX`, `SYMBOL_TRADE_FREEZE_LEVEL`,
    `SYMBOL_TRADE_TICK_SIZE`, `SYMBOL_TRADE_TICK_VALUE`, `SYMBOL_DIGITS`
  - If any mandatory property fails → log error with property name → return INIT_FAILED
  - Broker stop level = 0 is valid (not an error)
  - Contract size and tick value must be validated > 0
  - Immutable after successful init; expose `IsValid()` flag
  - _Requirements: 14.4, 14.5_

  - [ ] 4.1 Implement SymbolPropertiesReader.mqh
    - All 11 SymbolProperties struct fields populated from MT5 API
    - `IsValid()` flag checked by consuming modules
    - _Requirements: 14.4, 14.5_

  - [ ]* 4.2 Unit tests for SymbolPropertiesReader
    - Test: all five mandatory properties populated → IsValid() = true
    - Test: each mandatory property individually missing → INIT_FAILED
    - Test: stop level = 0 is accepted (not an error)
    - _Requirements: 14.4, 14.5_

  - [ ] 4.3 Implement Python SymbolProperties module
    - Write `python-research/data/loaders/symbol_props.py`
    - Accepts properties from YAML config (for backtesting — no live MT5 dependency)
    - _Requirements: 16.1_

---

- [ ] 5. Implement MultiTimeframe_DataFeed module
  - Write `include/data/MTFDataFeed.mqh`
  - `GetBars(timeframe, count)` returns `OHLCVBar[]` starting at MT5 bar index 1 (never bar 0)
  - Check `SeriesInfoInteger(symbol, timeframe, SERIES_SYNCHRONIZED)` before returning data
  - Return 0 bars and set `BarsAvailable = 0` if series not yet synchronised
  - No caching — every call fetches fresh from `CopyRates`
  - Callers must check `BarsAvailable` before proceeding
  - Track last-seen confirmed candle `time` per timeframe for new-candle detection
  - _Requirements: 1.1, 1.6, 4.5, 15.5_

  - [ ] 5.1 Implement MTFDataFeed.mqh with confirmed-candle enforcement
    - Array index 0 of returned array = MT5 bar index 1
    - New-candle detection via stored `last_bar_time` per timeframe
    - _Requirements: 1.1, 1.6_

  - [ ]* 5.2 Write property test for confirmed-candle enforcement (Property 1)
    - **Property 1: Confirmed-candle enforcement (no bar[0] access)**
    - **Validates: Requirements 1.1, 1.6, 2.7, 4.5, 15.5**
    - Mutate bar[0] with extreme values; assert all module outputs are identical

  - [ ]* 5.3 Unit tests for MTFDataFeed edge cases
    - Test: unsynchronised series → BarsAvailable = 0
    - Test: GetBars never includes bar[0] for any requested count
    - _Requirements: 1.6_

  - [ ] 5.4 Implement Python DataFeed module
    - Write `python-research/data/loaders/data_feed.py`
    - `get_bars(timeframe, as_of_index)` returns `data[0:as_of_index]` (structurally prevents look-ahead)
    - Write `python-research/data/loaders/csv_loader.py` and `mt5_loader.py`
    - _Requirements: 16.2, 16.3_

---

- [ ] 6. Implement State_Manager module
  - Write `include/state/StateManager.mqh`
  - Persist `EAState` struct to file atomically (write to temp file, then rename)
  - State fields: `daily_drawdown_pct`, `daily_open_equity`, `total_drawdown_ref_equity`,
    `consecutive_losses`, `cooldown_start_utc`, `circuit_breaker_triggered`, `last_update_utc`,
    `state_file_version`
  - On read: missing/unparseable file, failed checksum, symbol/account mismatch, or unsupported schema → enter SAFE_MODE (block new entries, reconcile positions from MT5 order book, log CRITICAL, require manual re-enable). Do NOT warn-and-reset.
  - On read: `circuit_breaker_triggered = true` → INIT_FAILED (requires manual intervention)
  - Day-change detection: if restart on different day than state file → reset daily accumulator
  - Safe monitoring mode: entered on connection loss, no new entries, poll every 30s
  - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7, 17.2, 17.3_

  - [ ] 6.1 Implement StateManager.mqh — persistence and restart recovery sequence
    - Atomic file write (temp + rename pattern)
    - Full restart recovery sequence (steps 1–6 from design §2.13)
    - Day-change detection and daily accumulator reset
    - _Requirements: 11.4, 11.5, 11.6, 17.2_

  - [ ] 6.2 Implement StateManager safe monitoring mode
    - Enter on connection loss; poll open positions every 30 seconds
    - Exit only when all open positions have confirmed valid SL orders
    - _Requirements: 11.3, 11.7, 17.3_

  - [ ]* 6.3 Write property test for state persistence round-trip (Property 22)
    - **Property 22: State persistence round-trip**
    - **Validates: Requirements 11.4, 11.5, 17.6**
    - Generate arbitrary EAState values; serialise and deserialise; assert all fields equal

  - [ ]* 6.4 Write property test for drawdown restoration on same-day restart (Property 23)
    - **Property 23: Drawdown restoration correctness on same-day restart**
    - **Validates: Requirements 11.4, 11.5, 17.2**
    - Same-day restart → restored value equals persisted; day+1 restart → reset to zero

  - [ ]* 6.5 Edge-case tests for State_Manager (CONFLICT-1 authoritative behavior)
    - Corrupt checksum → SAFE_MODE entered, CRITICAL logged, new entries blocked
    - Missing state file (where continuity required) → SAFE_MODE entered (not warn-and-reset)
    - Unsupported schema version → SAFE_MODE entered
    - Symbol mismatch in state file → SAFE_MODE entered
    - Account suffix mismatch → SAFE_MODE entered
    - `circuit_breaker_triggered = true` in valid file → INIT_FAILED returned
    - `.tmp` file valid → used as primary source; `.tmp` file invalid → fall back to main
    - _Requirements: 11.6, 11.8, 11.9, 19.4, 19.5, 19.8_

  - [ ] 6.6 Implement Python State_Manager module
    - Write `python-research/strategy/state_manager.py`
    - JSON serialisation/deserialisation of EAState
    - _Requirements: 16.1_

- [ ] 7. Phase 1 Checkpoint
  - Ensure all Phase 1 tests pass, ask the user if questions arise.
  - All MQL5 include files compile without errors in MT5
  - Python modules importable with no dependency errors
  - BLOCKER-4 (state file format for pool_registry) resolved before Phase 9

---

### Phase 2: Market Data

**Objective:** Implement and validate the confirmed-candle enforcing data pipeline. All analysis
modules depend on this pipeline producing correct bar arrays. The ATR engine is built first because
the Liquidity_Detector depends on it for pool tolerance calculation.

---

- [ ] 8. Implement ATR_Volatility_Engine module
  - Write `include/analysis/ATRVolatilityEngine.mqh`
  - Compute 1H ATR over `ATRPeriod` (default 14) confirmed candles
  - Compute 30-day baseline ATR from 720 most recent closed 1H candles
  - Filter status: `ALLOW` / `BLOCK_LOW` / `BLOCK_HIGH` / `UNAVAILABLE`
  - Min SL distance = `max(ATR × ATRSLMultiplier, stop_level_points × point_size)`
  - ATR = 0 or negative → UNAVAILABLE + log ERROR
  - Fewer than `ATRPeriod` candles → UNAVAILABLE
  - Fewer than 720 candles for baseline → log WARNING, use available history (minimum 14)
  - Rolling baseline buffer (720 values)
  - All calculations from bar index ≥ 1
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_

  - [ ] 8.1 Implement ATRVolatilityEngine.mqh — ATR calculation and filter logic
    - Standard true range formula; Wilder's smoothing
    - Baseline buffer management
    - _Requirements: 5.1, 5.2, 5.3_

  - [ ] 8.2 Implement ATR-derived SL distance calculation
    - `min_sl_distance = max(current_atr × ATRSLMultiplier, stop_level_points × point)`
    - _Requirements: 5.4, 9.1, 10.8_

  - [ ]* 8.3 Write property test for ATR filter correctness at all threshold boundaries (Property 10)
    - **Property 10: ATR filter correctness at all threshold boundaries**
    - **Validates: Requirements 5.1, 5.2, 5.3**
    - Generate (current_atr, baseline_atr, min_mult, max_mult) tuples; verify correct status;
      boundary values (equal to threshold) must return ALLOW (inclusive bounds)

  - [ ]* 8.4 Write property test for SL distance ATR-broker floor (Property 11)
    - **Property 11: SL distance enforces the ATR-broker floor**
    - **Validates: Requirements 5.4, 9.1, 10.8**
    - For any (atr, multiplier, stop_level, point): result = max(atr×mult, stop_level×point)

  - [ ]* 8.5 Unit tests for ATR edge cases
    - Fewer than 14 bars → UNAVAILABLE
    - ATR = 0 → UNAVAILABLE
    - Baseline computed from fewer than 720 bars → WARNING log, no crash
    - _Requirements: 5.5, 5.6_

  - [ ] 8.6 Implement Python ATR engine module
    - Write `python-research/strategy/atr_engine.py` mirroring ATRVolatilityEngine.mqh
    - _Requirements: 16.1_

---

- [ ] 9. Phase 2 Checkpoint
  - ATR engine produces correct output for known historical sequences
  - All property tests for Properties 10, 11 pass
  - Ensure all tests pass, ask the user if questions arise.

---

### Phase 3: Analysis Engines

**Objective:** Implement all four analysis engines — Market_Structure_Analyzer, Liquidity_Detector,
and Momentum_Engine — and their full unit and property test suites.

---

- [ ] 10. Implement Market_Structure_Analyzer module
  - Write `include/analysis/MarketStructureAnalyzer.mqh`
  - Swing detection on all four timeframes using confirmed candles only
  - `SwingSideCandles` (default 2): requires N confirmed candles on each side of extremum
  - Pending (unconfirmed) candidates within last N bars are never exposed externally
  - Equal highs/lows (to the tick): rightmost with required side candles taken as extremum
  - BOS: confirmed close beyond prior swing high (bullish) or low (bearish) on 1H or higher
  - CHOCH: BOS in direction opposite to current Regime
  - 4H Regime: Bullish / Bearish / Ranging based on last N alternating swing points
  - Regime change logged with previous regime, new regime, and trigger candle timestamp
  - Insufficient bars → `StructureResult.status = UNKNOWN`
  - Circular buffers holding last `RegimeSwingCount × 2` confirmed swing points per timeframe
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 3.1, 3.2, 3.3, 3.4, 3.7, 3.8_

  - [ ] 10.1 Implement swing detection logic (all four timeframes)
    - Confirmed-candle only; side-count validation; equal-high/low tie-breaking
    - Circular buffer management per timeframe
    - _Requirements: 1.1, 1.2_

  - [ ]* 10.2 Write property test for swing side-count invariant (Property 2)
    - **Property 2: Swing confirmation side-count invariant**
    - **Validates: Requirements 1.1, 1.2**
    - For any OHLCV sequence and N: every confirmed swing has ≥ N candles on each side;
      no swing confirmed within last N bars of input

  - [ ] 10.3 Implement BOS and CHOCH detection
    - BOS fires at bar whose confirmed close first crosses the prior swing level
    - CHOCH logged when BOS direction opposes current regime
    - _Requirements: 1.4, 1.5_

  - [ ]* 10.4 Write property test for BOS exact-candle detection (Property 4)
    - **Property 4: BOS fires at exactly the confirmed-candle close that crosses the swing level**
    - **Validates: Requirements 1.4, 1.5**
    - Plant a specific swing level in a synthetic series; verify BOS fires at exactly the correct bar
      (no false positives, no missed detections)

  - [ ] 10.5 Implement 4H regime classification engine
    - Bullish: all N consecutive swing highs strictly increasing AND all N swing lows strictly increasing
    - Bearish: all N strictly decreasing (highs and lows)
    - Ranging: all other cases including insufficient history
    - Default Ranging on insufficient history; log WARNING
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.8_

  - [ ]* 10.6 Write property test for regime classification correctness (Property 3)
    - **Property 3: Regime classification correctness**
    - **Validates: Requirements 1.3, 3.1, 3.2, 3.3, 3.4**
    - Generate arbitrary alternating swing sequences; verify Bullish/Bearish/Ranging exactly matches
      the HH/HL and LH/LL rules

  - [ ]* 10.7 Edge-case tests for Market_Structure_Analyzer
    - Fewer than minimum bars → UNKNOWN status returned
    - Equal highs on both sides of a candle → correct tie-breaking
    - Fewer than 2 confirmed swings at init → Ranging + WARNING
    - _Requirements: 1.7, 3.8_

  - [ ] 10.8 Implement Python Market_Structure module
    - Write `python-research/strategy/market_structure.py` mirroring MarketStructureAnalyzer.mqh
    - _Requirements: 16.1_

---

- [ ] 11. Implement Liquidity_Detector module
  - Write `include/analysis/LiquidityDetector.mqh`
  - Detect Liquidity_Pool zones: ≥ 2 swing highs or lows within `PoolATRTolerance × ATR`
  - Tolerance computed at pool creation time; ATR changes do not resize existing pools
  - Sweep detection: wick/close through pool + subsequent confirmed candle closes back inside
  - Never read bar[0] for sweep confirmation
  - Pool lifecycle: Active → Swept (sweep confirmed) / Active → Invalidated (close beyond tolerance without sweep)
  - Swept pool cannot be reactivated; new pool may form within tolerance band
  - Pool registry capped at `MaxActivePools` (default 20) per direction
  - Oldest pool by creation timestamp discarded when cap exceeded
  - ATR unavailable → suspend new pool detection; existing pools remain; AnalysisStatus = UNKNOWN
  - Pool registry persisted to state file (see BLOCKER-4)
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

  - [ ] 11.1 Implement pool detection logic (equal-high/low clustering within ATR tolerance)
    - Pool created from confirmed swing points; tolerance locked at creation ATR
    - _Requirements: 2.1, 2.6_

  - [ ] 11.2 Implement sweep detection and pool lifecycle management
    - Wick-through + confirmed close-back-inside pattern
    - Invalidation: close beyond tolerance without sweep confirmation
    - _Requirements: 2.2, 2.3, 2.4, 2.7_

  - [ ]* 11.3 Write property test for liquidity sweep round-trip (Property 5)
    - **Property 5: Liquidity pool sweep detection round-trip**
    - **Validates: Requirements 2.2, 2.4**
    - Generate price series with planted sweep pattern; assert sweep event recorded, pool → Swept;
      generate series without pattern; assert no sweep, pool remains Active

  - [ ]* 11.4 Write property test for pool lifecycle state machine (Property 6)
    - **Property 6: Pool lifecycle state machine validity**
    - **Validates: Requirements 2.3, 2.4**
    - Apply arbitrary price event sequences to a pool; assert only valid transitions occur
      (Active→Swept, Active→Invalidated; no reverse or invalid transitions)

  - [ ]* 11.5 Write property test for MaxActivePools invariant (Property 7)
    - **Property 7: MaxActivePools invariant**
    - **Validates: Requirements 2.5**
    - Generate pool creation sequences exceeding MaxActivePools; assert pool count ≤ cap;
      assert oldest pool removed first

  - [ ]* 11.6 Edge-case tests for Liquidity_Detector
    - ATR unavailable → no new pools created, existing pools retained, status = UNKNOWN
    - Swept pool generates no further sweep events for same pool object
    - _Requirements: 2.6_

  - [ ] 11.7 Implement Python Liquidity module
    - Write `python-research/strategy/liquidity.py` mirroring LiquidityDetector.mqh
    - _Requirements: 16.1_

---

- [ ] 12. Implement Momentum_Engine module
  - Write `include/analysis/MomentumEngine.mqh`
  - 5M momentum: compare most recently closed 5M candle's close vs. high-low range of prior N candles
  - `MomentumLookback` (default 10); valid range 2–50
  - Long: CONFIRMED iff `close ≥ range_midpoint`
  - Short: CONFIRMED iff `close ≤ range_midpoint`
  - Range = 0 → INSUFFICIENT_DATA (prevent divide-by-zero)
  - Fewer than N candles → INSUFFICIENT_DATA with logged reason
  - Bar[0] never read; all calculations from bar index ≥ 1
  - Output: `MomentumResult` (status, range_high, range_low, close_position_pct, rejection_reason)
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

  - [ ] 12.1 Implement MomentumEngine.mqh
    - Midpoint calculation; symmetric approval logic; INSUFFICIENT_DATA guards
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

  - [ ]* 12.2 Write property test for momentum symmetry by direction (Property 9)
    - **Property 9: Momentum approval is symmetric by direction**
    - **Validates: Requirements 4.1, 4.2, 4.3**
    - Generate arbitrary candle sequences with non-zero range; verify Long CONFIRMED iff
      close ≥ midpoint; Short CONFIRMED iff close ≤ midpoint

  - [ ]* 12.3 Edge-case tests for Momentum_Engine
    - Zero high-low range → INSUFFICIENT_DATA
    - Fewer than N candles → INSUFFICIENT_DATA with logged candle count and range
    - _Requirements: 4.4_

  - [ ] 12.4 Implement Python Momentum module
    - Write `python-research/strategy/momentum.py` mirroring MomentumEngine.mqh
    - _Requirements: 16.1_

- [ ] 13. Phase 3 Checkpoint
  - All analysis engine property tests pass (Properties 1–7, 9–11)
  - Python modules produce identical outputs to MQL5 modules on shared test vectors
  - Ensure all tests pass, ask the user if questions arise.

---

### Phase 4: Filter Layer

**Objective:** Implement all three filters. Each filter is independently testable and returns
`FilterStatus` (ALLOWED / BLOCKED / WARN). The SpreadFilter is designed here but wired into
the Order_Executor in Phase 7.

---

- [ ] 14. Implement Session_Filter module
  - Write `include/filters/SessionFilter.mqh`
  - Sessions: London (default 07:00–12:00 UTC), New York (13:00–17:00 UTC),
    London/NY Overlap (13:00–15:00 UTC)
  - Individual enable/disable flags per session
  - Configurable UTC offsets per session for DST (valid range: −12 to +14)
  - UTC offset applied to session window boundaries, not to server time
  - Uses broker server time (`TimeCurrent()`) — never local PC time
  - Server time unavailable → BLOCKED + log ERROR
  - All sessions disabled → BLOCKED + log config WARNING
  - Invalid session times (start ≥ end) → that session treated as BLOCKED + log config ERROR
  - Output: `FilterStatus` (ALLOWED / BLOCKED)
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9_

  - [ ] 14.1 Implement SessionFilter.mqh
    - Session window overlap detection; DST offset handling
    - _Requirements: 6.1, 6.2, 6.4, 6.5, 6.6_

  - [ ]* 14.2 Write property test for session filter timestamp correctness (Property 12)
    - **Property 12: Session filter correctness across all timestamps**
    - **Validates: Requirements 6.1, 6.2, 6.3, 6.4**
    - Generate arbitrary UTC timestamps and session configs; assert ALLOWED iff timestamp falls
      in at least one enabled window; disabled sessions contribute no ALLOWED results

  - [ ]* 14.3 Edge-case tests for Session_Filter
    - All sessions disabled → BLOCKED + WARNING
    - Server time unavailable → BLOCKED + ERROR
    - Invalid session window (start ≥ end) → that session BLOCKED + config ERROR
    - _Requirements: 6.7, 6.8, 6.9_

  - [ ] 14.4 Implement Python Session_Filter module
    - Write `python-research/strategy/session_filter.py`
    - _Requirements: 16.1_

---

- [ ] 15. Implement News_Filter module
  - Write `include/filters/NewsFilter.mqh`
  - Load event list from local CSV file (configurable path)
  - Event record fields: event name, UTC timestamp, impact level (Low/Medium/High)
  - Apply only to events at or above `MinImpactLevel` (default High)
  - Pre-event blocking: `[event_utc - PreEventMinutes, event_utc]`
  - Post-event blocking: `[event_utc, event_utc + PostEventMinutes]`
  - Overlapping windows → union of all blocking windows applies
  - Events beyond `PostEventMinutes` in the past → cleaned from active list
  - `NewsProtectionMode`: BLOCK / WARN / DISABLED
  - WARN mode → return WARN (not BLOCKED); Entry_Confirmation_Engine logs but still approves
  - DISABLED mode → always return ALLOWED
  - Stale list (older than `MaxListAgeHours`, default 24) → log WARNING → apply `StaleFallback`
    (BLOCK or ALLOW, default BLOCK)
  - Output: `FilterStatus` (ALLOWED / BLOCKED / WARN)
  - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7_

  - [ ] 15.1 Implement NewsFilter.mqh — event loading, window calculation, mode handling
    - CSV loader for news events file; stale-check logic; union of overlapping windows
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.7_

  - [ ]* 15.2 Write property test for news filter blocking windows (Property 14)
    - **Property 14: News filter blocking windows cover all qualifying events**
    - **Validates: Requirements 8.3, 8.4**
    - Generate arbitrary (timestamp, event_list, pre_minutes, post_minutes, min_impact);
      assert BLOCKED iff timestamp within [event_utc − pre, event_utc + post] for ≥1 qualifying event

  - [ ]* 15.3 Edge-case and example tests for News_Filter
    - WARN mode → returns WARN (not BLOCKED)
    - DISABLED mode → returns ALLOWED regardless of events
    - Stale list → StaleFallback applied
    - Overlapping windows → union applied
    - _Requirements: 8.5, 8.6, 8.7_

  - [ ] 15.4 Create `config/news_events.csv` template with header row and example entries
    - _Requirements: 8.1_

  - [ ] 15.5 Implement Python News_Filter module
    - Write `python-research/strategy/news_filter.py`
    - _Requirements: 16.1_

---

- [ ] 16. Implement Spread_Filter module
  - Write `include/filters/SpreadFilter.mqh`
  - Applied only at new order submission; never at modification or closure
  - No caching: every call reads fresh from `SymbolInfoDouble` (ASK and BID)
  - Spread calculation: `(Ask - Bid) / Point` compared against `MaxSpreadPoints` (default 30)
  - `MaxSpreadPoints` valid range: 10–200 points
  - SymbolInfo unavailable → BLOCKED + log ERROR
  - Output: `FilterStatus` (ALLOWED / BLOCKED)
  - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_

  - [ ] 16.1 Implement SpreadFilter.mqh
    - Live read of ASK/BID per call; no caching
    - _Requirements: 7.1, 7.2, 7.4, 7.5_

  - [ ]* 16.2 Write property test for spread filter independence (Property 13)
    - **Property 13: Spread filter independence (no cross-call caching)**
    - **Validates: Requirements 7.2, 7.4**
    - Call filter twice with different spread values; assert second result reflects only second spread;
      assert BLOCKED iff spread > threshold

  - [ ]* 16.3 Edge-case tests for Spread_Filter
    - SymbolInfo unavailable → BLOCKED + ERROR
    - Spread exactly at threshold → ALLOWED (not BLOCKED — threshold is exclusive)
    - _Requirements: 7.6_

  - [ ] 16.4 Implement Python Spread_Filter module
    - Write `python-research/strategy/spread_filter.py`
    - _Requirements: 16.1_

- [ ] 17. Phase 4 Checkpoint
  - All filter property tests pass (Properties 12, 13, 14)
  - Session / News / Spread filters integrated into test pipeline
  - Ensure all tests pass, ask the user if questions arise.

---

### Phase 5: Entry Confirmation Engine

**Objective:** Implement the signal aggregation engine that combines all upstream analysis into a
validated TradeSignal or null. This module contains no position sizing or order logic.

> ✅ **BLOCKER-1 RESOLVED:** `entry_price` in TradeSignal = live Ask (BUY) or Bid (SELL) read from
> SymbolInfoDouble at signal generation time. `signal_reference_price` = triggering candle close,
> for audit/logging only. The Order_Executor re-reads Ask/Bid again immediately before each
> OrderSend call. The two prices are always logged together for slippage audit.
>
> ✅ **BLOCKER-2 RESOLVED:** TP = nearest Active opposing Liquidity_Pool satisfying MinRR.
> BOS/CHOCH levels are NOT used as TP targets. If no Active opposing pool satisfies MinRR,
> signal is rejected with NO_VALID_TP. No trade is forced with substandard R:R.

---

- [ ] 18. Implement Entry_Confirmation_Engine module
  - Write `include/engine/EntryConfirmationEngine.mqh`
  - Aggregate AnalysisStatus from all analysis engines and filters
  - All 10 entry conditions must be simultaneously satisfied (design §2.10)
  - Any UNKNOWN or BLOCKED from any dependency → block signal + log source
  - TradeSignal construction on approval (BLOCKER-1 and BLOCKER-2 resolved):
    - `entry_price`: live Ask (BUY) or Bid (SELL) from `SymbolInfoDouble` at signal generation time
    - `signal_reference_price`: close of the confirming candle (bar index 1 on 5M) — audit only
    - `stop_loss_price`: below sweep low (BUY) / above sweep high (SELL), validated ≥ ATR min SL distance; STATIC for position lifetime
    - `take_profit_price`: nearest Active opposing Liquidity_Pool satisfying `|pool − entry| / |entry − SL| ≥ MinRR`; if none exists → reject with NO_VALID_TP
    - BOS/CHOCH levels are NOT TP candidates
    - All required fields must be non-zero; any zero field → discard + log invalid field name
  - Signal not held between ticks; generated and acted on (or discarded) in same tick
  - Regime = Ranging + `RangingModeEnabled = false` → null signal (hard block)
  - WARN from News_Filter: configurable whether WARN blocks or not
  - _Requirements: 3.5, 3.6, 4.1, 4.2, 4.3, 4.4, 5.1, 6.2, 6.3, 8.5, 8.6, 13.2, 13.3, 18.1–18.7_

  - [ ] 18.1 Implement signal aggregation and blocking logic
    - Check all 10 conditions in order; log first failing condition with source module name
    - _Requirements: 3.5, 3.6, 5.5, 6.2, 8.5, 8.6_

  - [ ] 18.2 Implement TradeSignal construction (BLOCKER-1 + BLOCKER-2 resolved)
    - `entry_price` = live Ask/Bid; `signal_reference_price` = candle close
    - SL placement vs ATR floor; static SL confirmed
    - TP algorithm: collect opposing Active pools → filter by MinRR → select nearest → reject NO_VALID_TP if empty
    - Log selected pool, R:R, next-nearest rejected pool (if any)
    - _Requirements: 18.1, 18.2, 18.3, 18.4, 18.5, 18.6, 18.7_

  - [ ]* 18.3 Write property test for ranging regime block (Property 8)
    - **Property 8: Ranging regime blocks all entries (unless Ranging_Mode_Enabled)**
    - **Validates: Requirements 3.5, 3.6**
    - For any AnalysisStatus snapshot with Ranging 4H regime and RangingModeEnabled=false;
      assert Entry_Confirmation_Engine returns null regardless of other inputs

  - [ ]* 18.4 Write property test for no signal on any BLOCKED input
    - Property: TradeSignal = null for any input combination where at least one source returns BLOCKED
    - **Validates: Requirements 6.3, 8.6**

  - [ ]* 18.5 Write property test for TradeSignal field completeness on approval
    - Property: when all conditions pass, all TradeSignal fields are non-zero and internally consistent
    - **Validates: Requirements 13.3**

  - [ ]* 18.6 Write property test: TP is always nearest qualifying opposing pool (Property 28)
    - **Property 28: TP = nearest qualifying Active opposing Liquidity_Pool**
    - Generate pool sets with various distances; assert selected TP is the nearest satisfying MinRR
    - Assert NO_VALID_TP when no pool satisfies MinRR
    - **Validates: Requirements 18.1–18.6**

  - [ ]* 18.7 Write property test: entry_price ≠ signal_reference_price (Property 27)
    - **Property 27: Execution entry price is always live Ask/Bid, never candle close**
    - Assert entry_price comes from SymbolInfoDouble; assert signal_reference_price = bar[1].close
    - **Validates: Requirements 10.11, 10.12**

  - [ ] 18.6 Implement Python Entry_Engine module
    - Write `python-research/strategy/entry_engine.py`
    - _Requirements: 16.1_

- [ ] 19. Phase 5 Checkpoint
  - Full pipeline test: OHLCV arrays → analysis → filters → Entry_Confirmation_Engine → TradeSignal
  - BLOCKER-1 and BLOCKER-2 resolved and documented in implementation comments
  - Ensure all tests pass, ask the user if questions arise.

---

### Phase 6: Risk Engine

**Objective:** Implement the Risk_Manager — the sole module responsible for position sizing and
all drawdown/limit enforcement. Completely independent of strategy logic.

---

- [ ] 20. Implement Risk_Manager module
  - Write `include/risk/RiskManager.mqh`
  - Stateless computation; reads persistent state from State_Manager
  - Position sizing formula (exact):
    ```
    RiskAmount = FloatingEquity × (RiskPerTradePct / 100)
    SLDistancePips = |EntryPrice - StopLossPrice| / SymbolPoint
    PipValue = (SymbolPoint × ContractSize) / EntryPrice
    LotSize = RiskAmount / (SLDistancePips × PipValue × ContractSize)
    LotSize = RoundDown(LotSize / LotStep) × LotStep
    LotSize = Clamp(LotSize, MinLot, MaxLotSize)
    ```
  - Validation sequence (in order, first failure causes rejection):
    1. TradeSignal field validation (non-zero entry, SL, TP, valid direction)
    2. R:R check: `|TP - Entry| / |Entry - SL| ≥ MinRR`
    3. Daily drawdown limit not reached
    4. Total drawdown circuit breaker not triggered
    5. Max open trades not exceeded
    6. Combined risk ≤ `RiskPerTradePct × MaxOpenTrades`
    7. Free margin ≥ `MinFreeMarginPct × RequiredMargin`
    8. LotSize after rounding > 0
  - EntryPrice = StopLossPrice → SL distance = 0 → rejection (prevents division by zero)
  - LotSize rounds to 0 → rejection with pre-rounding value logged
  - Floating equity at exact threshold → breaker fires (≥ comparison, not >)
  - No martingale, no grid, no averaging down (enforced by stateless formula)
  - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8, 9.9, 9.10, 9.11, 9.12,
    15.1, 15.2, 15.3, 15.4, 17.1, 17.6, 17.7_

  - [ ] 20.1 Implement position sizing formula
    - Exact formula as specified; RoundDown to LotStep; Clamp to [MinLot, MaxLotSize]
    - _Requirements: 9.1, 9.2, 9.8_

  - [ ]* 20.2 Write property test for position sizing formula correctness (Property 15)
    - **Property 15: Position sizing formula correctness**
    - **Validates: Requirements 9.1, 9.2, 9.8**
    - Generate arbitrary (equity, entry, SL, risk_pct, symbol_props) tuples;
      assert computed lot size matches formula exactly

  - [ ]* 20.3 Write property test for lot size LotStep validity and bounds (Property 16)
    - **Property 16: Lot size is always a valid multiple of LotStep within bounds**
    - **Validates: Requirements 9.8, 9.12**
    - Assert result is exact multiple of LotStep; within [MinLot, MaxLotSize] if > 0;
      reject with zero-size if formula produces value below MinLot after rounding

  - [ ] 20.4 Implement validation sequence (all 8 checks)
    - TradeSignal validation, R:R check, drawdown checks, max trades, combined risk, margin, lot > 0
    - Each check produces RejectionResult with `unmet_criterion` field
    - _Requirements: 9.3, 9.4, 9.5, 9.6, 9.7, 9.9, 9.10, 9.11, 9.12_

  - [ ]* 20.5 Write property test for R:R enforcement symmetry (Property 17)
    - **Property 17: R:R enforcement is symmetric**
    - **Validates: Requirements 9.7**
    - For any (entry, SL, TP): approves iff |TP-Entry|/|Entry-SL| ≥ MinRR;
      rejection includes computed and required values

  - [ ]* 20.6 Write property test for drawdown circuit breaker timing (Property 18)
    - **Property 18: Drawdown circuit breakers fire at or before threshold**
    - **Validates: Requirements 9.4, 9.5, 9.6, 17.1**
    - Simulate loss sequences; assert breaker fires exactly when accumulated loss first meets threshold
      (not before, not after); test both daily and total breakers

  - [ ]* 20.7 Write property test for combined position risk limit (Property 19)
    - **Property 19: Combined position risk never exceeds the multi-trade limit**
    - **Validates: Requirements 9.3, 9.11**
    - For any set of open positions + proposed new trade; assert rejection if combined risk >
      RiskPerTradePct × MaxOpenTrades

  - [ ]* 20.8 Write property test for margin threshold block (Property 26)
    - **Property 26: Margin threshold blocks entries below the floor**
    - **Validates: Requirements 17.7**
    - For any (free_margin, required_margin): blocked iff free_margin < MinFreeMarginPct × required

  - [ ]* 20.9 Edge-case tests for Risk_Manager
    - LotSize rounds to zero → rejection with pre-rounding value logged
    - EntryPrice = StopLossPrice → SL distance 0 → rejection
    - Equity exactly at threshold → breaker fires (inclusive ≥)
    - _Requirements: 9.10, 9.12_

  - [ ] 20.10 Implement Python Risk_Manager module
    - Write `python-research/risk/risk_manager.py` — identical logic to MQL5
    - _Requirements: 16.1_

- [ ] 21. Phase 6 Checkpoint
  - Full pipeline integration test: OHLCV → analysis → Entry_Confirmation_Engine → Risk_Manager → TradeOrder
  - All Properties 15–19 and 26 pass
  - Ensure all tests pass, ask the user if questions arise.

---

### Phase 7: Execution Engine

**Objective:** Implement the Order_Executor — the sole module that makes live broker calls.
This module is the only caller of `OrderSend`, `OrderModify`, `OrderClose`.

> ✅ **FREEZE-LEVEL RESOLVED:** When a position is within `SYMBOL_TRADE_FREEZE_LEVEL` of the current price, the Order_Executor SHALL NOT attempt the modification. It SHALL write a structured WARN log entry with all required fields (symbol, ticket, operation, current price, freeze-level value, required distance, reason="FREEZE_LEVEL_ACTIVE", UTC timestamp). No workaround trade is opened. If the skipped operation is a missing mandatory SL re-attachment and the skip persists for `MaxFreezeSkips` (default 5) consecutive cycles, the unprotected position is force-closed per Requirement 17.5 and a CRITICAL is logged.

---

- [ ] 22. Implement Order_Executor module
  - Write `include/execution/OrderExecutor.mqh`
  - Only module that calls `OrderSend`, `OrderModify`, `OrderClose`
  - Magic_Number on all orders
  - Submission flow (10 steps from design §2.12):
    1. SpreadFilter check → BLOCKED → cancel + log, no retry
    2. Validate SL distance ≥ broker stop level
    3. Validate all TradeOrder fields non-zero
    4. Submit via OrderSend
    5. Verify filled SL and TP match submitted values (within stop level tolerance)
    6. Mismatch → one correction via OrderModify
    7. Correction fails → log CRITICAL, halt management for that ticket
    8. Non-fatal error → retry up to `MaxRetries` with `RetryDelayMs` delay
    9. Fatal error → log with full order details, no retry
    10. Update State_Manager with new position record
  - Requotes treated as non-fatal (retried)
  - SL/TP monitoring every tick: verify SL present for each EA position
  - Missing SL → re-attach via OrderModify immediately → failure → close position → log CRITICAL
  - Freeze level: if position within freeze level of price, skip modification (not error)
  - Partial fills: cancel unfilled portion + log partial fill
  - Active position list rebuilt from MT5 order book on restart
  - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9, 10.10,
    13.5, 17.4, 17.5_

  - [ ] 22.1 Implement OrderExecutor.mqh submission flow (all 10 steps)
    - Magic_Number enforcement; Spread check; field validation; OrderSend; fill verification
    - _Requirements: 10.1, 10.2, 10.3, 10.6, 10.8, 10.9_

  - [ ]* 22.2 Write property test for SL/TP present on every submitted order (Property 20)
    - **Property 20: Every submitted order has SL and TP attached**
    - **Validates: Requirements 10.1, 10.2**
    - For any TradeOrder; assert submitted MT5 order has stop_loss ≠ 0 and take_profit ≠ 0

  - [ ]* 22.3 Write property test for post-fill SL/TP correction trigger (Property 21)
    - **Property 21: Post-fill SL/TP verification triggers correction on deviation**
    - **Validates: Requirements 10.4, 10.5**
    - For fill result with SL/TP deviation > broker stop level tolerance: assert exactly one
      OrderModify attempted; for deviation within tolerance: assert no correction attempted

  - [ ] 22.4 Implement SL/TP per-tick monitoring and re-attachment logic
    - Scan all open EA positions on every tick cycle; re-attach missing SL; force-close on failure
    - Freeze-level detection: before each OrderModify call, check whether position is within `freeze_level_points × point` of current price; if so, skip and write WARN log with all 7 required fields (symbol, ticket, operation, current price, freeze-level value, required distance, reason="FREEZE_LEVEL_ACTIVE", UTC timestamp)
    - Track consecutive freeze-level skips per ticket; if skip count reaches `MaxFreezeSkips` (default 5) for a position missing its mandatory SL, force-close position and log CRITICAL
    - _Requirements: 10.13, 10.14, 17.4, 17.5_

  - [ ]* 22.5 Example tests for Order_Executor (mock MT5)
    - Non-fatal error retry sequence exhausts retries then cancels
    - SL missing triggers re-attach attempt; re-attach failure triggers force-close
    - SpreadFilter BLOCKED cancels submission (no retry until new signal)
    - _Requirements: 10.3, 10.4, 10.7_

- [ ] 23. Phase 7 Checkpoint
  - Mock MT5 integration: full submission, fill verification, retry, SL monitoring cycle tested
  - All Properties 20–21 pass
  - Ensure all tests pass, ask the user if questions arise.

---

### Phase 8: Position Management

**Objective:** Wire the full MQL5 EA event loop — OnInit, OnTick, OnTimer, OnDeinit — and
implement daily drawdown reset, consecutive loss tracking, and cooldown management.

> ✅ **BLOCKER-3 RESOLVED:** V1 uses **static SL only**. The SL is calculated once before order
> submission and is never moved, trailed, or used for break-even. No partial TP. No averaging.
> This decision is documented as a design comment in `xauusd_ea.mq5` and enforced by
> Property 29 (SL is static for the lifetime of each position).

---

- [ ] 24. Implement main EA file event handlers
  - Write `xauusd_ea.mq5` with `OnInit`, `OnTick`, `OnTimer`, `OnDeinit` handlers
  - Add explicit V1 design decision comment block at top of file documenting static SL policy
  - `OnInit`: Config validation → SymbolProperties → State restore → position rebuild → SL re-attach
  - `OnTick`: new-candle detection per timeframe → run analysis pipeline → check filters → signal → risk → execute
  - `OnTimer`: SL/TP monitoring cycle; connection status check; State_Manager safe mode polls
  - `OnDeinit`: flush logger; clean up resources
  - EA aborts with INIT_FAILED on any hard init failure
  - _Requirements: 11.1, 11.2, 14.1, 14.2, 17.1, 17.2, 17.3_

  - [ ] 24.1 Implement OnInit sequence
    - In order: Config → SymbolProperties → StateManager → PositionRebuild → SL reattach
    - INIT_FAILED propagation on any step failure
    - _Requirements: 11.1, 11.2, 14.2_

  - [ ] 24.2 Implement OnTick pipeline
    - New-candle detection → analysis → filter → signal → risk → execute
    - _Requirements: 1.6_

  - [ ] 24.3 Implement OnTimer cycle
    - SL/TP monitoring; safe-mode polls; connection status handling
    - _Requirements: 11.7, 17.4_

- [ ] 25. Implement daily reset and consecutive-loss cooldown
  - Daily reset at midnight UTC (or first tick after missed midnight)
  - Reset daily drawdown accumulator; record new day-open equity
  - Consecutive loss counter: incremented on each losing trade close
  - When consecutive losses ≥ `MaxConsecutiveLosses` → enter cooldown for `CooldownHours`
  - Cooldown start time persisted to state file (survives restart)
  - Cooldown auto-exits after `CooldownHours` elapsed
  - _Requirements: 17.2, 17.6_

  - [ ] 25.1 Implement daily reset mechanism in State_Manager
    - Midnight detection; daily drawdown reset; day-open equity recording
    - _Requirements: 17.2_

  - [ ] 25.2 Implement consecutive loss counter and cooldown logic
    - Increment on losing trade; persist cooldown_start_utc; auto-exit on expiry
    - _Requirements: 17.6_

  - [ ] 25.3 Implement total drawdown circuit breaker
    - Compare floating equity to `total_drawdown_ref_equity` on every tick
    - Trigger: close all positions + disable EA + persist `circuit_breaker_triggered = true`
    - Require manual re-enablement (no auto-restart)
    - _Requirements: 9.6, 17.1, 17.3_

- [ ] 26. Phase 8 Checkpoint
  - End-to-end MT5 Strategy Tester run with representative OHLCV data
  - Daily reset, cooldown, and circuit breaker verified in simulated environment
  - BLOCKER-3 resolved and documented
  - Ensure all tests pass, ask the user if questions arise.

---

### Phase 9: Persistence and Resilience

**Objective:** Harden the state persistence layer, validate restart recovery, and confirm all
safety controls survive terminal interruption.

> ✅ **BLOCKER-4 RESOLVED:** State file format = native MQL5 plain-text KEY=VALUE with CRC32 checksum.
> Pool registry stored in a `[POOL_REGISTRY]` section with one CSV row per pool.
> No external JSON library. SAFE_MODE entered on any checksum, schema, symbol, or account mismatch.
> Full format specification is in the design document (§2.13 State_Manager).

---

- [ ] 27. Implement and validate state file serialisation with pool registry
  - Extend `StateManager.mqh` to implement the full state file format:
    - Plain-text KEY=VALUE header fields
    - `[POOL_REGISTRY]` CSV section (one pool per line)
    - `[END_POOL_REGISTRY]` terminator
    - `CHECKSUM=` CRC32 hex as final line
    - Atomic write: `.tmp` file → rename to final path
    - SAFE_MODE on: CRC32 mismatch, missing mandatory field, symbol mismatch, account suffix mismatch, schema version incompatibility
  - _Requirements: 19.1–19.10_

  - [ ] 27.1 Implement state file writer (key-value + pool registry + CRC32)
    - Full format per Requirement 19 and design §2.13
    - _Requirements: 19.1, 19.2, 19.3, 19.6, 19.7_

  - [ ] 27.2 Implement state file reader with integrity validation and SAFE_MODE
    - CRC32 verification; schema migration; symbol/account cross-check; `.tmp` fallback
    - _Requirements: 19.3, 19.4, 19.5, 19.8, 19.9, 19.10_

  - [ ]* 27.3 Write property test: CRC32 detects any single-character mutation (Property 30)
    - **Property 30: State file CRC32 checksum detects corruption**
    - Mutate each byte of every field above CHECKSUM; assert CRC32 mismatch detected → SAFE_MODE
    - **Validates: Requirements 19.3, 19.4**

  - [ ]* 27.4 Integration test: state persistence with pool registry
    - Create pool registry with N pools; serialise; deserialise; assert pool states match exactly
    - _Requirements: 19.6_

  - [ ]* 27.5 Edge-case tests: SAFE_MODE trigger conditions
    - Symbol mismatch → SAFE_MODE
    - Account suffix mismatch → SAFE_MODE
    - Unknown SCHEMA version (higher than current) → SAFE_MODE
    - Missing mandatory header field → SAFE_MODE
    - `.tmp` file present at init: valid → use `.tmp`; invalid → fall back to main file
    - _Requirements: 19.4, 19.5, 19.8, 19.10_

- [ ] 28. Implement and validate restart recovery integration — including SAFE_MODE paths (CONFLICT-1)
  - Simulate: EA running with 2 open positions → terminal kill → restart
  - Verify: positions reconstructed from MT5 order book; daily drawdown restored; cooldown intact
  - Verify: open positions missing SL → re-attachment attempted; failure → force-close + CRITICAL log
  - Verify SAFE_MODE paths: corrupt/missing/mismatched state → SAFE_MODE → positions reconciled → manual re-enable required
  - _Requirements: 11.1, 11.2, 11.3, 11.5, 11.6, 11.8, 11.9, 17.5, 19.4_

  - [ ] 28.1 Integration test: normal restart recovery sequence
    - Script simulating terminal restart with open positions in various states and valid state file
    - Verify positions reconstructed, drawdown restored, cooldown intact
    - _Requirements: 11.1, 11.2, 11.5_

  - [ ]* 28.2 Integration test: restart with missing SL
    - Open position exists in MT5 order book without SL; verify re-attachment attempted;
      simulate re-attachment failure → force-close triggered
    - _Requirements: 11.2, 17.5_

  - [ ]* 28.3 Integration test: circuit breaker survives restart
    - Persist `circuit_breaker_triggered = true`; restart EA; verify INIT_FAILED returned
    - _Requirements: 17.3_

  - [ ]* 28.4 Integration test: SAFE_MODE on corrupt state file (CONFLICT-1)
    - Write state file with invalid checksum; restart EA; verify SAFE_MODE entered, new entries blocked, CRITICAL logged, sentinel file written
    - Verify open positions are reconciled from MT5 order book and SLs verified
    - Verify EA does NOT silently reset accumulators and resume trading
    - _Requirements: 11.6, 19.4_

  - [ ]* 28.5 Integration test: SAFE_MODE on missing state file when continuity required (CONFLICT-1)
    - Delete state file; restart EA mid-day with open positions; verify SAFE_MODE entered (not warn-and-reset)
    - Verify positions reconciled, CRITICAL logged, manual re-enable required
    - _Requirements: 11.6, 19.4_

  - [ ]* 28.6 Integration test: SAFE_MODE on symbol/account mismatch (CONFLICT-1)
    - Write state file with mismatched SYMBOL field; restart EA; verify SAFE_MODE entered
    - _Requirements: 11.6, 19.8_

  - [ ]* 28.7 Integration test: SAFE_MODE on unsupported state schema version (CONFLICT-1)
    - Write state file with SCHEMA version higher than current EA constant; verify SAFE_MODE entered
    - _Requirements: 11.6, 19.5_

  - [ ]* 28.8 Integration test: successful state reconstruction in SAFE_MODE (CONFLICT-1)
    - Simulate corrupt state but live MT5 order book has sufficient data for reconstruction
    - Verify reconstructed values logged at INFO level
    - Verify EA remains in SAFE_MODE until manual re-enable
    - _Requirements: 11.8_

  - [ ]* 28.9 Integration test: failed state reconstruction in SAFE_MODE (CONFLICT-1)
    - Simulate corrupt state and insufficient MT5 history (e.g., EA offline for multiple days)
    - Verify WARNING logged identifying unresolvable fields
    - Verify EA remains in SAFE_MODE
    - _Requirements: 11.9_

- [ ] 29. Phase 9 Checkpoint
  - All restart scenarios tested and passing
  - Pool registry round-trip verified
  - BLOCKER-4 resolved and implemented
  - Ensure all tests pass, ask the user if questions arise.

---

### Phase 10: Logging and Monitoring

**Objective:** Verify the Logger produces correct structured output for all event types, that
masking works correctly for any account number length, and that all required fields are present
per event type.

---

- [ ] 30. Implement and validate full Logger coverage
  - Confirm all 11 event types produce correct log entries:
    `signal_generated`, `signal_approved`, `signal_rejected`, `order_submitted`,
    `order_filled`, `order_rejected`, `order_modified`, `order_closed`,
    `risk_limit_triggered`, `filter_blocked`, `ea_state_change`
  - Trade-related events must include: floating equity, balance, open drawdown %
  - CRITICAL events: log at CRITICAL level + State_Manager disables EA in same cycle
  - Log-level filtering: entries below configured minimum level suppressed
  - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6_

  - [ ] 30.1 Verify all 11 event types produce structurally correct log entries
    - Write test assertions for each event type against Logger output
    - _Requirements: 12.1, 12.2_

  - [ ]* 30.2 Write property test for account number masking (Property 24) — Python
    - **Property 24: Log masking for account numbers (Python mirror)**
    - **Validates: Requirements 12.6**
    - Same as task 2.2 but for Python Logger; Hypothesis with arbitrary digit strings

  - [ ]* 30.3 Write property test for log field completeness per event type (Property 25) — Python
    - **Property 25: Structured log entries contain all required fields per event type (Python mirror)**
    - **Validates: Requirements 12.1, 12.2, 12.3**

  - [ ]* 30.4 Example test: CRITICAL event triggers EA disable in same cycle
    - Simulate total drawdown limit reached; assert CRITICAL log written + EA state = DISABLED
    - _Requirements: 12.4_

- [ ] 31. Phase 10 Checkpoint
  - Logger validated for all 11 event types
  - Account masking verified for numbers of length 4–20
  - Ensure all tests pass, ask the user if questions arise.

---

### Phase 11: Property-Based Testing — All 26 Correctness Properties

**Objective:** Each of the 26 correctness properties defined in the design document has a
dedicated automated property-based test. This phase ensures every property has been verified
with at least 100 generated examples (1000 for critical risk properties 15–19).

All 26 property tests are implemented in Python using Hypothesis. Corresponding MQL5 unit test
scripts are cross-referenced. Each test is tagged:
`# Feature: xauusd-mt5-ea, Property N: <property_text>`

---

- [ ] 32. Property tests for data layer (Properties 1–2)

  - [ ]* 32.1 Property 1: Confirmed-candle enforcement
    - `tests/unit/test_data_feed.py` — mutate bar[0]; assert module outputs unchanged
    - **Property 1** | **Validates: Req 1.1, 1.6, 2.7, 4.5, 15.5**

  - [ ]* 32.2 Property 2: Swing side-count invariant
    - `tests/unit/test_market_structure.py` — confirm no swing within last N bars
    - **Property 2** | **Validates: Req 1.1, 1.2**

---

- [ ] 33. Property tests for Market_Structure_Analyzer (Properties 3–4)

  - [ ]* 33.1 Property 3: Regime classification correctness
    - `tests/unit/test_market_structure.py`
    - Generate swing sequences; verify Bullish/Bearish/Ranging classification
    - **Property 3** | **Validates: Req 1.3, 3.1, 3.2, 3.3, 3.4**

  - [ ]* 33.2 Property 4: BOS fires at exactly the correct candle
    - `tests/unit/test_market_structure.py`
    - Plant known swing level; assert BOS at exact bar
    - **Property 4** | **Validates: Req 1.4, 1.5**

---

- [ ] 34. Property tests for Liquidity_Detector (Properties 5–7)

  - [ ]* 34.1 Property 5: Liquidity sweep round-trip
    - `tests/unit/test_liquidity.py`
    - **Property 5** | **Validates: Req 2.2, 2.4**

  - [ ]* 34.2 Property 6: Pool lifecycle state machine validity
    - `tests/unit/test_liquidity.py`
    - **Property 6** | **Validates: Req 2.3, 2.4**

  - [ ]* 34.3 Property 7: MaxActivePools invariant
    - `tests/unit/test_liquidity.py`
    - **Property 7** | **Validates: Req 2.5**

---

- [ ] 35. Property test for Entry_Confirmation_Engine (Property 8)

  - [ ]* 35.1 Property 8: Ranging regime blocks all entries
    - `tests/unit/test_entry_engine.py`
    - **Property 8** | **Validates: Req 3.5, 3.6**

---

- [ ] 36. Property test for Momentum_Engine (Property 9)

  - [ ]* 36.1 Property 9: Momentum approval symmetry
    - `tests/unit/test_momentum.py`
    - **Property 9** | **Validates: Req 4.1, 4.2, 4.3**

---

- [ ] 37. Property tests for ATR_Volatility_Engine (Properties 10–11)

  - [ ]* 37.1 Property 10: ATR filter at all threshold boundaries
    - `tests/unit/test_atr_engine.py` — minimum 1000 iterations
    - **Property 10** | **Validates: Req 5.1, 5.2, 5.3**

  - [ ]* 37.2 Property 11: SL distance ATR-broker floor
    - `tests/unit/test_atr_engine.py` — minimum 1000 iterations
    - **Property 11** | **Validates: Req 5.4, 9.1, 10.8**

---

- [ ] 38. Property test for Session_Filter (Property 12)

  - [ ]* 38.1 Property 12: Session filter correctness across all timestamps
    - `tests/unit/test_session_filter.py`
    - **Property 12** | **Validates: Req 6.1, 6.2, 6.3, 6.4**

---

- [ ] 39. Property test for Spread_Filter (Property 13)

  - [ ]* 39.1 Property 13: Spread filter independence
    - `tests/unit/test_spread_filter.py`
    - **Property 13** | **Validates: Req 7.2, 7.4**

---

- [ ] 40. Property test for News_Filter (Property 14)

  - [ ]* 40.1 Property 14: News filter blocking windows
    - `tests/unit/test_news_filter.py`
    - **Property 14** | **Validates: Req 8.3, 8.4**

---

- [ ] 41. Property tests for Risk_Manager (Properties 15–19) — 1000 iterations each

  - [ ]* 41.1 Property 15: Position sizing formula correctness
    - `tests/unit/test_risk_manager.py` — minimum 1000 iterations
    - **Property 15** | **Validates: Req 9.1, 9.2, 9.8**

  - [ ]* 41.2 Property 16: Lot size LotStep validity
    - `tests/unit/test_risk_manager.py` — minimum 1000 iterations
    - **Property 16** | **Validates: Req 9.8, 9.12**

  - [ ]* 41.3 Property 17: R:R enforcement symmetry
    - `tests/unit/test_risk_manager.py` — minimum 1000 iterations
    - **Property 17** | **Validates: Req 9.7**

  - [ ]* 41.4 Property 18: Drawdown circuit breaker timing
    - `tests/unit/test_risk_manager.py` — minimum 1000 iterations
    - **Property 18** | **Validates: Req 9.4, 9.5, 9.6, 17.1**

  - [ ]* 41.5 Property 19: Combined position risk limit
    - `tests/unit/test_risk_manager.py` — minimum 1000 iterations
    - **Property 19** | **Validates: Req 9.3, 9.11**

---

- [ ] 42. Property tests for Order_Executor (Properties 20–21)

  - [ ]* 42.1 Property 20: Every submitted order has SL and TP
    - `tests/unit/test_order_executor.py` (mock MT5)
    - **Property 20** | **Validates: Req 10.1, 10.2**

  - [ ]* 42.2 Property 21: Post-fill SL/TP correction trigger
    - `tests/unit/test_order_executor.py` (mock MT5)
    - **Property 21** | **Validates: Req 10.4, 10.5**

---

- [ ] 43. Property tests for State_Manager (Properties 22–23)

  - [ ]* 43.1 Property 22: State persistence round-trip
    - `tests/unit/test_state_manager.py` — minimum 1000 iterations
    - **Property 22** | **Validates: Req 11.4, 11.5, 17.6**

  - [ ]* 43.2 Property 23: Drawdown restoration on same-day restart
    - `tests/unit/test_state_manager.py` — minimum 1000 iterations
    - **Property 23** | **Validates: Req 11.4, 11.5, 17.2**

---

- [ ] 44. Property tests for Logger (Properties 24–25)

  - [ ]* 44.1 Property 24: Log masking for account numbers
    - `tests/unit/test_logger.py`
    - **Property 24** | **Validates: Req 12.6**

  - [ ]* 44.2 Property 25: Structured log field completeness
    - `tests/unit/test_logger.py`
    - **Property 25** | **Validates: Req 12.1, 12.2, 12.3**

---

- [ ] 45. Property test for Risk_Manager margin guard (Property 26)

  - [ ]* 45.1 Property 26: Margin threshold blocks entries below floor
    - `tests/unit/test_risk_manager.py`
    - **Property 26** | **Validates: Req 17.7**

---

- [ ] 46. Property tests for blocker resolutions (Properties 27–31)

  - [ ]* 46.1 Property 27: Execution entry price is always live Ask/Bid — never candle close
    - `tests/unit/test_entry_engine.py`
    - Assert `entry_price` ≠ `signal_reference_price` for any non-zero spread
    - Assert `entry_price` reflects `SymbolInfoDouble(ASK/BID)` at signal time
    - **Property 27** | **Validates: Req 10.11, 10.12**

  - [ ]* 46.2 Property 28: TP is always nearest qualifying Active opposing Liquidity_Pool
    - `tests/unit/test_entry_engine.py`
    - Generate pool sets with various distances and MinRR values
    - Assert selected TP = nearest pool where R:R ≥ MinRR
    - Assert NO_VALID_TP when no qualifying pool exists
    - Assert BOS levels are never selected as TP
    - Minimum 1000 iterations
    - **Property 28** | **Validates: Req 18.1–18.6**

  - [ ]* 46.3 Property 29: Stop-loss is static for the lifetime of each position
    - `tests/unit/test_order_executor.py` (mock MT5)
    - Open position; run 100 monitoring cycles; assert SL level unchanged
    - Assert no `OrderModify` SL-change call is made during normal management
    - **Property 29** | **Validates: Req 18.8, 18.13**

  - [ ]* 46.4 Property 30: State file CRC32 detects any single-character mutation
    - `tests/unit/test_state_manager.py`
    - Generate valid state file; mutate each byte in fields above CHECKSUM line
    - Assert CRC32 mismatch detected → SAFE_MODE triggered for every mutation
    - Minimum 1000 iterations
    - **Property 30** | **Validates: Req 19.3, 19.4**

  - [ ]* 46.5 Property 31: Backtest slippage result sets are independent and correctly ordered
    - `tests/unit/test_backtest_engine.py`
    - Run Base, Conservative, Stress on same data; assert Base ≥ Conservative ≥ Stress in net return
    - Assert no cross-contamination between result set outputs
    - **Property 31** | **Validates: Req 20.1, 20.3, 20.4, 20.5**

  - [ ]* 46.6 Property 32: Freeze-level skip produces structured WARN log and never bypasses broker restriction
    - `tests/unit/test_order_executor.py` (mock MT5)
    - Simulate position within freeze-level distance of current price; trigger SL re-attachment attempt
    - Assert: `OrderModify` is NOT called
    - Assert: WARN log entry written with all 7 required fields (symbol, ticket, operation, current price, freeze-level value, required distance, reason="FREEZE_LEVEL_ACTIVE", UTC timestamp)
    - Assert: no new trade or workaround order is opened
    - Simulate `MaxFreezeSkips` consecutive freeze-level skips on a position missing mandatory SL
    - Assert: position is force-closed after MaxFreezeSkips and CRITICAL is logged
    - Simulate position outside freeze-level distance; assert OrderModify IS called (normal path unaffected)
    - **Property 32** | **Validates: Req 10.13, 10.14**

---

- [ ] 47. Phase 11 Checkpoint — All 32 Properties Green
  - All 32 property-based tests pass with required iteration counts
  - No property test has any suppressed or xfail condition
  - No-look-ahead canary test added to each analysis module test
  - Ensure all tests pass, ask the user if questions arise.

---

### Phase 12: Python Backtesting Environment

**Objective:** Implement the full Python research environment with confirmed-candle enforcing
backtest loop, trade log writer, walk-forward validator, and sensitivity analysis tool.

> ✅ **BLOCKER-5 RESOLVED:** Two slippage modes implemented:
> - **MODE A (Fixed):** fill = next bar open ± `SlippageFixedPoints × Point` (adverse, deterministic)
> - **MODE B (Variable):** fill = next bar open ± `|N(mean, std_dev)|` (half-normal, always adverse; seed fixed for reproducibility)
> Three result sets per run: **Base** (zero slippage/commission), **Conservative** (MODE A + commission),
> **Stress** (MODE B + commission × 1.5). Rankings use Conservative only.

---

- [ ] 48. Implement Python Backtest Engine
  - Write `python-research/backtest/engine.py`
  - Confirmed-candle enforcing loop: `data_feed.get_bars(tf, current_index)`
  - Warmup period: skip first `max(ATR_period × timeframe_ratio, RegimeSwingCount × swing_bars)` bars
  - Execute three result set runs per call: Base, Conservative, Stress
  - All three runs use identical strategy logic and data; only execution cost model differs
  - No look-ahead into fill bar
  - Per-bar loop: data slice → analysis → Entry_Engine → Risk_Manager → fill → SL/TP check → equity
  - _Requirements: 16.3, 20.1–20.7_

  - [ ] 48.1 Implement backtest loop core with confirmed-candle enforcing data slice
    - _Requirements: 16.3_

  - [ ] 48.2 Implement MODE A (fixed) and MODE B (variable half-normal) trade simulators
    - MODE B: half-normal draw `|N(mean, std_dev)|`; fixed seed; always adverse cost
    - Commission deducted at trade open: `CommissionPerLot × volume` (Conservative); `× 1.5` (Stress)
    - _Requirements: 20.1, 20.2_

  - [ ] 48.3 Implement three-run orchestration: Base, Conservative, Stress
    - Run engine three times with same data and parameters; store results separately
    - Each report header includes slippage mode name, all cost parameters, seed (MODE B)
    - _Requirements: 20.3, 20.4, 20.7_

  - [ ]* 48.4 Write no-look-ahead canary test for backtest engine
    - Run with genuine data; corrupt bar[0] on every bar with extreme values; run again;
      assert all strategy outputs identical between runs
    - _Requirements: 16.3, 15.5_

  - [ ]* 48.5 Write property test: slippage result sets are independent and correctly ordered (Property 31)
    - **Property 31: Backtest slippage modes produce independent, non-mixed result sets**
    - Assert Base return ≥ Conservative return ≥ Stress return for any positive-trade sequence
    - Assert Conservative and Stress differ by at least `CommissionPerLot × 0.5 × trade_count`
    - **Validates: Requirements 20.1, 20.3, 20.4, 20.5**

---

- [ ] 49. Implement Trade Log Writer
  - Write `python-research/backtest/trade_log.py`
  - Per-trade record fields: entry_timestamp, exit_timestamp, direction, entry_price,
    `signal_reference_price` (candle close), exit_price, stop_loss_price, take_profit_price,
    position_size, realised_pnl, exit_reason (SL/TP/manual), slippage_points (actual),
    commission_paid, all active filter states at entry time, slippage_mode, result_set_name
  - Output: CSV and JSON
  - _Requirements: 16.4, 20.4_

  - [ ] 49.1 Implement TradeLogWriter with all required fields including slippage audit fields
    - _Requirements: 16.4_

  - [ ]* 49.2 Unit test: all required trade log fields present in output for all three result sets
    - Assert `slippage_mode` and `result_set_name` populated correctly per run
    - _Requirements: 16.4, 20.4_

---

- [ ] 50. Implement Walk-Forward Validator
  - Write `python-research/backtest/walk_forward.py`
  - Only permitted validation methodology (no random train/test splits)
  - Configurable: anchor start, in-sample window, out-of-sample window, step size, N folds
  - Per-fold metrics: total return %, max drawdown %, Sharpe ratio, win rate %, profit factor,
    trade count, consecutive loss max, recovery factor
  - Aggregate metrics across all OOS folds → combined equity curve
  - Flag fold if OOS Sharpe < 0 or OOS drawdown > IS drawdown × 2
  - _Requirements: 16.3_

  - [ ] 50.1 Implement walk-forward orchestrator
    - In-sample optimise (parameter grid); OOS evaluate (fixed params, no re-optimisation)
    - _Requirements: 16.3_

  - [ ]* 50.2 Write walk-forward no-look-ahead canary test
    - Inject future data into OOS folds; assert outputs identical (data slice enforces bar[1:])
    - _Requirements: 16.3_

---

- [ ] 51. Implement Sensitivity Analysis Tool
  - Write `python-research/research/sensitivity_analysis.py`
  - Sweep configurable ranges of key parameters
  - Per-combination metrics: total return %, max drawdown %, Sharpe, win rate %, profit factor,
    trade count, flagged (bool: max_DD > FlagDrawdownThreshold, default 20%)
  - Flagged combinations excluded from automatic "best parameter" ranking
  - Output: CSV and JSON
  - Write `python-research/research/report_generator.py` for structured output
  - _Requirements: 16.5, 16.6_

  - [ ] 51.1 Implement sensitivity analysis sweep with flagging logic
    - _Requirements: 16.5, 16.6_

  - [ ]* 51.2 Unit test: flagging rule applied correctly at threshold boundary
    - max_DD exactly at FlagDrawdownThreshold → flagged=true; just below → flagged=false
    - _Requirements: 16.6_

- [ ] 52. Phase 12 Checkpoint
  - Full backtest run completes on at least 2 years of synthetic OHLCV data without errors
  - Walk-forward produces per-fold metrics CSV
  - Sensitivity analysis tool runs and writes output
  - No-look-ahead canary test passes for all analysis modules
  - BLOCKER-5 resolved and documented
  - Ensure all tests pass, ask the user if questions arise.

---

### Phase 13: Integration Validation

**Objective:** Full end-to-end verification across MQL5 and Python systems. Includes all six
integration tests, all seven live-execution safety scenario tests on MT5 demo, and the minimum
4-week demo observation period before any live capital decision.

> **🔴 HUMAN REVIEW REQUIRED:** Confirm MT5 demo account credentials and broker (XM) server name
> are available before beginning Phase 13. All live-execution safety tests require a funded demo
> account with XAUUSD available.

---

- [ ] 53. MQL5 + Python cross-validation
  - Run both MQL5 (Strategy Tester) and Python (backtest engine) on identical OHLCV data and config
  - Compare: number of signals generated, number of trades taken, position sizes, SL/TP levels
  - Acceptable deviation: ≤ 1 pip in price calculations (floating-point precision tolerance)
  - Investigate and resolve any deviation exceeding tolerance
  - _Requirements: 16.1_

  - [ ] 53.1 Generate shared test OHLCV dataset (CSV) and config YAML
    - Use known historical data with predictable structure levels
    - _Requirements: 16.1_

  - [ ] 53.2 Run MQL5 Strategy Tester backtest and export trade log
    - _Requirements: 16.1_

  - [ ] 53.3 Run Python backtest engine on same data and export trade log
    - _Requirements: 16.1_

  - [ ]* 53.4 Cross-validation comparison test
    - Assert signal count, trade count, and price levels match within tolerance
    - _Requirements: 16.1_

---

- [ ] 54. Full pipeline integration tests (6 scenarios from design §Test Architecture)

  - [ ] 54.1 AnalysisStatus pipeline test
    - Feed synthetic OHLCV through all analysis engines; verify AnalysisStatus types, directions,
      and confidence values flow correctly
    - _Requirements: 13.2_

  - [ ] 54.2 TradeSignal generation test
    - Combine all analysis outputs through Entry_Confirmation_Engine; verify TradeSignal fields
      consistent with inputs (direction, SL ≥ ATR floor, TP meets R:R)
    - _Requirements: 13.3_

  - [ ] 54.3 TradeOrder generation test
    - Pass TradeSignal through Risk_Manager; verify TradeOrder lot size, SL, TP
    - _Requirements: 13.4_

  - [ ]* 54.4 State persistence integration test
    - Simulate trade sequence; persist state; reload; verify drawdown and cooldown correctly restored
    - _Requirements: 11.4, 11.5_

  - [ ]* 54.5 Restart recovery integration test
    - Simulate open positions; restart EA; verify State_Manager reconstructs all positions
      with correct state; re-attaches missing SLs
    - _Requirements: 11.1, 11.2_

  - [ ]* 54.6 Circuit breaker integration test
    - Simulate loss sequence reaching total drawdown threshold; verify circuit breaker fires,
      all positions closed, EA disabled
    - _Requirements: 9.6, 17.1_

---

- [ ] 55. Live-execution safety tests on MT5 demo (7 scenarios)
  - All tests require MT5 demo account on XM broker with XAUUSD active
  - Each test must be documented with timestamp, observed result, and pass/fail

  - [ ] 55.1 SL attachment test
    - Manually remove SL from EA-managed position; verify re-attachment within next tick cycle;
      verify CRITICAL log written
    - _Requirements: 17.4_

  - [ ] 55.2 Spread spike test
    - Simulate spread above `MaxSpreadPoints` (modify config to low threshold);
      verify pending order cancelled; verify spread values logged
    - _Requirements: 7.2, 7.3_

  - [ ] 55.3 Connection drop and recovery test
    - Disconnect terminal; reconnect; verify safe monitoring mode entered and exited correctly;
      verify all open positions have valid SLs before normal operation resumes
    - _Requirements: 11.3, 11.7_

  - [ ] 55.4 Daily drawdown circuit breaker test
    - Set `DailyMaxDrawdownPct` to small value; trigger; verify positions closed and entries blocked
      for remainder of day; verify reset at midnight
    - _Requirements: 9.4, 9.5, 17.2_

  - [ ] 55.5 Total drawdown circuit breaker test
    - Set `TotalMaxDrawdownPct` to small value; trigger; verify EA disables itself; confirm
      no automatic re-enable; confirm manual re-attach required
    - _Requirements: 9.6, 17.1, 17.3_

  - [ ] 55.6 Restart state recovery test
    - Open position; stop terminal; restart; verify position state correctly reconstructed; SL present
    - _Requirements: 11.1, 11.5_

  - [ ] 55.7 Cooldown persistence test
    - Set `MaxConsecutiveLosses` = 2; trigger 2 consecutive losses; verify entries blocked for
      `CooldownHours`; restart terminal; verify cooldown still active (start time persisted)
    - _Requirements: 17.6_

---

- [ ] 56. Walk-forward validation on historical data
  - Run walk-forward validator on 2+ years of real XAUUSD OHLCV data (4H, 1H, 15M, 5M)
  - Generate per-fold and aggregate metrics report
  - Assert: no single OOS fold has drawdown above TotalMaxDrawdownPct
  - Assert: at least one filter (session, spread, news, ATR, momentum, regime) responsible for
    ≥1 rejection in each fold (filter coverage verification)
  - _Requirements: 16.3_

  - [ ]* 56.1 Walk-forward run on 2+ years of XAUUSD data
    - _Requirements: 16.3_

  - [ ]* 56.2 Filter coverage verification
    - Assert each filter is responsible for at least one signal rejection across full history
    - _Requirements: 16.3_

---

- [ ] 57. 🔴 HUMAN REVIEW REQUIRED — 4-Week Demo Observation
  - Deploy EA on MT5 demo account (XM broker, XAUUSD)
  - Monitor for minimum 4 calendar weeks
  - Document all triggered safety events (spread spikes, news blocks, session blocks, drawdown events)
  - Confirm all CRITICAL events are handled correctly
  - Confirm trade log entries match expected format for all 11 event types
  - Sign-off required from responsible trader before any live capital is risked
  - _Requirements: 17.1, 17.4, 12.1_

- [ ] 58. Final Integration Checkpoint — Definition of Done
  - All acceptance criteria below satisfied
  - Ensure all tests pass, ask the user if questions arise.

---

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP — however, all 32
  property test tasks (§ Phase 11) are strongly recommended before live deployment.
- Each task references specific requirements for traceability.
- The 5 BLOCKER tasks must be resolved before their dependent tasks are implemented.
- Tasks marked 🔴 HUMAN REVIEW REQUIRED require sign-off from the responsible trader or architect.
- Property tests use Hypothesis (Python) with minimum 100 iterations; 1000 iterations for
  all risk-related properties (Properties 15–19).
- MQL5 property tests use custom test scripts in `tests/` directory.
- All property tests are tagged: `# Feature: xauusd-mt5-ea, Property N: <property_text>`
- The no-look-ahead canary test must be run on every analysis module before demo deployment.

---

## Definition of Done

The EA is considered complete when all of the following are true:

### Code Completeness
- [ ] All 15 MQL5 modules implemented and compile without errors or warnings
- [ ] All Python research modules implemented and pass `pytest` with no failures
- [ ] All 32 correctness properties have passing automated tests
- [ ] No BLOCKER tasks remain open

### Test Coverage
- [ ] All property-based tests pass with required iteration counts (100 min, 1000 for risk)
- [ ] No-look-ahead canary test passes for all 4 analysis modules
- [ ] All 6 integration scenarios pass
- [ ] All 7 live-execution safety scenarios pass on MT5 demo
- [ ] MQL5 and Python backtest outputs match within 1-pip tolerance on shared dataset

### Safety Controls Verified
- [ ] Daily drawdown circuit breaker tested and confirmed
- [ ] Total drawdown circuit breaker tested and confirmed (EA disables, no auto-restart)
- [ ] SL re-attachment and force-close verified on MT5 demo
- [ ] Restart recovery verified with open positions
- [ ] Cooldown persistence verified across restart
- [ ] Connection-drop safe monitoring mode tested

### Documentation and Audit
- [ ] All BLOCKER resolutions documented as inline code comments in affected modules
- [ ] All HUMAN REVIEW sign-offs recorded with date and reviewer name
- [ ] Walk-forward report generated and reviewed
- [ ] Sensitivity analysis output reviewed; no unchecked flagged parameter combinations

### Live Trading Readiness Checklist

> **This checklist must be completed before risking any live capital.**

- [ ] **Demo period:** Minimum 4 weeks of uninterrupted demo operation without CRITICAL errors
- [ ] **Safety controls:** All 7 live-execution safety scenario tests passed on demo
- [ ] **Drawdown limits:** DailyMaxDrawdownPct and TotalMaxDrawdownPct confirmed appropriate for account size
- [ ] **Risk per trade:** RiskPerTradePct confirmed at or below 1% for initial live deployment
- [ ] **News calendar:** `config/news_events.csv` populated with current upcoming events; MaxListAgeHours verified
- [ ] **Sessions enabled:** Correct session windows for current DST period confirmed
- [ ] **Spread threshold:** MaxSpreadPoints verified against broker's typical XAU/USD spread
- [ ] **Magic Number:** Unique Magic Number confirmed; no conflict with other EAs on the same account
- [ ] **State file path:** StateFilePath configured to a writable directory with sufficient disk space
- [ ] **Log level:** Minimum log level set to INFO for live trading
- [ ] **Circuit breaker:** circuit_breaker_triggered = false confirmed in state file before EA start
- [ ] **Symbol Properties:** SymbolPropertiesReader tested against live XM XAUUSD contract spec
- [ ] **Walk-forward:** Walk-forward report reviewed; aggregate OOS metrics meet minimum thresholds
- [ ] **Human sign-off:** Responsible trader has reviewed this checklist and signed off (date: \_\_\_\_\_\_\_\_)

---

## Critical Path

The critical path through the dependency graph is the longest chain of sequential dependencies:

```
Phase 1 (Foundation) →
  Logger → Config_Manager → SymbolProperties → MTFDataFeed → StateManager
Phase 2 (ATR Engine) →
Phase 3 (Analysis Engines: MSA → LiquidityDetector → MomentumEngine) →
Phase 4 (Filter Layer: Session + News + Spread) →
Phase 5 (Entry_Confirmation_Engine) →
Phase 6 (Risk_Manager) →
Phase 7 (Order_Executor) →
Phase 8 (Position Management / Main EA) →
Phase 9 (Persistence hardening) →
Phase 10 (Logging validation) →
Phase 11 (All 26 property tests) →
Phase 12 (Python Backtest + Walk-Forward) →
Phase 13 (Integration + Demo validation)
```

**Estimated longest sequential chain:** Phases 1–8 (MQL5 EA functional). Phases 9–13 add
hardening, testing, and validation.

**Parallel work opportunities:**
- Python mirror modules can be written in parallel with their MQL5 counterparts (Phases 1–7)
- Phase 4 filters (Session, News, Spread) can be implemented in parallel
- Phase 11 property tests can run as soon as the module they test is complete (do not wait for Phase 11)
- Python backtest engine (Phase 12) can start as soon as Python strategy modules are complete
- Walk-forward (Phase 12) and sensitivity analysis (Phase 12) are independent of each other

**Tasks requiring mandatory sequential order (no parallelism):**
- LiquidityDetector must follow ATR engine (ATR is input to pool tolerance)
- EntryConfirmationEngine must follow all analysis engines and filters
- Risk_Manager must follow EntryConfirmationEngine
- Order_Executor must follow Risk_Manager
- Phase 13 integration tests must follow all prior phases

---

## Tasks Requiring Manual Human Review

All five technical blockers have been resolved. The following tasks still require human sign-off
before or during execution:

| # | Task | Review Required | Phase | Status |
|---|---|---|---|---|
| 1 | ~~BLOCKER-1~~ | ~~Entry price source~~ | 5 | ✅ RESOLVED |
| 2 | ~~BLOCKER-2~~ | ~~TP construction priority rule~~ | 5 | ✅ RESOLVED |
| 3 | ~~BLOCKER-3~~ | ~~SL static confirmation~~ | 8 | ✅ RESOLVED |
| 4 | ~~BLOCKER-4~~ | ~~State file format~~ | 9 | ✅ RESOLVED |
| 5 | ~~BLOCKER-5~~ | ~~Slippage model type~~ | 12 | ✅ RESOLVED |
| 6 | Task 55 | MT5 demo account and XM broker credentials for safety tests | 13 | 🔴 OPEN |
| 7 | Task 57 | 4-week demo observation sign-off before live capital | 13 | 🔴 OPEN |
| 8 | ~~Freeze-level~~ | ~~Confirm DEBUG log vs. silent skip for freeze-level SL skips~~ | 7 | ✅ RESOLVED |

---

## Task Dependency Graph

```json
{
  "waves": [
    {
      "id": 0,
      "tasks": ["1.1", "1.3"]
    },
    {
      "id": 1,
      "tasks": ["1.2", "2.1", "2.4", "3.1", "3.3", "4.1", "4.3"]
    },
    {
      "id": 2,
      "tasks": ["1.2", "2.2", "2.3", "3.2", "4.2", "5.1", "6.6"]
    },
    {
      "id": 3,
      "tasks": ["5.2", "5.3", "5.4", "6.1", "6.2"]
    },
    {
      "id": 4,
      "tasks": ["5.3", "6.3", "6.4", "6.5", "8.1", "8.2", "8.6"]
    },
    {
      "id": 5,
      "tasks": ["8.3", "8.4", "8.5", "10.1", "10.8"]
    },
    {
      "id": 6,
      "tasks": ["10.2", "10.3", "10.5", "12.1", "12.4", "14.1", "14.4", "15.1", "15.4", "15.5", "16.1", "16.4"]
    },
    {
      "id": 7,
      "tasks": ["10.4", "10.6", "10.7", "12.2", "12.3", "14.2", "14.3", "15.2", "15.3", "16.2", "16.3"]
    },
    {
      "id": 8,
      "tasks": ["11.1", "11.7"]
    },
    {
      "id": 9,
      "tasks": ["11.2", "11.7"]
    },
    {
      "id": 10,
      "tasks": ["11.3", "11.4", "11.5", "11.6", "18.1", "18.6"]
    },
    {
      "id": 11,
      "tasks": ["18.2", "18.3", "18.4", "18.5", "20.1", "20.10"]
    },
    {
      "id": 12,
      "tasks": ["20.2", "20.3", "20.4", "20.9", "22.1"]
    },
    {
      "id": 13,
      "tasks": ["20.5", "20.6", "20.7", "20.8", "22.2", "22.3", "22.4"]
    },
    {
      "id": 14,
      "tasks": ["22.5", "24.1", "24.2", "24.3", "30.1"]
    },
    {
      "id": 15,
      "tasks": ["25.1", "25.2", "25.3", "27.1", "27.2", "30.2", "30.3", "30.4"]
    },
    {
      "id": 16,
      "tasks": ["27.3", "27.4", "27.5", "28.1", "28.2", "28.3", "28.4", "28.5", "28.6", "28.7", "28.8", "28.9"]
    },
    {
      "id": 17,
      "tasks": [
        "32.1", "32.2",
        "33.1", "33.2",
        "34.1", "34.2", "34.3",
        "35.1",
        "36.1",
        "37.1", "37.2",
        "38.1",
        "39.1",
        "40.1",
        "41.1", "41.2", "41.3", "41.4", "41.5",
        "42.1", "42.2",
        "43.1", "43.2",
        "44.1", "44.2",
        "45.1"
      ]
    },
    {
      "id": 18,
      "tasks": ["48.1", "48.2", "49.1", "50.1"]
    },
    {
      "id": 19,
      "tasks": ["48.3", "49.2", "50.2", "51.1"]
    },
    {
      "id": 20,
      "tasks": ["51.2", "53.1"]
    },
    {
      "id": 21,
      "tasks": ["53.2", "53.3"]
    },
    {
      "id": 22,
      "tasks": ["53.4", "53.5", "53.6", "54.1", "54.2", "54.3"]
    },
    {
      "id": 23,
      "tasks": ["54.4", "54.5", "54.6"]
    },
    {
      "id": 24,
      "tasks": ["55.1", "55.2", "55.3", "55.4", "55.5", "55.6", "55.7"]
    },
    {
      "id": 25,
      "tasks": ["56.1", "56.2"]
    }
  ]
}
```
