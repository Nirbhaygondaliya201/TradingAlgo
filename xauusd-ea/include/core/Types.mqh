//+------------------------------------------------------------------+
//| Types.mqh                                                        |
//| XAU/USD MT5 Expert Advisor                                       |
//| All shared struct and enum definitions.                          |
//|                                                                  |
//| ARCHITECTURE: Layer 0 (no dependencies).                         |
//| This file is included by every module exactly once (via the      |
//| main EA file). It must not include any other project file.       |
//|                                                                  |
//| Design reference: §Data Models                                   |
//| Requirements: 13.1, 13.7, 14.1                                   |
//+------------------------------------------------------------------+
#pragma once

//+------------------------------------------------------------------+
//| Enumerations                                                     |
//+------------------------------------------------------------------+

/// Direction of a trade signal, swing, BOS, or liquidity event.
enum Direction
{
    DIRECTION_NONE  = 0,  // No directional bias / not applicable
    DIRECTION_LONG  = 1,  // Bullish / Buy direction
    DIRECTION_SHORT = 2   // Bearish / Sell direction
};

/// Signal type emitted by analysis engines and filters to the
/// Entry_Confirmation_Engine via AnalysisStatus.
enum SignalType
{
    SIGNAL_SWEEP_LONG      = 0,  // Liquidity sweep in bullish direction confirmed
    SIGNAL_SWEEP_SHORT     = 1,  // Liquidity sweep in bearish direction confirmed
    SIGNAL_BOS_LONG        = 2,  // Break of Structure — bullish
    SIGNAL_BOS_SHORT       = 3,  // Break of Structure — bearish
    SIGNAL_CHOCH_LONG      = 4,  // Change of Character — bullish (BOS vs prior bearish regime)
    SIGNAL_CHOCH_SHORT     = 5,  // Change of Character — bearish (BOS vs prior bullish regime)
    SIGNAL_REGIME_BULLISH  = 6,  // 4H regime classified Bullish
    SIGNAL_REGIME_BEARISH  = 7,  // 4H regime classified Bearish
    SIGNAL_REGIME_RANGING  = 8,  // 4H regime classified Ranging
    SIGNAL_FILTER_ALLOWED  = 9,  // Filter gate: entry is permitted
    SIGNAL_FILTER_BLOCKED  = 10, // Filter gate: entry is blocked
    SIGNAL_FILTER_WARN     = 11, // Filter gate: warning — entry permitted with caveat
    SIGNAL_UNKNOWN         = 12  // Data unavailable or status indeterminate
};

/// Lifecycle status of a LiquidityPool.
enum PoolStatus
{
    POOL_ACTIVE      = 0, // Pool is active and eligible for sweep detection
    POOL_SWEPT       = 1, // Pool has been swept; no further sweep signals for this pool
    POOL_INVALIDATED = 2  // Pool invalidated (price closed beyond tolerance without sweep)
};

/// Output status of the ATR_Volatility_Engine filter.
enum ATRFilterStatus
{
    ATR_ALLOW      = 0, // Current ATR within normal bounds — entries permitted
    ATR_BLOCK_LOW  = 1, // ATR below minimum threshold — entries blocked
    ATR_BLOCK_HIGH = 2, // ATR above maximum threshold — entries blocked
    ATR_UNAVAILABLE = 3 // ATR data unavailable — entries blocked
};

/// Result status of the Momentum_Engine.
enum MomentumStatus
{
    MOMENTUM_CONFIRMED        = 0, // Momentum confirms the proposed trade direction
    MOMENTUM_REJECTED         = 1, // Momentum does not confirm the direction
    MOMENTUM_INSUFFICIENT_DATA = 2 // Fewer than N candles available or range is zero
};

/// Execution outcome returned by the Order_Executor after an OrderSend attempt.
enum ExecutionStatus
{
    EXEC_FILLED   = 0, // Order filled successfully
    EXEC_REJECTED = 1, // Order rejected by broker (fatal error)
    EXEC_FAILED   = 2  // Order failed after retries (non-fatal errors exhausted)
};

/// Order type used in TradeOrder — only market orders are supported in V1.
enum OrderType
{
    ORDER_MARKET_BUY  = 0, // Market Buy (Long entry)
    ORDER_MARKET_SELL = 1  // Market Sell (Short entry)
};

/// Type of a confirmed swing point.
enum SwingType
{
    SWING_HIGH = 0, // Local high extremum
    SWING_LOW  = 1  // Local low extremum
};

/// Side of a LiquidityPool relative to price: above (resistance) or below (support).
enum PoolSide
{
    POOL_SIDE_ABOVE = 0, // Pool located above price (sell-side liquidity)
    POOL_SIDE_BELOW = 1  // Pool located below price (buy-side liquidity)
};

