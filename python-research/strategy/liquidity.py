"""
liquidity.py — XAU/USD MT5 EA Python Research Environment
==========================================================
Liquidity Detection Engine — Python mirror of MQL5 LiquidityDetector.mqh.

SCOPE (exactly as documented in design §2.4):
  - Detect Liquidity_Pool zones: ≥ 2 confirmed swing H/L within ATR tolerance
  - Detect Liquidity_Sweep events (wick-through + confirmed close-back)
  - Manage pool lifecycle: Active → Swept / Active → Invalidated
  - Cap pool registry at MaxActivePools per direction
  - Suspend detection when ATR unavailable

NOT IN SCOPE:
  - BOS, CHOCH, regime, momentum, entry signals, execution

CONFIRMED-CANDLE GUARANTEE:
  bars[0] = most recently CLOSED candle.
  bar at as_of_index (the forming candle) is NEVER passed to this module.
  Pool confirmation timestamp = bars[0].time (last right-side confirm bar),
  NOT the swing candle's time. This prevents look-ahead / repainting.

NO-REPAINTING GUARANTEE:
  A pool's created_timestamp is bars[0].time at the moment of confirmation.
  A pool is NOT visible before all required confirmation candles are closed.

Design reference: §2.4 Liquidity_Detector
Requirements: 2.1–2.7
Correctness Properties: 5, 6, 7
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from strategy.types import ATRFilterStatus, ATRResult, LiquidityPool, OHLCVBar, PoolSide, PoolStatus


# ---------------------------------------------------------------------------
# LiquidityStatus (mirrors MQL5 LiquidityStatus struct)
# ---------------------------------------------------------------------------

@dataclass
class LiquidityStatus:
    atr_available:    bool               = True
    active_pool_count:int                = 0
    active_above:     int                = 0
    active_below:     int                = 0
    sweep_occurred:   bool               = False
    swept_pool:       Optional[LiquidityPool] = None
    rejection_reason: str                = ""


# ---------------------------------------------------------------------------
# LiquidityDetector
# ---------------------------------------------------------------------------

class LiquidityDetector:
    """
    Liquidity pool detector for the Python research environment.
    Mirrors MQL5 LiquidityDetector semantics exactly.

    Usage in backtest loop::

        detector = LiquidityDetector()
        detector.configure(swing_side_candles=2, max_active_pools=20,
                           pool_atr_tolerance=0.5)
        for bar_index in range(warmup, len(data)):
            bars = feed.get_bars('M15', bar_index).bars
            status = detector.update(bars, atr_result)
    """

    _EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

    def __init__(self) -> None:
        self._pools:       List[LiquidityPool] = []
        self._swing_side_n = 2
        self._max_pools    = 20
        self._atr_tolerance= 0.5

    # ------------------------------------------------------------------
    # configure
    # ------------------------------------------------------------------

    def configure(self, swing_side_candles: int = 2,
                  max_active_pools: int = 20,
                  pool_atr_tolerance: float = 0.5) -> None:
        """Set all parameters. Call before the first update()."""
        self._swing_side_n  = swing_side_candles
        self._max_pools     = max_active_pools
        self._atr_tolerance = pool_atr_tolerance

    # ------------------------------------------------------------------
    # update
    # ------------------------------------------------------------------

    def update(
        self,
        bars: List[OHLCVBar],
        atr_result: ATRResult,
    ) -> LiquidityStatus:
        """
        Process one confirmed M15 candle event.

        bars       : list of confirmed OHLCVBar, newest-first.
                     bars[0] = latest confirmed candle (MUST NOT be bar index 0).
        atr_result : ATRResult from atr_engine.calculate_atr() for the
                     SAME timeframe / session.
        """
        status = LiquidityStatus()
        status.atr_available = (atr_result.status != ATRFilterStatus.UNAVAILABLE)

        if not status.atr_available:
            status.rejection_reason = "ATR_UNAVAILABLE"
            self._count_pools(status)
            return status

        n = len(bars)
        min_bars = 2 * self._swing_side_n + 2  # need right + pivot + left + 1
        if n < min_bars:
            self._count_pools(status)
            return status

        atr_val = atr_result.current_atr

        # ---- 1. Detect confirmed swings and create pools ----
        scan_limit = n - self._swing_side_n - 1
        confirmation_time = bars[0].time   # NO-REPAINTING anchor

        for pivot in range(self._swing_side_n, scan_limit + 1):
            if not _valid_bar(bars[pivot]):
                continue

            pivot_high = bars[pivot].high
            pivot_low  = bars[pivot].low

            # Right-side confirmation (bars[0]..bars[pivot-1])
            high_right = all(
                _valid_bar(bars[r]) and bars[r].high < pivot_high
                for r in range(self._swing_side_n)
            )
            low_right = all(
                _valid_bar(bars[r]) and bars[r].low > pivot_low
                for r in range(self._swing_side_n)
            )

            # Left-side confirmation (bars[pivot+1]..bars[pivot+N])
            high_left = all(
                (pivot + l) < n and _valid_bar(bars[pivot + l])
                and bars[pivot + l].high < pivot_high
                for l in range(1, self._swing_side_n + 1)
            )
            low_left = all(
                (pivot + l) < n and _valid_bar(bars[pivot + l])
                and bars[pivot + l].low > pivot_low
                for l in range(1, self._swing_side_n + 1)
            )

            if high_right and high_left:
                self._try_create_pool(pivot_high, PoolSide.ABOVE,
                                      atr_val, confirmation_time)

            if low_right and low_left:
                self._try_create_pool(pivot_low, PoolSide.BELOW,
                                      atr_val, confirmation_time)

        # ---- 2. Sweep detection ----
        if n >= 2:
            self._detect_sweep(bars, status)

        # ---- 3. Invalidation ----
        self._update_invalidation(bars[0])

        self._count_pools(status)
        return status

    # ------------------------------------------------------------------
    # get_pools
    # ------------------------------------------------------------------

    def get_pools(self) -> List[LiquidityPool]:
        """Return a shallow copy of the current pool registry."""
        return list(self._pools)

    def get_active_pools(self, side: Optional[PoolSide] = None) -> List[LiquidityPool]:
        """Return only ACTIVE pools, optionally filtered by side."""
        return [p for p in self._pools
                if p.status == PoolStatus.ACTIVE
                and (side is None or p.side == side)]

    def get_pool_count(self) -> int:
        """Return total number of pools (all statuses)."""
        return len(self._pools)

    # ------------------------------------------------------------------
    # reset
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Clear all pools (call at reinitialization)."""
        self._pools = []

    # ------------------------------------------------------------------
    # load_pools
    # ------------------------------------------------------------------

    def load_pools(self, saved_pools: List[LiquidityPool]) -> None:
        """Restore pool registry from StateManager."""
        valid_statuses = {PoolStatus.ACTIVE, PoolStatus.SWEPT,
                          PoolStatus.INVALIDATED}
        self._pools = [p for p in saved_pools if p.status in valid_statuses]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _try_create_pool(self, price_level: float, side: PoolSide,
                         atr_val: float, confirm_time: datetime) -> None:
        tolerance = atr_val * self._atr_tolerance
        if tolerance <= 0.0 or not math.isfinite(tolerance):
            return

        # Duplicate check — skip if an active pool is within tolerance
        for p in self._pools:
            if p.status == PoolStatus.ACTIVE and p.side == side:
                if abs(p.price_level - price_level) <= tolerance:
                    return  # Already exists

        # Enforce MaxActivePools cap per side
        active_on_side = [p for p in self._pools
                          if p.status == PoolStatus.ACTIVE and p.side == side]
        if len(active_on_side) >= self._max_pools:
            # Remove oldest active pool on this side
            oldest = min(active_on_side, key=lambda p: p.created_timestamp)
            self._pools.remove(oldest)

        # Create new pool
        new_pool = LiquidityPool(
            price_level       = price_level,
            tolerance_band    = tolerance,      # locked at creation ATR
            status            = PoolStatus.ACTIVE,
            side              = side,
            created_timestamp = confirm_time,   # NO-REPAINTING: confirm time
            swept_timestamp   = self._EPOCH,
        )
        self._pools.append(new_pool)

    def _detect_sweep(self, bars: List[OHLCVBar],
                      status: LiquidityStatus) -> None:
        """
        Sweep = bars[1] wick/close through pool level,
                bars[0] close back inside tolerance.
        Never uses bar[0] as the sweep candle itself.
        """
        import dataclasses
        for i, p in enumerate(self._pools):
            if p.status != PoolStatus.ACTIVE:
                continue
            pl, tol = p.price_level, p.tolerance_band
            if p.side == PoolSide.ABOVE:
                through = bars[1].high > pl or bars[1].close > pl
                back_in = (pl - tol) <= bars[0].close <= (pl + tol)
            else:
                through = bars[1].low < pl or bars[1].close < pl
                back_in = (pl - tol) <= bars[0].close <= (pl + tol)

            if through and back_in:
                swept = dataclasses.replace(
                    p,
                    status          = PoolStatus.SWEPT,
                    swept_timestamp = bars[0].time,
                )
                self._pools[i]       = swept
                status.sweep_occurred = True
                status.swept_pool    = swept
                break  # Only one sweep per update call

    def _update_invalidation(self, bar0: OHLCVBar) -> None:
        """
        Pool is invalidated when bar0.close breaks beyond the pool
        by more than its tolerance_band without a prior sweep.
        """
        import dataclasses
        for i, p in enumerate(self._pools):
            if p.status != PoolStatus.ACTIVE:
                continue
            pl, tol = p.price_level, p.tolerance_band
            if p.side == PoolSide.ABOVE:
                invalidated = bar0.close > (pl + tol)
            else:
                invalidated = bar0.close < (pl - tol)
            if invalidated:
                self._pools[i] = dataclasses.replace(
                    p, status=PoolStatus.INVALIDATED)

    def _count_pools(self, status: LiquidityStatus) -> None:
        status.active_pool_count = 0
        status.active_above      = 0
        status.active_below      = 0
        for p in self._pools:
            if p.status == PoolStatus.ACTIVE:
                status.active_pool_count += 1
                if p.side == PoolSide.ABOVE:
                    status.active_above += 1
                else:
                    status.active_below += 1


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _valid_bar(bar: OHLCVBar) -> bool:
    """Basic OHLC sanity check."""
    if bar.time == datetime(1970, 1, 1, tzinfo=timezone.utc):
        return False
    if bar.high < bar.low:
        return False
    if bar.close <= 0.0 or bar.open <= 0.0:
        return False
    if not (math.isfinite(bar.high) and math.isfinite(bar.low)
            and math.isfinite(bar.close)):
        return False
    return True
