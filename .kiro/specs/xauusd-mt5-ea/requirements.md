# Requirements Document

## Introduction

This document defines the requirements for a professional XAU/USD (Gold) algorithmic trading system
implemented as a MetaTrader 5 Expert Advisor (EA) for live execution through XM broker. The system
applies multi-timeframe market structure analysis — combining 4H regime detection, 1H major structure,
15M liquidity/setup detection, and 5M entry confirmation — alongside strict risk management and
professional-grade safety controls.

The system is intended for eventual live trading. Profitability is not guaranteed. The architecture
separates market analysis, strategy logic, risk management, and order execution into distinct, testable
modules. A companion Python environment supports research, back-testing, and analysis.

---

## Glossary

- **EA**: Expert Advisor — an automated trading program running inside MetaTrader 5.
- **MQL5**: The programming language used to write EAs for MetaTrader 5.
- **Symbol_Properties**: Real-time broker/symbol data retrieved via MT5 API (spread, point size, digits, contract size, margin requirements, stop levels, etc.).
- **Market_Structure_Analyzer**: The module responsible for detecting swing highs/lows, BOS, CHOCH, and market regime on each timeframe.
- **Liquidity_Detector**: The module responsible for identifying liquidity pools, equal highs/lows, and sweep events.
- **Entry_Confirmation_Engine**: The module that combines signals from all timeframes and filters to produce a validated trade signal.
- **Risk_Manager**: The module that calculates position size, stop-loss distance, take-profit targets, and enforces all risk limits independently of strategy logic.
- **Order_Executor**: The module that submits, modifies, and closes orders via the MT5 trade API, handles retries, and validates execution results.
- **Session_Filter**: The module that restricts trading to approved market sessions (London, New York, London/NY overlap).
- **Spread_Filter**: The module that checks current spread against a dynamic maximum threshold before allowing order submission.
- **News_Filter**: The module that blocks new trade entries during configurable windows around high-impact economic events.
- **State_Manager**: The module that persists EA state across terminal restarts and connection interruptions.
- **Logger**: The module responsible for writing structured log entries for every significant EA action, decision, and error.
- **BOS**: Break of Structure — a confirmed close beyond a prior significant swing high (bullish BOS) or swing low (bearish BOS).
- **CHOCH**: Change of Character — a BOS that occurs in the opposite direction of the prevailing trend, signalling a potential reversal.
- **Liquidity_Pool**: A price zone where a concentration of stop orders is expected to rest, typically at or just beyond equal highs or equal lows.
- **Liquidity_Sweep**: A price excursion through a Liquidity_Pool followed by a reversal back inside the pool boundary.
- **ATR**: Average True Range — a measure of market volatility over N periods.
- **Regime**: The current directional bias of the market on the 4H timeframe (Bullish, Bearish, Ranging).
- **Swing_High / Swing_Low**: A confirmed local price extremum identified using a minimum left/right candle look-back on closed candles only.
- **Confirmed_Candle**: A candle at bar index ≥ 1 whose open, high, low, and close values are final and immutable (i.e., not the currently forming candle at bar index 0).
- **Look-Ahead_Bias**: Use of data from bar index 0 or any future bar that would not have been available at the time a decision was made — strictly prohibited in all strategy logic.
- **Drawdown**: The peak-to-trough decline in account equity over a measurement period.
- **Risk_Per_Trade**: The maximum monetary or percentage loss permitted on a single trade.
- **R:R**: Risk-to-Reward ratio — the ratio of potential loss (risk) to potential gain (reward) on a trade.
- **Protective_Stop**: A stop-loss order placed on every live trade without exception.
- **Magic_Number**: A unique integer identifier assigned to all orders placed by this EA to distinguish them from manual or other EA orders.
- **Slippage**: The difference between the expected execution price and the actual fill price.
- **Python_Research_Env**: The companion Python environment used for strategy research, data analysis, and back-testing — not for live order execution.
- **AnalysisStatus**: The structured interface object passed from analysis modules (Market_Structure_Analyzer, Liquidity_Detector, filters) to the Entry_Confirmation_Engine, containing: signal type, direction, confidence level (integer 0–100), and timestamp.
- **TradeSignal**: The structured interface object passed from the Entry_Confirmation_Engine to the Risk_Manager, containing: signal reference price (confirming candle close), execution entry price (live Ask for BUY / live Bid for SELL at signal generation time), stop-loss price, take-profit price, direction, and signal timestamp.
- **Signal_Reference_Price**: The close price of the confirmed candle that triggered the entry signal. Used for audit and logging only — never used as the live execution price.
- **Execution_Entry_Price**: The live executable Ask (BUY) or Bid (SELL) price at the moment the TradeSignal is generated. This is the price passed to OrderSend. The spread is re-checked again immediately before OrderSend submission.
- **Static_SL**: A stop-loss level calculated before order submission and fixed for the lifetime of the position. V1 of this EA uses static SL only — no trailing stop, no break-even move, no partial TP, no position averaging.
- **TP_Candidate**: A price level eligible for use as take-profit. In V1, the TP is set to the nearest Active opposing Liquidity_Pool whose distance from the execution entry price satisfies the minimum R:R requirement. If no such pool exists, the trade is rejected with NO_VALID_TP.
- **NO_VALID_TP**: A rejection reason returned by the Entry_Confirmation_Engine when no opposing Liquidity_Pool satisfies the minimum R:R requirement. The trade is not taken.
- **SAFE_MODE**: An EA operational state entered when the persisted state file cannot be trusted (missing, corrupt, failed checksum, or incompatible schema version). In SAFE_MODE the EA blocks all new entries, monitors open positions, and logs a CRITICAL alert. SAFE_MODE requires manual intervention to exit.
- **TradeOrder**: The structured interface object passed from the Risk_Manager to the Order_Executor, containing: symbol, order type, volume, entry price, stop-loss price, take-profit price, and timestamp.

---

## Requirements