/// EA operational state machine states.
enum EAOperationalState
{
    EA_STATE_INITIALISING     = 0, // OnInit in progress
    EA_STATE_RUNNING          = 1, // Normal trading operation
    EA_STATE_SAFE_MONITORING  = 2, // Connection lost or state integrity failure — no new entries
    EA_STATE_DAILY_CIRCUIT    = 3, // Daily drawdown limit reached — entries blocked until midnight
    EA_STATE_COOLDOWN         = 4, // Consecutive loss cooldown active — entries blocked
    EA_STATE_HARD_DISABLED    = 5  // Total drawdown circuit breaker fired — manual re-enable required
};

//+------------------------------------------------------------------+
//| Core Interface Structs                                           |
//+------------------------------------------------------------------+

/// AnalysisStatus — the only communication channel from each analysis
/// engine and filter module to the Entry_Confirmation_Engine.
/// No module may directly reference Risk_Manager or Order_Executor types.
/// Requirement 13.2
struct AnalysisStatus
{
    SignalType  signal_type;       // What this status represents
    Direction   direction;         // Directional component (NONE for filters)
    int         confidence;        // 0–100; reserved for future use; default 100
    datetime    timestamp;         // UTC broker server time of the event
    string      source_module;     // Module name — for logging and traceability
    string      rejection_reason;  // Populated when BLOCKED or UNKNOWN; empty otherwise
};

/// TradeSignal — produced by Entry_Confirmation_Engine, consumed by Risk_Manager.
/// BLOCKER-1: entry_price is the LIVE Ask/Bid at signal generation time —
///            never the triggering candle's close (that is signal_reference_price).
/// BLOCKER-2: take_profit_price is always the nearest Active opposing
///            Liquidity_Pool satisfying MinRR. BOS/CHOCH levels are not TP targets.
///            If no qualifying pool exists the signal is rejected with NO_VALID_TP.
/// BLOCKER-3: stop_loss_price is STATIC — set once, never modified during position lifetime.
/// Requirement 13.3
struct TradeSignal
{
    double   entry_price;            // LIVE Ask (BUY) or Bid (SELL) at signal generation time
    double   signal_reference_price; // Confirming candle close — for audit/logging only
    double   stop_loss_price;        // Non-zero; below entry (long) or above entry (short); STATIC
    double   take_profit_price;      // Nearest Active opposing Liquidity_Pool satisfying MinRR
    Direction direction;             // LONG or SHORT
    datetime signal_timestamp;       // UTC broker server time at signal generation
    double   atr_at_signal;          // 1H ATR at signal time — for audit
    int      regime;                 // 4H regime at signal time (cast from SignalType) — for audit
    double   computed_rr;            // |TP − entry| / |entry − SL| at generation time — for audit
    string   tp_pool_level;          // Price level string of selected TP pool — for audit
    string   rejection_reason;       // Populated on rejection (e.g., "NO_VALID_TP"); empty on approval
};

/// TradeOrder — produced by Risk_Manager, consumed only by Order_Executor.
/// The Order_Executor re-reads the live Ask/Bid immediately before OrderSend;
/// entry_price here is used for deviation checking, not as the exact submission price.
/// Requirement 13.4
struct TradeOrder
{
    string    symbol;                // Symbol name (e.g., "XAUUSD")
    OrderType order_type;            // MARKET_BUY or MARKET_SELL
    double    volume;                // Validated lot size (rounded to LotStep, within [MinLot, MaxLot])
    double    entry_price;           // Live Ask/Bid from TradeSignal (re-read at OrderSend time)
    double    signal_reference_price;// Candle close that triggered signal — for audit only
    double    stop_loss_price;       // Validated against broker stop level; STATIC — never moved
    double    take_profit_price;     // Validated against broker stop level
    datetime  timestamp;             // UTC time of TradeOrder creation
    int       magic_number;          // EA Magic Number — from Constants.mqh
    double    max_slippage_points;   // Max acceptable slippage in points — from Config
};

/// ExecutionResult — returned by Order_Executor after each OrderSend attempt.
struct ExecutionResult
{
    ExecutionStatus status;          // FILLED, REJECTED, or FAILED
    long     ticket;                 // MT5 order ticket (0 if not filled)
    double   filled_price;           // Actual fill price
    double   filled_sl;              // Actual SL on the filled order
    double   filled_tp;              // Actual TP on the filled order
    int      mt5_error_code;         // 0 on success; MT5 error code on failure
    string   error_description;      // Human-readable error description
    datetime execution_timestamp;    // UTC time of fill or final failure
};

/// RejectionResult — returned by Risk_Manager when a TradeSignal fails validation.
struct RejectionResult
{
    string   unmet_criterion;  // Name of the first failing check (e.g., "R:R below minimum")
    double   computed_value;   // The value that failed (e.g., the actual R:R)
    double   required_value;   // The threshold or limit
    datetime timestamp;        // UTC time of rejection
};

