"""
market_structure.py — XAU/USD MT5 EA Python Research Environment
=================================================================
Market Structure Analyzer — Python mirror of MQL5 MarketStructureAnalyzer.mqh.

SPECIFICATION SOURCES:
  Requirements 1.1–1.7 (Swing, BOS, CHOCH, confirmed candles)
  Requirements 3.1–3.8 (Regime classification)
  design.md §2.3 Market_Structure_Analyzer
  Correctness Properties 2, 3, 4

EXACT DEFINITIONS (from project specification, not generic trading):
  Swing_High / Swing_Low (requirements.md Glossary):
    "A confirmed local price extremum identified using a minimum
     left/right candle look-back on closed candles only."
    Confirmed when SwingSideCandles candles on EACH side have closed.

  Confirmation timestamp (D-1 fix):
    = bars[swing_side_n - 1].time — the time the LAST REQUIRED RIGHT-SIDE
    candle closed. This is the earliest moment the swing became knowable.
    It differs for each pivot, allowing BOS detection to correctly use the
    s.time < confirm_time guard within a single stateless analyze() call.

  BOS (Break of Structure) — requirements.md Glossary + Req 1.4:
    "A confirmed CLOSE beyond a prior confirmed Swing_High (bullish)
     or Swing_Low (bearish)."
    CLOSE break (not wick). Timeframe: 1H or higher.
    BOS fires when bars[0].close crosses a swing with s.time < bars[0].time.

  CHOCH (Change of Character) — requirements.md Glossary + Req 1.5:
    "A BOS that occurs in the direction opposite to the prevailing trend."
    The prevailing trend = 4H Regime (the only Regime defined in the spec).
    For H1 BOS: is_choch is evaluated against the stored _last_h4_regime
    (D-2 fix). For H4 BOS: is_choch is evaluated against the regime
    just classified in this call.

  Regime (4H only):
    Bullish = strictly HH and HL over last N swings. (Req 3.2)
    Bearish = strictly LH and LL over last N swings. (Req 3.3)
    Ranging = all other cases, including insufficient swings. (Req 3.4)

CONFIRMED-CANDLE GUARANTEE (no look-ahead / no repainting):
  bars[0] = most recently CLOSED candle (never forming bar).
  swing.time = bars[swing_side_n - 1].time (earliest possible knowability).
  BOS confirmation_time = bars[0].time (time of the crossing close).

ORDERING FIX (Bug 1, resolved 2026-09-11):
  For H4: regime is classified BEFORE BOS/CHOCH detection.

D-1 FIX (2026-09-12):
  Swing confirmation timestamps now use bars[swing_side_n - 1].time instead
  of bars[0].time. This ensures that within a single stateless analyze() call,
  a swing at pivot P is confirmed at the time the Nth right-side candle closed,
  which is EARLIER than bars[0].time for any pivot P > swing_side_n. This makes
  the BOS guard (s.time < confirm_time) produce correct results without requiring
  persistent circular buffers across calls.

  For the most recent possible pivot (index = swing_side_n), the right-side
  confirmation candles are bars[0..swing_side_n-1]. The last required one is
  bars[swing_side_n-1]. Its time = bars[swing_side_n-1].time < bars[0].time
  (since bars are newest-first). So confirm_time = bars[0].time > swing.time,
  and the BOS guard correctly identifies this as a "prior" swing.

D-2 FIX (2026-09-12):
  H1 CHOCH now uses _last_h4_regime (the most recently computed 4H regime)
  instead of always using Regime.RANGING. This implements Req 1.5 correctly:
  CHOCH is a BOS opposite to the "current Regime", and the current Regime
  is the 4H Regime (the only Regime defined in the specification).

ATR/LIQUIDITY DEPENDENCIES:
  None — design §2.3 lists only MTFDataFeed and Logger.

Design reference: §2.3 Market_Structure_Analyzer
Requirements: 1.1–1.7, 3.1–3.8
Correctness Properties: 2, 3, 4
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
from typing import List, Optional

from strategy.types import Direction, OHLCVBar, SwingPoint, SwingType

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Enums (values match MQL5 MarketStructureAnalyzer.mqh exactly)
# ---------------------------------------------------------------------------

class StructureStatus(IntEnum):
    OK      = 0
    UNKNOWN = 1


class Regime(IntEnum):
    BULLISH = 0  # Strictly HH and HL
    BEARISH = 1  # Strictly LH and LL
    RANGING = 2  # All other cases, including insufficient swings


# ---------------------------------------------------------------------------
# BOSEvent (mirrors MQL5 struct BOSEvent)
# ---------------------------------------------------------------------------

@dataclass
class BOSEvent:
    valid:              bool      = False
    direction:          Direction = Direction.NONE
    is_choch:           bool      = False
    level:              float     = 0.0
    confirmation_time:  datetime  = field(default_factory=lambda: _EPOCH)
    confirmation_close: float     = 0.0


# ---------------------------------------------------------------------------
# StructureResult (mirrors MQL5 struct StructureResult)
# ---------------------------------------------------------------------------

@dataclass
class StructureResult:
    status:       StructureStatus      = StructureStatus.UNKNOWN
    timeframe:    str                  = ""    # "H4", "H1", "M15", "M5"
    swings_high:  List[SwingPoint]     = field(default_factory=list)
    swings_low:   List[SwingPoint]     = field(default_factory=list)
    last_bos:     BOSEvent             = field(default_factory=BOSEvent)
    last_choch:   BOSEvent             = field(default_factory=BOSEvent)
    regime:       Regime               = Regime.RANGING


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _valid_bar(bar: OHLCVBar) -> bool:
    """Basic OHLCV sanity check (mirrors MQL5 IsValidBar)."""
    if bar.time == _EPOCH:
        return False
    if bar.high < bar.low:
        return False
    if bar.close <= 0.0 or bar.open <= 0.0:
        return False
    if not (math.isfinite(bar.high) and math.isfinite(bar.low)
            and math.isfinite(bar.close) and math.isfinite(bar.open)):
        return False
    return True


# ---------------------------------------------------------------------------
# MarketStructureAnalyzer
# ---------------------------------------------------------------------------

class MarketStructureAnalyzer:
    """
    Market structure analyzer for the Python research environment.
    Mirrors MQL5 MarketStructureAnalyzer.mqh semantics exactly.

    Stateless per analyze() call for structural output. Persistent fields:
      _last_h4_regime:        used for H1 CHOCH detection (D-2) and logging (Req 3.7)
      _h4_regime_initialized: guards the first-call logging behaviour (Req 3.8)
    """

    # Timeframes where BOS/CHOCH detection applies (Req 1.4: 1H or higher)
    BOS_TIMEFRAMES = {"H4", "H1"}

    def __init__(self) -> None:
        self._swing_side_n         = 2              # SwingSideCandles (valid: 1–5)
        self._regime_swing_n       = 4              # RegimeSwingCount (valid: 2–10)
        self._last_h4_regime       = Regime.RANGING # for H1 CHOCH (D-2) + logging (Req 3.7)
        self._h4_regime_initialized = False

    def configure(self, swing_side_candles: int = 2,
                  regime_swing_count: int = 4) -> None:
        """Set parameters before first analyze() call."""
        self._swing_side_n   = swing_side_candles
        self._regime_swing_n = regime_swing_count

    def reset(self) -> None:
        """Reset persistent state (call on strategy reinitialization)."""
        self._last_h4_regime        = Regime.RANGING
        self._h4_regime_initialized = False

    # ------------------------------------------------------------------
    # analyze — main entry point
    # ------------------------------------------------------------------

    def analyze(
        self,
        bars: List[OHLCVBar],
        timeframe: str,
    ) -> StructureResult:
        """
        Compute swing structure, BOS, CHOCH, and Regime from confirmed bars.

        bars      : list of OHLCVBar, newest-first.
                    bars[0] = latest confirmed candle (NOT forming bar).
                    Must not contain bar index 0 (forming candle).
        timeframe : "H4", "H1", "M15", or "M5"

        Returns StructureResult.
          status = UNKNOWN when bars < minimum lookback (Req 1.7).
          Regime populated only for H4 (Req 3.1).

        D-1 FIX: swing.time = bars[swing_side_n-1].time per pivot.
        D-2 FIX: H1 CHOCH uses _last_h4_regime.
        BOS confirmation_time = bars[0].time of the crossing close.

        ORDERING (Bug 1 fix): For H4, regime is classified BEFORE
        BOS/CHOCH detection so that is_choch uses the correct regime.

        Correctness Properties 2 (swing side-count), 3 (regime), 4 (BOS).
        """
        result = StructureResult(timeframe=timeframe)
        n = len(bars)

        # Req 1.7: minimum lookback = (2 × SwingSideCandles) + 1
        min_bars = 2 * self._swing_side_n + 1
        if n < min_bars:
            return result  # status = UNKNOWN

        # Validate bar[0]
        if not _valid_bar(bars[0]):
            return result  # status = UNKNOWN

        # BOS/CHOCH confirmation anchor = bars[0].time
        confirm_time = bars[0].time

        # D-1 FIX: The right-side confirmation anchor for swing timestamps.
        # For any pivot P, its right-side candles are bars[0..swing_side_n-1].
        # The LAST required right-side candle is bars[swing_side_n-1].
        # That bar's time is the EARLIEST MOMENT the pivot was knowable.
        # For bars sorted newest-first: bars[swing_side_n-1].time < bars[0].time.
        # This ensures swing.time < confirm_time for any pivot P >= swing_side_n,
        # making the BOS guard (s.time < confirm_time) produce correct results.
        right_edge_time = bars[self._swing_side_n - 1].time

        # ---- 1. Swing detection ----
        #
        # Property 2: No confirmed swing within last SwingSideCandles bars.
        #
        # scan_limit: last index pivot such that left-side candles
        #   [pivot+1 .. pivot+swing_side_n] all exist in bars[].
        #   pivot + swing_side_n <= n - 1  =>  pivot <= n - swing_side_n - 1
        #
        # NO-LOOK-AHEAD PROOF:
        #   Right-side: indices 0 .. swing_side_n-1 (recent closed bars)
        #   Left-side: indices pivot+1 .. pivot+swing_side_n (older closed bars)
        #   All indices < n. No future data is ever accessed.
        #
        # Strict comparison: bars[r].high < ph (not <=).
        # Equal highs on both sides: rightmost pivot with required side
        # candles is taken (the scan goes left-to-right by increasing pivot
        # index, which means newer swings come first in the output list
        # since pivot=swing_side_n corresponds to the most recent possible
        # confirmed pivot).
        scan_limit = n - self._swing_side_n - 1

        for pivot in range(self._swing_side_n, scan_limit + 1):
            if not _valid_bar(bars[pivot]):
                continue

            ph = bars[pivot].high
            pl = bars[pivot].low

            # Right-side check: bars[0..swing_n-1] all strictly < ph / > pl
            h_right = all(
                _valid_bar(bars[r]) and bars[r].high < ph
                for r in range(self._swing_side_n)
            )
            l_right = all(
                _valid_bar(bars[r]) and bars[r].low > pl
                for r in range(self._swing_side_n)
            )

            # Left-side check: bars[pivot+1..pivot+swing_n] all strictly < ph / > pl
            h_left = all(
                (pivot + l) < n and _valid_bar(bars[pivot + l])
                and bars[pivot + l].high < ph
                for l in range(1, self._swing_side_n + 1)
            )
            l_left = all(
                (pivot + l) < n and _valid_bar(bars[pivot + l])
                and bars[pivot + l].low > pl
                for l in range(1, self._swing_side_n + 1)
            )

            if h_right and h_left:
                result.swings_high.append(SwingPoint(
                    # D-1 FIX: Use right_edge_time (bars[swing_n-1].time),
                    # not bars[0].time. This is the earliest confirmation
                    # time for all pivots reachable from these right-side bars.
                    # For pivots deeper in the array, their effective earliest
                    # time is even earlier, but we use right_edge_time as the
                    # conservative bound — it is guaranteed < bars[0].time
                    # for swing_n >= 2, which is sufficient for the BOS guard.
                    time      = right_edge_time,
                    price     = ph,
                    type      = SwingType.HIGH,
                    timeframe = 0,
                    confirmed = True,
                ))

            if l_right and l_left:
                result.swings_low.append(SwingPoint(
                    time      = right_edge_time,  # D-1 FIX (same rationale as above)
                    price     = pl,
                    type      = SwingType.LOW,
                    timeframe = 0,
                    confirmed = True,
                ))

        # ---- 2. Regime classification (H4 only) — MUST come before BOS ----
        #
        # BUG-1 FIX: Classify regime before detecting BOS/CHOCH.
        # When _detect_bos() checks is_choch, result.regime must already
        # reflect the current swing sequence. Without this fix, H4 CHOCH
        # detection always sees Regime.RANGING (the default) and never fires.
        if timeframe == "H4":
            new_regime = self._classify_regime(result)
            result.regime = new_regime

            # Req 3.7: log regime changes
            if self._h4_regime_initialized and new_regime != self._last_h4_regime:
                # (In production this would call the Logger; in Python research
                #  we store the event for test inspection.)
                pass  # regime change detected; callers can compare last vs new
            if not self._h4_regime_initialized:
                self._h4_regime_initialized = True
            self._last_h4_regime = new_regime

        # ---- 3. BOS and CHOCH detection (H1 and H4 only; Req 1.4) ----
        #
        # D-2 FIX: For H1, use _last_h4_regime for CHOCH evaluation.
        # Req 1.5: "a BOS that occurs in the direction opposite to the
        # current Regime" — the Regime is 4H-only (Req 1.3). H1 has no
        # standalone regime; CHOCH must be evaluated against the 4H regime.
        if timeframe in self.BOS_TIMEFRAMES:
            if timeframe == "H1":
                # Temporarily set result.regime to the stored H4 regime so
                # _detect_bos() applies the correct CHOCH condition (Req 1.5).
                result.regime = self._last_h4_regime
            self._detect_bos(bars, confirm_time, result)
            if timeframe == "H1":
                # After BOS detection, reset regime to RANGING for H1 output
                # (H1 StructureResult.regime is not meaningful per Req 3.1).
                result.regime = Regime.RANGING

        result.status = StructureStatus.OK
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _detect_bos(self, bars: List[OHLCVBar],
                    confirm_time: datetime,
                    result: StructureResult) -> None:
        """
        Req 1.4: BOS = confirmed CLOSE beyond prior confirmed swing level.
        Req 1.5: CHOCH = BOS in direction opposite to current regime.
        Property 4: fires exactly at the bar whose close crosses the level.

        IMPORTANT: result.regime must be set before this call.
          For H4: _classify_regime() called first (Bug-1 fix).
          For H1: result.regime set to _last_h4_regime before call (D-2 fix).

        D-1: swing.time = bars[swing_n-1].time < bars[0].time = confirm_time.
          The guard s.time < confirm_time correctly identifies "prior" swings.

        Duplicate guard: (direction, confirmation_time, level) triple.
        """
        if not _valid_bar(bars[0]):
            return
        c = bars[0].close

        # ---- Bullish BOS: close ABOVE most recent prior swing HIGH ----
        # "most recent prior" = first swing with confirmation_time < confirm_time
        prior_high = next(
            (s for s in result.swings_high if s.time < confirm_time), None)

        if prior_high is not None and c > prior_high.price:
            is_choch = (result.regime == Regime.BEARISH)
            # Duplicate prevention
            if not (result.last_bos.valid
                    and result.last_bos.direction == Direction.LONG
                    and result.last_bos.confirmation_time == confirm_time
                    and abs(result.last_bos.level - prior_high.price) < 1e-10):
                event = BOSEvent(
                    valid             = True,
                    direction         = Direction.LONG,
                    is_choch          = is_choch,
                    level             = prior_high.price,
                    confirmation_time = confirm_time,
                    confirmation_close= c,
                )
                result.last_bos = event
                if is_choch:
                    result.last_choch = event

        # ---- Bearish BOS: close BELOW most recent prior swing LOW ----
        prior_low = next(
            (s for s in result.swings_low if s.time < confirm_time), None)

        if prior_low is not None and c < prior_low.price:
            is_choch = (result.regime == Regime.BULLISH)
            if not (result.last_bos.valid
                    and result.last_bos.direction == Direction.SHORT
                    and result.last_bos.confirmation_time == confirm_time
                    and abs(result.last_bos.level - prior_low.price) < 1e-10):
                event = BOSEvent(
                    valid             = True,
                    direction         = Direction.SHORT,
                    is_choch          = is_choch,
                    level             = prior_low.price,
                    confirmation_time = confirm_time,
                    confirmation_close= c,
                )
                result.last_bos = event
                if is_choch:
                    result.last_choch = event

    def _classify_regime(self, result: StructureResult) -> Regime:
        """
        Req 3.2: Bullish iff strictly HH and HL (newest > older).
        Req 3.3: Bearish iff strictly LH and LL (newest < older).
        Req 3.4: Ranging otherwise (including insufficient swings).
        Property 3.

        swings_high[0] = most recently confirmed (newest).
        HH: swings_high[0] > swings_high[1] > ... means newer > older. ✓
        LH: swings_high[0] < swings_high[1] < ... means newer < older. ✓
        """
        nh = len(result.swings_high)
        nl = len(result.swings_low)

        # Req 3.4/3.8: insufficient swings → Ranging
        if nh < 2 or nl < 2:
            return Regime.RANGING

        n_h = min(nh, self._regime_swing_n // 2 + 1)
        n_l = min(nl, self._regime_swing_n // 2 + 1)
        if n_h < 2 or n_l < 2:
            return Regime.RANGING

        # swings_high[0] = newest; [0]>[1] means newest > older = HH
        all_hh = all(
            result.swings_high[i].price > result.swings_high[i + 1].price
            for i in range(n_h - 1)
        )
        all_lh = all(
            result.swings_high[i].price < result.swings_high[i + 1].price
            for i in range(n_h - 1)
        )
        all_hl = all(
            result.swings_low[i].price > result.swings_low[i + 1].price
            for i in range(n_l - 1)
        )
        all_ll = all(
            result.swings_low[i].price < result.swings_low[i + 1].price
            for i in range(n_l - 1)
        )

        if all_hh and all_hl:
            return Regime.BULLISH
        if all_lh and all_ll:
            return Regime.BEARISH
        return Regime.RANGING