### Requirement 1: Multi-Timeframe Market Structure Analysis

**User Story:** As a trader, I want the EA to analyse market structure across four timeframes so that trade entries are aligned with the dominant trend and significant structural levels.

#### Acceptance Criteria

1. THE Market_Structure_Analyzer SHALL identify Swing_High and Swing_Low points on each of the four timeframes (4H, 1H, 15M, 5M) using only Confirmed_Candle data (bar index ≥ 1).
2. WHEN identifying a Swing_High or Swing_Low, THE Market_Structure_Analyzer SHALL require a configurable minimum number of confirmed candles on each side of the extremum (valid range: 1–5, default: 2 candles each side) before classifying the point as confirmed.
3. THE Market_Structure_Analyzer SHALL classify the 4H market Regime as Bullish, Bearish, or Ranging based on the sequence of the most recent confirmed Swing_High and Swing_Low points, where a Bullish classification requires all N configured swing points to form strictly higher highs and higher lows, a Bearish classification requires all N configured swing points to form strictly lower highs and lower lows, and Ranging applies in all other cases including insufficient swing history.
4. WHEN a confirmed candle closes beyond a prior confirmed Swing_High or Swing_Low on the 1H or higher timeframe, THE Market_Structure_Analyzer SHALL record a BOS event with the direction, the price level broken, and the candle timestamp.
5. WHEN a BOS occurs in the direction opposite to the current Regime, THE Market_Structure_Analyzer SHALL record a CHOCH event with the same fields as the BOS event.
6. THE Market_Structure_Analyzer SHALL recalculate structure on every new confirmed candle and SHALL NOT read data from bar index 0 (the currently forming candle) for any structural decision.
7. IF price data for a required timeframe is unavailable or returns fewer bars than the configured minimum lookback (minimum lookback = (2 × candle-side parameter) + 1), THEN THE Market_Structure_Analyzer SHALL log an error and set the affected timeframe's structure status to UNKNOWN.

---

### Requirement 2: Liquidity Detection and Sweep Identification

**User Story:** As a trader, I want the EA to detect liquidity pools and identify when they have been swept so that entries can be timed to capture post-sweep reversals.

#### Acceptance Criteria

1. THE Liquidity_Detector SHALL identify Liquidity_Pool zones at confirmed equal highs and equal lows, defined as two or more Swing_High or Swing_Low points within a configurable price tolerance (valid range: 0.1×–2.0× ATR, default: 0.5× ATR on the detection timeframe).
2. WHEN a candle's wick or close trades through a Liquidity_Pool boundary on the detection timeframe AND a subsequent Confirmed_Candle on the same timeframe closes back inside the pool boundary, THE Liquidity_Detector SHALL record a Liquidity_Sweep event with the pool level, sweep direction, and confirming candle timestamp.
3. THE Liquidity_Detector SHALL track the status of each identified Liquidity_Pool as Active, Swept, or Invalidated; a pool SHALL be marked Invalidated when price closes beyond the pool boundary by more than the pool tolerance without a sweep confirmation.
4. WHEN a Liquidity_Pool has been tagged by a Liquidity_Sweep, THE Liquidity_Detector SHALL mark the pool as Swept and prevent it from generating further sweep signals unless a new pool forms within the tolerance band defined in criterion 1.
5. THE Liquidity_Detector SHALL maintain no more than a configurable maximum number of Active pools per timeframe (valid range: 5–50, default: 20) and SHALL discard the oldest pool when the limit is exceeded.
6. IF the ATR value required for pool tolerance calculation is unavailable, THEN THE Liquidity_Detector SHALL log an error and suspend Liquidity_Pool detection until a valid ATR value is successfully computed from a Confirmed_Candle.
7. THE Liquidity_Detector SHALL NOT use bar index 0 (the currently forming candle) to confirm a Liquidity_Sweep.

---

### Requirement 3: Trend and Regime Detection

**User Story:** As a trader, I want the EA to determine the current market regime so that it only takes trades aligned with the dominant directional bias.

#### Acceptance Criteria

1. THE Market_Structure_Analyzer SHALL determine the 4H Regime using the last configurable number of alternating confirmed Swing_High and Swing_Low points (valid range: 2–10, default: 4 most recent alternating swings).
2. WHEN all N configured most recently confirmed swing points on 4H form a sequence where each Swing_High is strictly greater than the preceding Swing_High AND each Swing_Low is strictly greater than the preceding Swing_Low, THE Market_Structure_Analyzer SHALL set the Regime to Bullish.
3. WHEN all N configured most recently confirmed swing points on 4H form a sequence where each Swing_High is strictly less than the preceding Swing_High AND each Swing_Low is strictly less than the preceding Swing_Low, THE Market_Structure_Analyzer SHALL set the Regime to Bearish.
4. WHEN the 4H swing sequence does not satisfy the Bullish or Bearish criteria, or when fewer than N confirmed swings are available, THE Market_Structure_Analyzer SHALL set the Regime to Ranging.
5. WHILE the Regime is Ranging, THE Entry_Confirmation_Engine SHALL block all new trade entries.
6. IF a configurable Ranging_Mode_Enabled parameter is set to TRUE, THEN the Ranging block in criterion 5 SHALL be lifted and the Entry_Confirmation_Engine SHALL process entry signals during Ranging conditions.
7. WHEN the Regime changes from one value to another, THE Market_Structure_Analyzer SHALL log the previous Regime, the new Regime, and the timestamp of the Confirmed_Candle that triggered the change.
8. IF fewer than the minimum required confirmed swings (2) are available on the 4H timeframe at EA initialisation or after data gaps, THEN THE Market_Structure_Analyzer SHALL default the Regime to Ranging and log a warning.

---

### Requirement 4: Momentum Confirmation

**User Story:** As a trader, I want entry signals to be confirmed by momentum so that trades enter during genuine directional moves rather than weak retracements.

#### Acceptance Criteria

