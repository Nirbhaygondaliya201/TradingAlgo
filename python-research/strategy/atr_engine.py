"""
atr_engine.py — XAU/USD MT5 EA Python Research Environment
============================================================
ATR Volatility Engine — Python mirror of MQL5 ATRVolatilityEngine.mqh.

Implements the same methodology as the MQL5 module:
  - True Range:  TR(i) = max(H-L, |H-PrevC|, |L-PrevC|)
  - Seed ATR:    simple average of first `atr_period` TR values (oldest bars)
  - Wilder's RMA: ATR_n = (ATR_{n-1} × (period-1) + TR_n) / period

Input:
  - List/sequence of OHLCVBar objects, newest-first (bars[0] = most recently
    closed, bars[-1] = oldest). MUST be confirmed bars only (no bar index 0).
  - All configuration parameters passed explicitly — no hardcoded values.

Output:
  - ATRResult dataclass with: current_atr, baseline_atr, status, min_sl_distance

Confirmed-candle guarantee:
  - The function only operates on the bars list it receives.
  - The DataFeed layer is responsible for never passing bar[0].
  - This module never calls ConfirmedCandleFeed or any MT5 API directly.

Design reference: §2.5 ATR_Volatility_Engine
Requirements: 5.1–5.6
Correctness Properties: 1, 10, 11
"""

from __future__ import annotations

import math
from typing import List, Optional, Sequence

from strategy.types import ATRFilterStatus, ATRResult, OHLCVBar

# Constants matching MQL5 Constants.mqh
ATR_BASELINE_MIN_BARS    = 14
ATR_BASELINE_WINDOW_BARS = 720


# ---------------------------------------------------------------------------
# True Range
# ---------------------------------------------------------------------------

def compute_true_range(high: float, low: float,
                       close: float, prev_close: float) -> float:
    """
    TR = max(H-L, |H-PrevClose|, |L-PrevClose|)
    Matches MQL5 ATRVolatilityEngine::ComputeTrueRange() exactly.
    """
    hl  = high - low
    hpc = abs(high - prev_close)
    lpc = abs(low  - prev_close)
    return max(hl, hpc, lpc)


# ---------------------------------------------------------------------------
# ATR calculation
# ---------------------------------------------------------------------------

def calculate_atr(
    bars:           Sequence[OHLCVBar],
    atr_period:     int   = 14,
    atr_min_mult:   float = 0.5,
    atr_max_mult:   float = 2.5,
    atr_sl_mult:    float = 1.5,
    stop_level_pts: int   = 0,
    point_size:     float = 0.01,
    baseline_window:int   = ATR_BASELINE_WINDOW_BARS,
) -> ATRResult:
    """
    Compute ATR + filter status from a confirmed candle sequence.

    Parameters
    ----------
    bars            : Sequence of OHLCVBar, newest-first (bars[0] = latest
                      confirmed candle). Must NOT include bar index 0.
    atr_period      : Lookback period (valid: 5–50, default: 14)
    atr_min_mult    : Block-low multiplier vs baseline (default: 0.5)
    atr_max_mult    : Block-high multiplier vs baseline (default: 2.5)
    atr_sl_mult     : Minimum SL = ATR × this (default: 1.5)
    stop_level_pts  : Broker min stop level in points (from SymbolProperties)
    point_size      : Symbol point size (from SymbolProperties)
    baseline_window : Bars used for baseline ATR (default: 720)

    Returns
    -------
    ATRResult with status=UNAVAILABLE on any failure.
    """
    _unavail = ATRResult(
        current_atr    = 0.0,
        baseline_atr   = 0.0,
        status         = ATRFilterStatus.UNAVAILABLE,
        min_sl_distance= 0.0,
    )

    # --- Input validation ---
    if not (5 <= atr_period <= 50):
        return _unavail

    n = len(bars)
    if n == 0:
        return _unavail

    # Need at least atr_period + 1 bars (for atr_period TR values which
    # each require a previous close)
    required = atr_period + 1
    if n < required:
        return _unavail

    # --- Compute True Range for all bars ---
    # bars is newest-first; TR(i) uses bars[i] and prev close = bars[i+1].close
    tr_count = n - 1
    tr_values: List[float] = []

    for i in range(tr_count):
        b   = bars[i]
        bpv = bars[i + 1]

        # Basic OHLC sanity
        if (b.high < b.low or b.close <= 0.0 or b.open <= 0.0 or bpv.close <= 0.0
                or not math.isfinite(b.high) or not math.isfinite(b.low)
                or not math.isfinite(b.close) or not math.isfinite(bpv.close)):
            return _unavail

        tr = compute_true_range(b.high, b.low, b.close, bpv.close)
        tr_values.append(tr)

    if len(tr_values) < atr_period:
        return _unavail

    # --- Seed ATR: simple average of the oldest atr_period TR values ---
    # tr_values[0] = TR for bars[0] (newest), tr_values[-1] = TR for bars[-2].
    # "Oldest" = last atr_period values in the list.
    seed_trs = tr_values[-atr_period:]
    seed_sum = sum(seed_trs)
    if seed_sum <= 0.0 or not math.isfinite(seed_sum):
        return _unavail

    atr_val = seed_sum / atr_period

    # --- Wilder's RMA: walk from oldest toward newest ---
    # After seeding on the last atr_period TRs, apply RMA on all
    # remaining (newer) TRs from (tr_count - atr_period - 1) down to 0.
    remaining = tr_values[: tr_count - atr_period]  # newer TRs, oldest first reversed
    remaining.reverse()  # now oldest-first among the remaining
    remaining.reverse()  # cancel — we want newest-last → apply from oldest to newest

    # remaining = tr_values[0 : tr_count - atr_period], which is the newer part.
    # Walk it from its last element (oldest of the newer portion) to index 0 (newest).
    newer_trs = tr_values[: tr_count - atr_period]
    for tr in reversed(newer_trs):
        atr_val = ((atr_val * (atr_period - 1)) + tr) / atr_period

    if atr_val <= 0.0 or not math.isfinite(atr_val):
        return _unavail

    # --- Baseline ATR: simple average of up to baseline_window TR values ---
    baseline_count = min(tr_count, baseline_window)
    if baseline_count < ATR_BASELINE_MIN_BARS:
        # Use what we have (design: log warning, use available, min 14)
        pass
    baseline_sum = sum(tr_values[:baseline_count])
    baseline_atr = baseline_sum / baseline_count if baseline_count > 0 else 0.0

    if baseline_atr <= 0.0 or not math.isfinite(baseline_atr):
        return _unavail

    # --- Filter status (inclusive bounds → equal = ALLOW) ---
    if atr_val < baseline_atr * atr_min_mult:
        status = ATRFilterStatus.BLOCK_LOW
    elif atr_val > baseline_atr * atr_max_mult:
        status = ATRFilterStatus.BLOCK_HIGH
    else:
        status = ATRFilterStatus.ALLOW

    # --- Minimum SL distance ---
    atr_floor    = atr_val * atr_sl_mult
    broker_floor = stop_level_pts * point_size
    min_sl       = max(atr_floor, broker_floor)

    return ATRResult(
        current_atr    = atr_val,
        baseline_atr   = baseline_atr,
        status         = status,
        min_sl_distance= min_sl,
    )
