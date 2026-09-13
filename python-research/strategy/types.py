"""
types.py — XAU/USD MT5 EA Python Research Environment
=======================================================
Python dataclass mirrors of every MQL5 struct and enum defined in
``include/core/Types.mqh`` (Task 1.1).

Design reference: §Data Models
Requirements: 16.1 (mirrors MQL5 module inputs/outputs)

IMPORTANT:
- All fields use the same names as the MQL5 structs so that
  cross-validation scripts can compare outputs field-by-field.
- ``datetime`` fields use Python ``datetime`` objects (UTC-aware
  where possible) matching the MQL5 ``datetime`` (seconds since epoch).
- Enum integer values match the MQL5 enum values exactly.
- No trading logic lives here. This file is data-structure-only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
from typing import Optional


# ---------------------------------------------------------------------------
# Enumerations (integer values MUST match MQL5 Types.mqh)
# ---------------------------------------------------------------------------

class Direction(IntEnum):
    """Direction of a trade signal, swing, BOS, or liquidity event."""
    NONE  = 0  # No directional bias / not applicable
    LONG  = 1  # Bullish / Buy direction
    SHORT = 2  # Bearish / Sell direction


class SignalType(IntEnum):
    """Signal type emitted by analysis engines and filters."""
    SWEEP_LONG      = 0   # Liquidity sweep in bullish direction confirmed
    SWEEP_SHORT     = 1   # Liquidity sweep in bearish direction confirmed
    BOS_LONG        = 2   # Break of Structure — bullish
    BOS_SHORT       = 3   # Break of Structure — bearish
    CHOCH_LONG      = 4   # Change of Character — bullish
    CHOCH_SHORT     = 5   # Change of Character — bearish
    REGIME_BULLISH  = 6   # 4H regime classified Bullish
    REGIME_BEARISH  = 7   # 4H regime classified Bearish
    REGIME_RANGING  = 8   # 4H regime classified Ranging
    FILTER_ALLOWED  = 9   # Filter gate: entry is permitted
    FILTER_BLOCKED  = 10  # Filter gate: entry is blocked
    FILTER_WARN     = 11  # Filter gate: warning — entry permitted with caveat
    UNKNOWN         = 12  # Data unavailable or status indeterminate


class PoolStatus(IntEnum):
    """Lifecycle status of a LiquidityPool."""
    ACTIVE      = 0  # Pool is active and eligible for sweep detection
    SWEPT       = 1  # Pool has been swept; no further sweep signals for this pool
    INVALIDATED = 2  # Pool invalidated (close beyond tolerance without sweep)


class ATRFilterStatus(IntEnum):
    """Output status of the ATR_Volatility_Engine filter."""
    ALLOW       = 0  # Current ATR within normal bounds — entries permitted
    BLOCK_LOW   = 1  # ATR below minimum threshold — entries blocked
    BLOCK_HIGH  = 2  # ATR above maximum threshold — entries blocked
    UNAVAILABLE = 3  # ATR data unavailable — entries blocked


class MomentumStatus(IntEnum):
    """Result status of the Momentum_Engine."""
    CONFIRMED         = 0  # Momentum confirms the proposed trade direction
    REJECTED          = 1  # Momentum does not confirm the direction
    INSUFFICIENT_DATA = 2  # Fewer than N candles or range is zero


class ExecutionStatus(IntEnum):
    """Execution outcome returned after an OrderSend attempt."""
    FILLED   = 0  # Order filled successfully
    REJECTED = 1  # Order rejected by broker (fatal error)
    FAILED   = 2  # Order failed after retries (non-fatal errors exhausted)


class OrderType(IntEnum):
    """Order type — V1 supports market orders only."""
    MARKET_BUY  = 0  # Market Buy (Long entry)
    MARKET_SELL = 1  # Market Sell (Short entry)


class SwingType(IntEnum):
    """Type of a confirmed swing point."""
    HIGH = 0  # Local high extremum
    LOW  = 1  # Local low extremum


class PoolSide(IntEnum):
    """Side of a LiquidityPool relative to price."""
    ABOVE = 0  # Pool located above price (sell-side / resistance liquidity)
    BELOW = 1  # Pool located below price (buy-side / support liquidity)


class EAOperationalState(IntEnum):
    """EA operational state machine states."""
    INITIALISING    = 0  # OnInit in progress
    RUNNING         = 1  # Normal trading operation
    SAFE_MONITORING = 2  # Connection lost or state integrity failure
    DAILY_CIRCUIT   = 3  # Daily drawdown limit reached
    COOLDOWN        = 4  # Consecutive loss cooldown active
    HARD_DISABLED   = 5  # Total drawdown circuit breaker fired


# ---------------------------------------------------------------------------
# Core interface dataclasses (mirror MQL5 structs from Types.mqh)
# ---------------------------------------------------------------------------

def _utc_zero() -> datetime:
    """Return the UTC epoch (1970-01-01 00:00:00 UTC) as a timezone-aware datetime."""
    return datetime(1970, 1, 1, tzinfo=timezone.utc)


@dataclass
class AnalysisStatus:
    """
    Output from each analysis engine / filter → input to Entry_Confirmation_Engine.
    Mirrors MQL5 ``struct AnalysisStatus``.
    Requirement 13.2
    """
    signal_type:      SignalType = SignalType.UNKNOWN
    direction:        Direction  = Direction.NONE
    confidence:       int        = 0         # 0–100; reserved for future use
    timestamp:        datetime   = field(default_factory=_utc_zero)
    source_module:    str        = ""        # Module name for logging/traceability
    rejection_reason: str        = ""        # Populated when BLOCKED or UNKNOWN


@dataclass
class TradeSignal:
    """
    Produced by Entry_Confirmation_Engine → consumed by Risk_Manager.
    Mirrors MQL5 ``struct TradeSignal``.

    BLOCKER-1: entry_price is the LIVE Ask/Bid at signal generation time —
               never the triggering candle's close (signal_reference_price).
    BLOCKER-2: take_profit_price is the nearest Active opposing Liquidity_Pool
               satisfying MinRR. BOS/CHOCH levels are not TP targets.
    BLOCKER-3: stop_loss_price is STATIC — set once, never modified.
    Requirement 13.3
    """
    entry_price:            float     = 0.0   # LIVE Ask (BUY) or Bid (SELL)
    signal_reference_price: float     = 0.0   # Confirming candle close — audit only
    stop_loss_price:        float     = 0.0   # Non-zero; STATIC for position lifetime
    take_profit_price:      float     = 0.0   # Nearest qualifying opposing pool
    direction:              Direction = Direction.NONE
    signal_timestamp:       datetime  = field(default_factory=_utc_zero)
    atr_at_signal:          float     = 0.0   # 1H ATR at signal time (audit)
    regime:                 int       = 0     # Cast from SignalType (audit)
    computed_rr:            float     = 0.0   # |TP−entry|/|entry−SL| (audit)
    tp_pool_level:          str       = ""    # TP pool price level string (audit)
    rejection_reason:       str       = ""    # Populated on rejection; empty on approval


@dataclass
class TradeOrder:
    """
    Produced by Risk_Manager → consumed only by Order_Executor.
    Mirrors MQL5 ``struct TradeOrder``.
    Requirement 13.4
    """
    symbol:                 str       = ""
    order_type:             OrderType = OrderType.MARKET_BUY
    volume:                 float     = 0.0   # Validated lot size
    entry_price:            float     = 0.0   # Live Ask/Bid (re-read at OrderSend time)
    signal_reference_price: float     = 0.0   # Candle close — audit only
    stop_loss_price:        float     = 0.0   # STATIC — never moved
    take_profit_price:      float     = 0.0
    timestamp:              datetime  = field(default_factory=_utc_zero)
    magic_number:           int       = 0
    max_slippage_points:    float     = 0.0


@dataclass
class ExecutionResult:
    """
    Returned by Order_Executor after each OrderSend attempt.
    Mirrors MQL5 ``struct ExecutionResult``.
    """
    status:               ExecutionStatus = ExecutionStatus.FAILED
    ticket:               int             = 0
    filled_price:         float           = 0.0
    filled_sl:            float           = 0.0
    filled_tp:            float           = 0.0
    mt5_error_code:       int             = 0
    error_description:    str             = ""
    execution_timestamp:  datetime        = field(default_factory=_utc_zero)


@dataclass
class RejectionResult:
    """
    Returned by Risk_Manager when a TradeSignal fails validation.
    Mirrors MQL5 ``struct RejectionResult``.
    """
    unmet_criterion: str      = ""   # First failing check name
    computed_value:  float    = 0.0  # The value that failed
    required_value:  float    = 0.0  # The threshold or limit
    timestamp:       datetime = field(default_factory=_utc_zero)


@dataclass(frozen=True)
class SymbolProperties:
    """
    Populated at session start from broker symbol properties.
    Mirrors MQL5 ``struct SymbolProperties``.
    In Python backtesting, values are loaded from ``default_config.yaml``.
    frozen=True enforces immutability after construction (§2.1: immutable after init).
    Requirements 14.4, 14.5
    """
    point:               float = 0.0  # Smallest price increment
    lot_step:            float = 0.0  # Minimum lot increment
    min_lot:             float = 0.0
    max_lot:             float = 0.0
    contract_size:       float = 0.0  # Units per lot (100 oz for XAU)
    stop_level_points:   int   = 0    # Min SL/TP distance in points
    freeze_level_points: int   = 0    # Freeze zone width in points
    tick_size:           float = 0.0
    tick_value:          float = 0.0  # P&L per tick per lot
    digits:              int   = 0    # Price decimal places
    margin_initial:      float = 0.0  # Required margin per lot
    is_valid:            bool  = False  # True after all mandatory fields validated


@dataclass
class OHLCVBar:
    """
    A single confirmed candle (bar index ≥ 1).
    Mirrors MQL5 ``struct OHLCVBar``.
    GUARANTEED: only populated from confirmed (non-forming) bars.
    Correctness Property 1.
    """
    time:        datetime = field(default_factory=_utc_zero)  # Bar open time (UTC)
    open:        float    = 0.0
    high:        float    = 0.0
    low:         float    = 0.0
    close:       float    = 0.0
    tick_volume: int      = 0


@dataclass
class SwingPoint:
    """
    A confirmed local price extremum.
    Mirrors MQL5 ``struct SwingPoint``.
    Pending swings are never stored in this struct.
    """
    time:      datetime  = field(default_factory=_utc_zero)
    price:     float     = 0.0
    type:      SwingType = SwingType.HIGH
    timeframe: int       = 0      # MT5 ENUM_TIMEFRAMES value
    confirmed: bool      = False  # Always True once stored here


@dataclass
class LiquidityPool:
    """
    A zone of clustered swing highs or lows (equal highs / equal lows).
    Mirrors MQL5 ``struct LiquidityPool``.
    tolerance_band is locked at creation time; subsequent ATR changes do NOT resize it.
    """
    price_level:       float      = 0.0
    tolerance_band:    float      = 0.0   # ATR × PoolATRTolerance at creation time (locked)
    status:            PoolStatus = PoolStatus.ACTIVE
    side:              PoolSide   = PoolSide.ABOVE
    created_timestamp: datetime   = field(default_factory=_utc_zero)
    swept_timestamp:   datetime   = field(default_factory=_utc_zero)  # Epoch = not swept
    sweep_event:       Optional["AnalysisStatus"] = None


@dataclass
class ATRResult:
    """
    Output from ATR_Volatility_Engine.
    Mirrors MQL5 ``struct ATRResult``.
    """
    current_atr:     float           = 0.0
    baseline_atr:    float           = 0.0   # 30-day average ATR
    status:          ATRFilterStatus = ATRFilterStatus.UNAVAILABLE
    min_sl_distance: float           = 0.0   # max(atr×multiplier, stop_level×point)


@dataclass
class MomentumResult:
    """
    Output from Momentum_Engine.
    Mirrors MQL5 ``struct MomentumResult``.
    """
    status:             MomentumStatus = MomentumStatus.INSUFFICIENT_DATA
    range_high:         float          = 0.0
    range_low:          float          = 0.0
    close_position_pct: float          = 0.0  # 0.0 = at range low; 1.0 = at range high
    rejection_reason:   str            = ""


@dataclass
class EAState:
    """
    In-memory representation of all persisted EA state.
    Mirrors MQL5 ``struct EAState``.
    Serialised to plain-text KEY=VALUE file with CRC32 checksum (BLOCKER-4).
    """
    daily_drawdown_pct:        float    = 0.0
    daily_open_equity:         float    = 0.0
    total_drawdown_ref_equity: float    = 0.0
    consecutive_losses:        int      = 0
    cooldown_start_utc:        datetime = field(default_factory=_utc_zero)  # Epoch = no cooldown
    circuit_breaker_triggered: bool     = False
    safe_mode_active:          bool     = False
    last_update_utc:           datetime = field(default_factory=_utc_zero)
    state_file_version:        int      = 0
    symbol:                    str      = ""
    account_suffix:            str      = ""   # Last 4 digits of account number
    checksum:                  int      = 0    # CRC32 of all preceding fields