1. THE Entry_Confirmation_Engine SHALL calculate momentum on the 5M timeframe by comparing the most recently closed candle's close price against the high-low range of the prior N closed candles, where N is configurable (valid range: 2–50, default: 10), using only candles at bar index ≥ 1.
2. WHEN a long entry signal is generated, THE Entry_Confirmation_Engine SHALL require that the most recently closed 5M candle's close price falls within the upper 50% of the prior N-candle high-low range before approving the signal and passing it to the Risk_Manager.
3. WHEN a short entry signal is generated, THE Entry_Confirmation_Engine SHALL require that the most recently closed 5M candle's close price falls within the lower 50% of the prior N-candle high-low range before approving the signal and passing it to the Risk_Manager.
4. IF the momentum calculation returns an indeterminate result — defined as fewer than N closed candles available, or the prior N-candle high-low range being undefined or zero — THEN THE Entry_Confirmation_Engine SHALL reject the entry signal and log the rejection reason including the number of available candles and the computed range value.
5. THE Entry_Confirmation_Engine SHALL NOT read bar index 0 (the currently forming candle) for any momentum calculation; all momentum values SHALL be derived exclusively from candles whose close event has already occurred.

---

### Requirement 5: ATR Volatility Filtering

**User Story:** As a trader, I want the EA to filter trades based on current volatility so that it avoids entering during abnormally low or abnormally high volatility conditions.

#### Acceptance Criteria

1. THE Entry_Confirmation_Engine SHALL calculate ATR on the 1H timeframe over a configurable period (default: 14 candles, valid range: 5–50) using only Confirmed_Candle data (bar index ≥ 1).
2. IF current 1H ATR is below a configurable minimum threshold — expressed as a multiplier of the baseline 30-day average ATR computed from the 720 most recent closed 1H candles (default multiplier: 0.5, valid range: 0.1–1.0) — THEN THE Entry_Confirmation_Engine SHALL block new entries and log the current ATR value, the computed baseline, and the threshold.
3. IF current 1H ATR is above a configurable maximum threshold — expressed as a multiplier of the same 30-day baseline (default multiplier: 2.5, valid range: 1.5–5.0) — THEN THE Entry_Confirmation_Engine SHALL block new entries and log the current ATR value, the computed baseline, and the threshold.
4. THE Entry_Confirmation_Engine SHALL use ATR to set the minimum stop-loss distance as a configurable multiplier of the 1H ATR (default: 1.5×, valid range: 0.5–5.0); IF the calculated stop-loss distance is less than the broker minimum stop level from Symbol_Properties, THEN the broker minimum stop level SHALL be used instead.
5. IF ATR data is unavailable for more than a configurable timeout period (default: 5 minutes, valid range: 1–60 minutes), THEN THE Entry_Confirmation_Engine SHALL log an error and suspend trading until a new ATR value is successfully computed from a Confirmed_Candle.
6. IF fewer than 720 closed 1H candles are available for baseline calculation, THEN THE Entry_Confirmation_Engine SHALL log a warning and use the available history as the baseline, provided at least 14 closed candles are present; if fewer than 14 closed candles are available, entry signals SHALL be blocked.

---

### Requirement 6: Session Filter

**User Story:** As a trader, I want the EA to trade only during high-liquidity market sessions so that entries benefit from tighter spreads and meaningful price moves.

#### Acceptance Criteria

1. THE Session_Filter SHALL define tradeable sessions by configurable UTC start and end times for London (default: 07:00–12:00 UTC), New York (default: 13:00–17:00 UTC), and London/NY Overlap (default: 13:00–15:00 UTC).
2. WHILE the current server time falls within at least one enabled tradeable session window, THE Session_Filter SHALL return an ALLOWED status to the Entry_Confirmation_Engine; WHILE the current server time falls outside all enabled session windows, THE Session_Filter SHALL return a BLOCKED status.
3. WHEN the Entry_Confirmation_Engine receives a BLOCKED status from the Session_Filter, THE Entry_Confirmation_Engine SHALL not generate or approve new entry signals.
4. THE Session_Filter SHALL allow configurable individual session enable/disable flags so that each session can be independently turned on or off.
5. THE Session_Filter SHALL use broker server time (not local PC time) for all session comparisons.
6. THE Session_Filter SHALL accept configurable UTC offset values per session to accommodate Daylight Saving Time transitions; valid UTC offsets SHALL be within the range −12 to +14 hours.
7. IF broker server time cannot be retrieved, THEN THE Session_Filter SHALL return BLOCKED and log an error.
8. IF all configured sessions are disabled, THEN THE Session_Filter SHALL return BLOCKED and log a configuration warning.
9. IF any session's configured start time is greater than or equal to its configured end time, THEN THE Session_Filter SHALL return BLOCKED for that session and log a configuration error identifying the invalid session.

---

### Requirement 7: Spread Filter

**User Story:** As a trader, I want the EA to check the current spread before entering a trade so that entries are not made during spread spikes that erode trade economics.

#### Acceptance Criteria

1. WHEN an order submission is initiated, THE Spread_Filter SHALL read the current ask-bid spread for XAUUSD from Symbol_Properties at that moment.
2. IF the current spread exceeds the configurable maximum spread threshold (valid range: 10–200 points, default: 30 points for XAUUSD, where the point value is obtained from Symbol_Properties), THEN THE Spread_Filter SHALL return BLOCKED to the Order_Executor.
3. WHEN THE Order_Executor receives a BLOCKED status from the Spread_Filter, THE Order_Executor SHALL cancel the pending order submission and log both the current spread value and the configured threshold.
4. THE Spread_Filter SHALL re-evaluate spread at every order submission attempt and SHALL NOT cache spread values across attempts.
5. THE Spread_Filter SHALL NOT apply the spread check to order modification or order closure operations; the spread check applies only to new order submissions.
6. IF Symbol_Properties cannot be read, THEN THE Spread_Filter SHALL return BLOCKED and log an error.

---