/// SymbolProperties — populated once at OnInit from MT5 Symbol_Properties API.
/// Immutable after successful initialisation.
/// All broker-specific values are read dynamically — nothing is hardcoded.
/// Requirements 14.4, 14.5
struct SymbolProperties
{
    double   point;              // SYMBOL_POINT — smallest price increment
    double   lot_step;           // SYMBOL_VOLUME_STEP — minimum lot increment
    double   min_lot;            // SYMBOL_VOLUME_MIN
    double   max_lot;            // SYMBOL_VOLUME_MAX
    double   contract_size;      // SYMBOL_TRADE_CONTRACT_SIZE — units per lot (100 oz for XAU)
    int      stop_level_points;  // SYMBOL_TRADE_STOPS_LEVEL — minimum SL/TP distance in points
    int      freeze_level_points;// SYMBOL_TRADE_FREEZE_LEVEL — freeze zone width in points
    double   tick_size;          // SYMBOL_TRADE_TICK_SIZE
    double   tick_value;         // SYMBOL_TRADE_TICK_VALUE — P&L per tick per lot
    int      digits;             // SYMBOL_DIGITS — price decimal places
    double   margin_initial;     // SYMBOL_MARGIN_INITIAL — required margin per lot
    bool     is_valid;           // Set to true after all mandatory properties validated
};

/// OHLCVBar — a single confirmed candle.
/// GUARANTEED: this struct is only ever populated from bar index ≥ 1 (never bar 0).
/// The MultiTimeframe_DataFeed enforces this at the data-access layer.
/// Correctness Property 1
struct OHLCVBar
{
    datetime time;        // Bar open time (UTC)
    double   open;
    double   high;
    double   low;
    double   close;
    long     tick_volume; // Tick count for the bar period
};

/// SwingPoint — a confirmed local price extremum.
/// Pending (unconfirmed) candidates are never exposed in this struct.
/// A SwingPoint is only created once it has ≥ SwingSideCandles confirmed candles on each side.
struct SwingPoint
{
    datetime  time;       // Timestamp of the swing candle
    double    price;      // High price (SWING_HIGH) or Low price (SWING_LOW)
    SwingType type;       // HIGH or LOW
    int       timeframe;  // MT5 PERIOD_H4, PERIOD_H1, PERIOD_M15, or PERIOD_M5
    bool      confirmed;  // Always true — pending swings are never stored here
};

/// LiquidityPool — a zone of clustered swing highs or lows (equal highs / equal lows).
/// The tolerance_band is locked at creation time from the ATR at that moment;
/// subsequent ATR changes do NOT resize an existing pool.
struct LiquidityPool
{
    double     price_level;        // Average price of the clustered swing points
    double     tolerance_band;     // ATR × PoolATRTolerance at creation time (locked)
    PoolStatus status;             // ACTIVE, SWEPT, or INVALIDATED
    PoolSide   side;               // ABOVE (resistance) or BELOW (support)
    datetime   created_timestamp;  // UTC time the pool was first identified
    datetime   swept_timestamp;    // UTC time of sweep confirmation (0 if not swept)
    AnalysisStatus sweep_event;    // Sweep AnalysisStatus when swept; zero-initialised otherwise
};

/// ATRResult — output from ATR_Volatility_Engine.
struct ATRResult
{
    double        current_atr;     // Current period ATR value (1H, period = ATRPeriod)
    double        baseline_atr;    // 30-day average ATR (from 720 closed 1H candles)
    ATRFilterStatus status;        // ALLOW, BLOCK_LOW, BLOCK_HIGH, or UNAVAILABLE
    double        min_sl_distance; // max(current_atr × ATRSLMultiplier, stop_level_points × point)
};

/// MomentumResult — output from Momentum_Engine.
struct MomentumResult
{
    MomentumStatus status;          // CONFIRMED, REJECTED, or INSUFFICIENT_DATA
    double         range_high;      // High of the prior N-candle lookback window
    double         range_low;       // Low of the prior N-candle lookback window
    double         close_position_pct; // 0.0 = at range low; 1.0 = at range high
    string         rejection_reason;   // Populated on REJECTED or INSUFFICIENT_DATA
};

/// EAState — in-memory representation of all persisted EA state.
/// Serialised to a plain-text KEY=VALUE file with CRC32 integrity check.
/// BLOCKER-4: No external JSON library. Format defined in Requirement 19 and design §2.13.
struct EAState
{
    double   daily_drawdown_pct;        // Intraday loss as % of day-open equity
    double   daily_open_equity;         // Floating equity at broker server 00:00 UTC today
    double   total_drawdown_ref_equity; // Floating equity snapshot at OnInit (circuit breaker ref)
    int      consecutive_losses;        // Count of consecutive losing closed trades
    datetime cooldown_start_utc;        // UTC time cooldown started (0 if no cooldown active)
    bool     circuit_breaker_triggered; // True if total drawdown circuit breaker has fired
    bool     safe_mode_active;          // True if state file failed integrity check
    datetime last_update_utc;           // UTC time of last file write
    int      state_file_version;        // Schema version for forward-compatibility migration
    string   symbol;                    // Symbol this state belongs to (cross-check on load)
    string   account_suffix;            // Last 4 digits of account number (cross-check on load)
    uint     checksum;                  // CRC32 of all preceding fields (validated on every load)
};
//+------------------------------------------------------------------+