### Requirement 8: Economic News Protection

**User Story:** As a trader, I want the EA to avoid entering trades around high-impact news events so that positions are not caught by violent news-driven price spikes.

#### Acceptance Criteria

1. THE News_Filter SHALL maintain a configurable list of upcoming economic event records, each containing event name, UTC timestamp, and impact level (Low, Medium, High); the list SHALL be loaded from a configurable local file or external calendar feed.
2. THE News_Filter SHALL apply blocking or warning behavior only to events at or above a configurable minimum impact level (default: High; valid values: Low, Medium, High).
3. IF the current server time is within a configurable pre-event window (valid range: 0–120 minutes, default: 30 minutes before a qualifying event), THEN THE News_Filter SHALL return BLOCKED.
4. IF the current server time is within a configurable post-event window (valid range: 0–120 minutes, default: 15 minutes after a qualifying event), THEN THE News_Filter SHALL return BLOCKED.
5. THE News_Filter SHALL be configurable via a News_Protection_Mode parameter (BLOCK, WARN, DISABLED); WHEN News_Protection_Mode is WARN, THE News_Filter SHALL return a WARN status instead of BLOCKED, and the Entry_Confirmation_Engine SHALL log the warning including the event name and scheduled time but SHALL still approve the entry signal.
6. WHEN THE Entry_Confirmation_Engine receives a BLOCKED status from the News_Filter, THE Entry_Confirmation_Engine SHALL not approve new entry signals and SHALL log the blocking event name, impact level, and scheduled time.
7. IF the news event list cannot be loaded or the most recent event timestamp in the list is stale by more than a configurable maximum age (valid range: 1–168 hours, default: 24 hours), THEN THE News_Filter SHALL log a warning and default to the configured fallback behaviour (BLOCK or ALLOW, configurable, default: BLOCK).

---

### Requirement 9: Risk Management

**User Story:** As a trader, I want every trade to have precisely calculated position size and strictly enforced risk limits so that no single trade or sequence of trades can cause catastrophic account loss.

#### Acceptance Criteria

1. THE Risk_Manager SHALL calculate position size for every trade such that the monetary risk (entry price minus stop-loss price, multiplied by position size and contract value) does not exceed a configurable Risk_Per_Trade_Percent of current floating account equity — defined as balance plus unrealised P&L — (default: 1.0%, valid range: 0.1%–5.0%).
2. THE Risk_Manager SHALL enforce a configurable maximum position size cap (default: 0.5 lots for XAUUSD, valid range: 0.01–10.0 lots) regardless of the calculated size.
3. THE Risk_Manager SHALL enforce a configurable maximum number of simultaneously open trades (default: 2, valid range: 1–10).
4. THE Risk_Manager SHALL enforce a configurable daily maximum drawdown limit (default: 5% of floating account equity at broker server 00:00 UTC); WHEN the accumulated intraday loss reaches this limit, THE Risk_Manager SHALL instruct the Order_Executor to close all open positions and log the event.
5. WHILE the daily drawdown limit has been reached, THE Risk_Manager SHALL block all new entry signals for the remainder of that trading day and log each blocked signal.
6. THE Risk_Manager SHALL enforce a configurable total account drawdown limit (default: 15%, valid range: 5%–50%) measured from the floating equity snapshot captured at OnInit; WHEN this limit is reached, THE Risk_Manager SHALL disable the EA (halt all order submissions and close all open positions) and log a CRITICAL alert.
7. THE Risk_Manager SHALL require a minimum R:R of a configurable value (default: 1.5, valid range: 1.0–10.0) before approving a trade signal; IF the calculated R:R is below this threshold, THEN THE Risk_Manager SHALL reject the TradeSignal and log the rejection reason including the calculated R:R and the configured minimum.
8. THE Risk_Manager SHALL obtain lot step, minimum lot size, and maximum lot size from Symbol_Properties and round all calculated position sizes to the nearest valid lot step; the rounded size SHALL NOT be below the minimum lot size.
9. THE Risk_Manager SHALL operate as a module independent of strategy logic; it SHALL receive a TradeSignal and return either an approved TradeOrder or a rejection with the unmet criterion identified.
10. IF a TradeSignal is received with a zero entry price, zero stop-loss price, or undefined direction, THEN THE Risk_Manager SHALL discard the signal and log an error identifying the invalid field.
11. IF the Risk_Manager receives a request to open a new position while an existing position in the same direction has an unrealised loss, THEN THE Risk_Manager SHALL evaluate the new signal independently; the new position SHALL only be approved if the combined risk of all open positions after adding the new position does not exceed the configured Risk_Per_Trade_Percent multiplied by the configured maximum number of simultaneous trades.
12. IF the calculated position size after rounding to lot step is zero, THEN THE Risk_Manager SHALL reject the TradeSignal and log the rejection reason including the pre-rounding calculated size.

---

### Requirement 10: Order Execution

**User Story:** As a trader, I want all trade orders to be submitted with protective stops, validated after fill, and retried safely on failure so that live trades are always protected and execution is reliable.

#### Acceptance Criteria

1. THE Order_Executor SHALL attach a Protective_Stop (stop-loss order) to every trade at the time of order submission; orders SHALL NOT be submitted without a stop-loss.
2. THE Order_Executor SHALL attach a take-profit level to every trade at the time of submission.
3. WHEN an order is submitted and the broker returns a non-fatal error (e.g., REQUOTE, PRICE_CHANGED, CONNECTION_ERROR), THE Order_Executor SHALL retry the submission up to a configurable maximum retry count (default: 3, valid range: 1–10) with a configurable delay between retries (default: 500 ms, valid range: 100–5000 ms); WHEN retries are exhausted without success, THE Order_Executor SHALL log the final error with full order details and cancel the submission without further retry.
4. WHEN an order fill is confirmed, THE Order_Executor SHALL verify that the filled stop-loss and take-profit levels match the submitted values within the broker stop level tolerance obtained from Symbol_Properties.
5. WHEN a filled order's stop-loss or take-profit does not match the submitted values, THE Order_Executor SHALL attempt to correct the levels once within the same execution cycle; IF the correction attempt fails, THEN THE Order_Executor SHALL log a CRITICAL error identifying the ticket number and mismatched values and halt further order management for that ticket until manual intervention.
6. THE Order_Executor SHALL use the Magic_Number on all orders to distinguish EA-managed trades from manual trades.
7. WHEN the Spread_Filter returns BLOCKED at order submission time, THE Order_Executor SHALL cancel the submission, log the current spread value and threshold, and not retry until a new entry signal is generated.
8. IF the calculated stop-loss distance is below the broker's minimum stop level (SYMBOL_TRADE_STOPS_LEVEL from Symbol_Properties), THEN THE Order_Executor SHALL cancel the submission and log the stop distance, minimum stop level, and order details.
9. IF an order is rejected with a fatal error (e.g., INVALID_STOPS, MARKET_CLOSED, TRADE_DISABLED), THEN THE Order_Executor SHALL log the error with the order ticket, symbol, direction, volume, entry price, stop-loss price, take-profit price, and MT5 error code, and SHALL NOT retry that specific order.
10. THE Order_Executor SHALL log every order attempt, fill, rejection, modification, and closure with timestamp, order ticket, price, volume, and error code where applicable.
11. WHEN submitting an order, THE Order_Executor SHALL log both the Signal_Reference_Price (the confirming candle close that generated the signal) and the Execution_Entry_Price (the live Ask or Bid at submission time) so that signal slippage — defined as the difference between these two values — is visible in the audit trail.
12. THE Order_Executor SHALL re-read the current executable Ask (BUY) or Bid (SELL) price immediately before each OrderSend call and use that live price as the Execution_Entry_Price; the Execution_Entry_Price captured at signal generation time SHALL NOT be used if it is stale by more than a configurable maximum signal age (default: 0 — always re-read; valid range: 0–60 seconds).
13. WHEN the Order_Executor attempts to modify or re-attach an SL/TP on an open position and the position is within the broker's freeze level (SYMBOL_TRADE_FREEZE_LEVEL in points, obtained from Symbol_Properties), THE Order_Executor SHALL NOT attempt the modification, SHALL NOT force the modification through any workaround, and SHALL write a structured WARN log entry containing: symbol, ticket/position identifier, operation attempted, current relevant price, freeze-level value in points, required distance, reason "FREEZE_LEVEL_ACTIVE", and UTC timestamp.
14. WHEN a freeze-level skip occurs on a position that is missing its mandatory stop-loss, THE Order_Executor SHALL follow the existing protective SL policy: the re-attachment attempt is deferred to the next monitoring cycle; IF the position remains missing its SL after a configurable maximum number of consecutive freeze-level skips (default: 5, valid range: 1–20), THEN THE Order_Executor SHALL close the unprotected position immediately and log a CRITICAL error.

---

### Requirement 11: State Management and Resilience

**User Story:** As a trader, I want the EA to recover gracefully from terminal restarts and connection drops so that open positions are never left unmanaged and the EA resumes correctly.

#### Acceptance Criteria

1. WHEN the EA initialises (OnInit), THE State_Manager SHALL scan all open orders filtered by Magic_Number and reconstruct the internal trade state from the live order book.
2. WHEN an open order is found during initialisation without a stop-loss, THE State_Manager SHALL instruct the Order_Executor to attach a stop-loss calculated by the Risk_Manager; THE EA SHALL resume normal operation only after the stop-loss attachment is confirmed or the failed attachment attempt has been logged.
3. WHEN a connection to the broker is lost, THE State_Manager SHALL enter a safe monitoring mode in which no new entries are attempted.
4. THE State_Manager SHALL persist the daily drawdown accumulator and the total drawdown reference equity to a local file immediately after every update to either value, so that drawdown limits are correctly enforced after a terminal restart.
5. WHEN the terminal restarts mid-day, THE State_Manager SHALL restore the daily drawdown accumulator from the persisted file and enforce limits from the restored value.
6. IF the persisted state file is corrupt, missing (and state is required for continuity), has an unsupported schema version, or fails checksum or integrity validation, THEN THE State_Manager SHALL enter SAFE_MODE as defined in Requirement 19.4: block all new trade entries, log a CRITICAL alert identifying the specific failure, persist `SAFE_MODE=1` to the sentinel file, reconcile actual MT5 positions and orders from the live order book, ensure all existing positions have valid stop-loss orders, and require manual re-enablement before new trading resumes. The EA SHALL NOT silently reset drawdown accumulators and continue trading under any state-integrity-failure condition.
7. WHILE in safe monitoring mode following a connection loss, THE State_Manager SHALL check the status of all open positions every 30 seconds once connection is restored, and SHALL exit safe monitoring mode only after confirming all open positions have valid stop-loss orders.
8. WHEN entering SAFE_MODE due to a state file integrity failure, THE State_Manager SHALL attempt deterministic state reconstruction using only trusted MT5 live order book data and account history; IF sufficient trusted data exists to reconstruct daily drawdown, total drawdown reference, and open position state, THEN THE State_Manager SHALL log the reconstructed values at INFO level and present them for manual review; THE EA SHALL remain in SAFE_MODE until the trader manually confirms the reconstructed state and re-enables the EA.
9. IF state reconstruction in SAFE_MODE cannot produce trusted values for the daily drawdown accumulator or total drawdown reference equity — for example because the EA has been offline for multiple days — THEN THE State_Manager SHALL log a WARNING identifying which values could not be reconstructed, and the trader's manual re-enablement step SHALL include explicit confirmation of those values before trading resumes.

---

### Requirement 12: Logging and Monitoring

**User Story:** As a trader, I want every significant EA action and decision to be logged with sufficient detail so that I can audit behaviour, diagnose issues, and review performance.

#### Acceptance Criteria

1. WHEN any of the following events occurs, THE Logger SHALL write a structured log entry containing: event type, UTC timestamp in ISO 8601 format, module name, and event-specific fields — events: trade signal generated, signal approved, signal rejected, order submitted, order filled, order rejected, order modified, order closed, risk limit triggered, filter blocked, EA state change.
2. THE Logger SHALL prefix every log entry with a log level tag from the set {DEBUG, INFO, WARN, ERROR, CRITICAL} and the UTC timestamp in ISO 8601 format (e.g., 2026-09-08T07:30:00Z).
3. WHEN a trade-related event is logged — defined as signal generated, signal approved/rejected, order submitted, order filled, order rejected, order modified, or order closed — THE Logger SHALL include the current floating account equity, account balance, and open drawdown percentage in that log entry.
4. WHEN a CRITICAL event occurs — defined as total drawdown limit reached, EA disabled by circuit breaker, or an unrecoverable internal error — THE Logger SHALL write the entry at CRITICAL level, and THE State_Manager SHALL disable the EA within the same execution cycle.
5. THE Logger SHALL support a configurable minimum log level (default: INFO); log entries below the configured minimum level SHALL be suppressed and not written to the Experts log.
6. THE Logger SHALL mask any account number appearing in a log entry by replacing all but the last four digits with asterisks (e.g., "****1234") and SHALL NOT write broker passwords, API keys, or other credentials to any log output.

---

### Requirement 13: Module Architecture and Separation of Concerns

**User Story:** As a developer, I want the EA to be organised into clearly separated modules so that each concern can be developed, tested, and maintained independently.

#### Acceptance Criteria

1. THE EA SHALL implement the following independent modules: Market_Structure_Analyzer, Liquidity_Detector, Entry_Confirmation_Engine, Risk_Manager, Order_Executor, Session_Filter, Spread_Filter, News_Filter, State_Manager, and Logger.
2. THE Market_Structure_Analyzer, Liquidity_Detector, Session_Filter, Spread_Filter, and News_Filter SHALL communicate with THE Entry_Confirmation_Engine only through AnalysisStatus objects (containing: signal type, direction, confidence level as integer 0–100, and timestamp), with no direct reference to Risk_Manager or Order_Executor types or functions.
3. THE Entry_Confirmation_Engine SHALL pass approved trade signals to THE Risk_Manager only through a TradeSignal data structure; IF any required TradeSignal field (entry price, stop-loss price, take-profit price, direction) is zero, null, or undefined, THEN THE Entry_Confirmation_Engine SHALL discard the signal and log the invalid field before passing it.
4. THE Risk_Manager SHALL pass approved trade instructions to THE Order_Executor only through a TradeOrder data structure containing: symbol, order type, volume, entry price, stop-loss price, take-profit price, and timestamp; IF the Risk_Manager rejects a TradeSignal, it SHALL return a rejection response identifying the unmet criterion and SHALL NOT create a TradeOrder.
5. THE Order_Executor SHALL be the only module permitted to call MT5 trade execution functions (OrderSend, OrderModify, OrderClose); no other module SHALL call these functions directly.
6. THE Logger SHALL be implemented as a stateless utility callable from all modules; it SHALL NOT hold references to any other module to prevent circular dependencies.
7. THE EA code SHALL be organised as one MQL5 include file per module (e.g., MarketStructureAnalyzer.mqh, LiquidityDetector.mqh), with the main EA file including each module file exactly once.

---

### Requirement 14: Configuration Management

**User Story:** As a trader, I want all strategy and risk parameters to be configurable through the EA's input parameters so that I can adjust behaviour without recompiling the EA.

#### Acceptance Criteria

1. THE EA SHALL expose all configurable parameters as MQL5 input variables accessible from the MetaTrader 5 Strategy Tester and live EA settings panel.
2. THE EA SHALL validate all input parameters at initialisation (OnInit); IF any parameter is outside its defined valid range — where numeric parameters must be within their documented min/max bounds, enumeration parameters must be one of their documented valid values, and time parameters must represent valid clock times — THEN THE EA SHALL log an error with the parameter name, submitted value, and valid range, and SHALL return INIT_FAILED to abort initialisation.
3. THE EA SHALL group input parameters by module using MQL5 input group separators, with one group per module (e.g., "=== Risk Settings ===", "=== Session Settings ===", "=== Structure Settings ==="); each module's parameters SHALL appear under exactly one group heading.
4. THE EA SHALL obtain the following five symbol properties from Symbol_Properties at runtime and SHALL NOT hardcode them: point size (SYMBOL_POINT), lot step (SYMBOL_VOLUME_STEP), contract size (SYMBOL_TRADE_CONTRACT_SIZE), minimum stop level in points (SYMBOL_TRADE_STOPS_LEVEL), and required margin per lot (SYMBOL_MARGIN_INITIAL).
5. IF any of the five mandatory symbol properties listed in criterion 4 cannot be read from Symbol_Properties, THEN THE EA SHALL log an error identifying the specific property that failed and SHALL return INIT_FAILED to abort initialisation.

---

### Requirement 15: No Prohibited Trading Practices

**User Story:** As a trader, I want the EA to be free from all prohibited high-risk trading practices so that the system manages capital responsibly.

#### Acceptance Criteria

1. IF a trade results in a loss, THEN THE Risk_Manager SHALL NOT increase the position size of the next trade relative to what the fixed Risk_Per_Trade_Percent formula would produce for that trade independently; prohibited patterns include doubling position size, multiplying position size by any factor greater than 1.0, and adding any fixed increment to position size — all solely as a consequence of a prior loss.
2. IF an existing position in the same direction has an unrealised loss, THEN THE Risk_Manager SHALL evaluate any new entry signal independently of that position's unrealised P&L or entry price; the new signal SHALL be approved or rejected based solely on its own entry, stop-loss, take-profit, and the combined position risk limit defined in Requirement 9.
3. THE EA SHALL NOT place a pre-defined ladder of orders at fixed price intervals in either direction (grid trading).
4. IF a prior trade has been closed at a loss, THEN THE EA SHALL NOT open a new position whose sole observable trigger is that prior realised loss rather than an independent entry signal satisfying all entry criteria.
5. THE Market_Structure_Analyzer, Liquidity_Detector, and Entry_Confirmation_Engine SHALL read all indicator and price values exclusively from bar index ≥ 1; no module SHALL read data from bar index 0 or any future bar for any decision that triggers or suppresses a trade.
6. IF a non-repainting indicator is used for entry decisions, THEN the EA source code SHALL contain a comment in the indicator's configuration block explicitly documenting the indicator as non-repainting and confirming that values are read from bar index ≥ 1.

---

### Requirement 16: Back-testing and Research Architecture (Python)

**User Story:** As a developer, I want a Python research environment that mirrors the EA's logic so that strategy concepts can be validated and analysed before being coded into MQL5.

#### Acceptance Criteria

1. THE Python_Research_Env SHALL implement all core strategy logic (market structure analysis, liquidity detection, entry confirmation, risk calculation) as independently importable and unit-testable Python modules, each exposing a public interface that mirrors the corresponding MQL5 module's inputs and outputs.
2. THE Python_Research_Env SHALL ingest historical OHLCV data for XAUUSD from a configurable source (CSV files or MT5 Python API) at all four required timeframes (4H, 1H, 15M, 5M).
3. THE Python_Research_Env SHALL apply the same no-look-ahead rule as the MQL5 EA: all decisions at bar index N SHALL use only OHLCV data available at bar index N−1 or earlier; the back-test engine SHALL enforce this by slicing data up to and excluding the current bar before passing it to any strategy module.
4. WHEN a trade is generated during back-testing, THE Python_Research_Env SHALL write a trade log record containing: entry timestamp, exit timestamp, direction, entry price, exit price, stop-loss price, take-profit price, position size, realised P&L, exit reason (stop-loss / take-profit / manual close), and all active filter states at entry time.
5. THE Python_Research_Env SHALL include a parameter sensitivity analysis tool that sweeps configurable ranges of key parameters and produces for each combination: total return, maximum drawdown, Sharpe ratio, win rate, profit factor, and the number of trades; the output SHALL be written to a structured CSV or JSON file for further analysis.
6. IF a parameter combination produces a maximum drawdown greater than a configurable threshold during back-testing (default: 20%, valid range: 5%–50%), THEN THE Python_Research_Env SHALL mark that row in the sensitivity output with a FLAGGED label and SHALL exclude it from any automatically generated "best parameter" ranking.

---

### Requirement 17: Live Trading Safety Architecture

**User Story:** As a trader, I want a set of hard safety controls that prevent the EA from causing runaway losses regardless of strategy behaviour, so that I can deploy it with confidence.

#### Acceptance Criteria

1. THE EA SHALL implement a hard-stop circuit breaker: WHEN total account drawdown from the floating equity snapshot captured at OnInit exceeds the configured total drawdown limit, THE EA SHALL close all open positions and disable itself within the same tick-processing cycle, and log a CRITICAL alert.
2. THE EA SHALL implement a daily reset mechanism: WHEN the trading day changes — detected when broker server time crosses midnight UTC, or on the first tick after the EA was inactive at midnight — THE State_Manager SHALL reset the daily drawdown accumulator to zero and record the current floating account equity as the new day-open equity reference.
3. WHEN the EA is disabled by a safety circuit breaker, THE EA SHALL require manual re-enablement by the trader (e.g., removing and re-attaching the EA to the chart); THE EA SHALL NOT automatically re-enable itself.
4. WHILE the EA is running, THE Order_Executor SHALL verify that every open trade managed by the EA (identified by Magic_Number) has a valid Protective_Stop during each OnTick or OnTimer execution cycle; IF a stop is missing, THEN THE Order_Executor SHALL attempt to re-attach it immediately and log a CRITICAL error.
5. IF the re-attachment of a missing stop-loss fails, THEN THE Order_Executor SHALL close the unprotected position immediately and log a CRITICAL error identifying the ticket number, attempted stop-loss level, and MT5 error code.
6. THE EA SHALL implement a maximum consecutive loss counter; WHEN the number of consecutive losing trades reaches a configurable limit (valid range: 2–20, default: 5), THE EA SHALL pause new entry signals for a configurable cooldown period (valid range: 1–168 hours, default: 24 hours); the cooldown start time SHALL be persisted to the state file so that it survives a terminal restart.
7. THE EA SHALL monitor account free margin; WHILE free margin falls below a configurable minimum margin threshold (default: 150% of required margin for all open positions combined, valid range: 110%–500%), THE Entry_Confirmation_Engine SHALL block new entries and THE Logger SHALL write a WARNING log entry.

---

### Requirement 18: Take-Profit Selection and Static Stop-Loss Management

**User Story:** As a trader, I want the EA to determine take-profit targets using deterministic rules based on opposing liquidity pools, and to keep the initial stop-loss fixed for the lifetime of each position, so that trade management is predictable and auditable.

#### Acceptance Criteria

**Take-Profit Selection (BLOCKER-2 resolution):**
1. WHEN constructing a TradeSignal, THE Entry_Confirmation_Engine SHALL select the take-profit price as the nearest Active opposing Liquidity_Pool whose distance from the Execution_Entry_Price satisfies the configured minimum R:R requirement.
2. "Nearest opposing Liquidity_Pool" is defined as: the Active pool on the opposite side of the trade (above entry for SELL, below entry for BUY) whose price level is closest to the Execution_Entry_Price among all qualifying candidates.
3. A Liquidity_Pool is a qualifying TP candidate IF AND ONLY IF its distance from the Execution_Entry_Price is at least `MinRR × |Execution_Entry_Price − StopLossPrice|`.
4. IF no Active opposing Liquidity_Pool satisfies the minimum R:R requirement at signal generation time, THEN THE Entry_Confirmation_Engine SHALL reject the signal with reason NO_VALID_TP and log the closest pool distance, the minimum required distance, and the computed R:R shortfall.
5. BOS/CHOCH price levels SHALL NOT be used as take-profit targets; they are used only for directional confirmation and regime analysis.
6. THE Entry_Confirmation_Engine SHALL NOT force a trade by accepting a substandard R:R; the minimum R:R is a hard gate.
7. THE Entry_Confirmation_Engine SHALL log the selected TP price level, the pool that provided it, the computed R:R, and the next-nearest rejected pool (if any) for audit purposes.

**Static Stop-Loss Management (BLOCKER-3 resolution):**
8. THE EA V1 SHALL use a static stop-loss only: the SL is calculated once before order submission and SHALL NOT be modified for the lifetime of the position.
9. THE EA V1 SHALL NOT implement trailing stop-loss.
10. THE EA V1 SHALL NOT implement break-even stop moves.
11. THE EA V1 SHALL NOT implement partial take-profit.
12. THE EA V1 SHALL NOT implement position averaging (adding to a position after entry).
13. WHEN a position is open, THE Order_Executor SHALL monitor that the original stop-loss level remains intact. Any external modification of the stop-loss level detected by the Order_Executor SHALL be logged at WARN level with the original and modified values.

---

### Requirement 19: State File Format and Integrity (BLOCKER-4 resolution)

**User Story:** As a trader, I want the EA's persistent state to use a reliable, self-contained native MQL5 format with integrity checking so that the EA can detect corruption, recover safely, and never silently operate on bad state.

#### Acceptance Criteria

1. THE State_Manager SHALL persist EA operational state to a plain-text file using a structured key-value format natively readable and writable by MQL5 file I/O functions, with one field per line in the format `KEY=VALUE`.
2. THE state file SHALL begin with the following mandatory header fields in this exact order: `VERSION`, `SCHEMA`, `TIMESTAMP_UTC`, `SYMBOL`, `ACCOUNT_SUFFIX` (last 4 digits of account number only).
3. THE state file SHALL include a `CHECKSUM` field as the final line, containing a CRC32 value computed over all preceding lines of the file (excluding the CHECKSUM line itself); THE State_Manager SHALL verify this checksum on every read.
4. IF the checksum verification fails, or if any mandatory field is missing or unparseable, THEN THE State_Manager SHALL enter SAFE_MODE: block all new entries, log a CRITICAL alert with the specific validation failure, persist `SAFE_MODE=1` to a separate sentinel file, and require manual intervention to clear.
5. IF the `VERSION` field in the state file does not match the current EA `STATE_FILE_VERSION` constant, THEN THE State_Manager SHALL: if the version is older and a migration path is defined, apply the migration and write the updated file; if no migration path is defined, enter SAFE_MODE.
6. THE state file SHALL persist the Liquidity_Pool registry as a dedicated section beginning with the line `[POOL_REGISTRY]`, followed by one pool record per line in CSV format: `pool_index,price_level,tolerance_band,status,side,created_timestamp_utc,swept_timestamp_utc`; the section ends at the next section header or end of file.
7. THE State_Manager SHALL write the state file atomically: first write to a temporary file with suffix `.tmp`, then rename to the final path; if the rename fails, log an ERROR and retain the previous state file.
8. THE State_Manager SHALL validate that `SYMBOL` and `ACCOUNT_SUFFIX` in the state file match the currently running EA instance before restoring state; a mismatch SHALL trigger SAFE_MODE.
9. IF the state file is absent at EA initialisation and no `.tmp` file exists, THEN THE State_Manager SHALL create a new state file with default values and log an INFO entry (not an error) indicating a fresh start.
10. IF a `.tmp` state file exists at initialisation (indicating a previously interrupted write), THEN THE State_Manager SHALL attempt to validate and use the `.tmp` file before falling back to the main state file.

---

### Requirement 20: Python Backtest Slippage Model (BLOCKER-5 resolution)

**User Story:** As a developer, I want the Python backtesting environment to model execution costs using two independently configurable slippage modes so that strategy performance can be evaluated under both normal and conservative assumptions without optimistic bias.

#### Acceptance Criteria

1. THE Python_Research_Env SHALL implement two configurable slippage modes for trade fill simulation:
   - **MODE A (Fixed):** Fill price = next bar's open price ± a configurable fixed number of points (`SlippageFixedPoints`, default: 2 points); positive for BUY, negative for SELL.
   - **MODE B (Variable):** Fill price = next bar's open price ± a draw from a half-normal distribution with configurable mean (`SlippageMeanPoints`, default: 2) and standard deviation (`SlippageStdDevPoints`, default: 3); the sign is always adverse (positive cost for BUY, positive cost for SELL).
2. THE Python_Research_Env SHALL additionally apply a configurable fixed commission cost per trade expressed in account currency (`CommissionPerLot`, default: 7.0 per lot round-turn) deducted at trade open.
3. WHEN a sensitivity analysis or walk-forward run is executed, THE Python_Research_Env SHALL produce three separate result sets using the same parameter combination: Base (MODE A with SlippageFixedPoints = 0, no commission), Conservative (MODE A with configured SlippageFixedPoints and CommissionPerLot), and Stress (MODE B with configured mean/std dev and CommissionPerLot × 1.5).
4. THE Python_Research_Env SHALL label all output reports with the slippage mode and parameter values used; reports from different modes SHALL NOT be mixed or averaged.
5. THE Python_Research_Env SHALL NOT select or rank parameter combinations based on Base results alone; the Conservative result set SHALL be used for all "best parameter" rankings.
6. IF the Conservative maximum drawdown for a parameter combination exceeds the `FlagDrawdownThreshold`, THEN the combination SHALL be flagged regardless of Base results.
7. All slippage and commission parameters SHALL be configurable via the YAML config file and visible in every output report header.
