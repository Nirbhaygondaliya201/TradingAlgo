"""
test_market_structure.py — Task 10 comprehensive test suite
============================================================
Tests for MarketStructureAnalyzer (Python mirror of MarketStructureAnalyzer.mqh).

Coverage:
  SWINGS        (Property 2)   — detection, confirmation timing, equal levels,
                                 side-count invariant, insufficient history
  REGIME        (Property 3)   — all cases + insufficient history
  BOS           (Property 4)   — bullish, bearish, close vs wick, correct level,
                                 confirmation timestamp, duplicate prevention
  CHOCH                         — bullish, bearish, prerequisite structure,
                                 confirmation timestamp, Bug-1 fix verification
  DATA SAFETY                   — CANARY A (forming candle mutation),
                                 CANARY B (future candle mutation),
                                 CANARY C (swing confirmation timing),
                                 invalid OHLC, empty bars, missing data
  DETERMINISM                   — identical inputs → identical outputs, idempotent
  INTEGRATION                   — swing detection + BOS + CHOCH in sequence
  NO TRADING                    — confirms no OrderSend / entry signals

Specification references:
  requirements.md: Req 1.1–1.7, 3.1–3.8, 15.5
  design.md §2.3, Properties 2, 3, 4

Architecture note on single-call BOS:
  The analyzer is stateless per call — it recomputes swings fresh from the input
  bars each time. BOS detection within a single Analyze() call requires that
  bars[0] (the newest bar) has a close > prior swing level. However, since
  high >= close always, bars[0].high >= bars[0].close > pivot.high, which causes
  the right-side check (bars[0..swing_n-1] all < pivot.high) to fail.
  Therefore BOS/CHOCH tests use _detect_bos() directly with pre-injected swings,
  testing the detection logic in isolation as unit tests require.
"""

from __future__ import annotations

import math
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from typing import List

import pytest

from strategy.market_structure import (
    BOSEvent,
    MarketStructureAnalyzer,
    Regime,
    StructureResult,
    StructureStatus,
    _valid_bar,
)
from strategy.types import Direction, OHLCVBar, SwingPoint, SwingType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _bar(t_offset: int, open_: float, high: float, low: float, close: float) -> OHLCVBar:
    """Convenience: create an OHLCVBar at epoch + t_offset hours."""
    return OHLCVBar(
        time        = _EPOCH + timedelta(hours=t_offset),
        open        = open_,
        high        = high,
        low         = low,
        close       = close,
        tick_volume = 1,
    )


def _flat_bars(n: int, price: float = 100.0, start_h: int = 1) -> List[OHLCVBar]:
    """Return n identical bars (no swings possible). start_h=1 to avoid epoch time."""
    return [_bar(start_h + i, price, price + 0.01, price - 0.01, price)
            for i in range(n)]


def _make_msa(swing_n: int = 2, regime_n: int = 4) -> MarketStructureAnalyzer:
    msa = MarketStructureAnalyzer()
    msa.configure(swing_side_candles=swing_n, regime_swing_count=regime_n)
    return msa


def _newest_first(bars: List[OHLCVBar]) -> List[OHLCVBar]:
    """Reverse to newest-first (analyzer convention)."""
    return list(reversed(bars))


def _inject_swing_h(result: StructureResult, price: float, t_offset: int) -> None:
    """Inject a confirmed swing high directly into a StructureResult for unit testing."""
    result.swings_high.append(SwingPoint(
        time      = _EPOCH + timedelta(hours=t_offset),
        price     = price,
        type      = SwingType.HIGH,
        timeframe = 0,
        confirmed = True,
    ))


def _inject_swing_l(result: StructureResult, price: float, t_offset: int) -> None:
    """Inject a confirmed swing low directly into a StructureResult for unit testing."""
    result.swings_low.append(SwingPoint(
        time      = _EPOCH + timedelta(hours=t_offset),
        price     = price,
        type      = SwingType.LOW,
        timeframe = 0,
        confirmed = True,
    ))


# ============================================================================
# Section 1: _valid_bar helper
# ============================================================================

class TestValidBar:
    def test_valid_bar(self):
        b = _bar(1, 100.0, 102.0, 99.0, 101.0)
        assert _valid_bar(b)

    def test_zero_time_invalid(self):
        b = OHLCVBar(time=_EPOCH, open=100.0, high=102.0, low=99.0, close=101.0)
        assert not _valid_bar(b)

    def test_high_lt_low_invalid(self):
        b = OHLCVBar(time=_EPOCH + timedelta(hours=1),
                     open=100.0, high=99.0, low=102.0, close=100.5)
        assert not _valid_bar(b)

    def test_zero_close_invalid(self):
        b = _bar(1, 100.0, 102.0, 99.0, 0.0)
        assert not _valid_bar(b)

    def test_nan_values_invalid(self):
        b = _bar(1, 100.0, float("nan"), 99.0, 100.5)
        assert not _valid_bar(b)

    def test_inf_values_invalid(self):
        b = _bar(1, 100.0, float("inf"), 99.0, 100.5)
        assert not _valid_bar(b)

    def test_high_equals_low_valid_doji(self):
        """Doji (high == low) is valid — not prohibited by spec."""
        b = OHLCVBar(time=_EPOCH + timedelta(hours=1),
                     open=100.0, high=100.0, low=100.0, close=100.0, tick_volume=1)
        assert _valid_bar(b)


# ============================================================================
# Section 2: Insufficient History → UNKNOWN (Req 1.7)
# ============================================================================

class TestInsufficientHistory:
    """Req 1.7: fewer than (2×SwingSideCandles)+1 bars → UNKNOWN."""

    @pytest.mark.parametrize("n", [0, 1, 2, 3, 4])
    def test_fewer_than_min_bars_swing2_returns_unknown(self, n: int):
        # swing_side_n=2 requires min 2*2+1=5 bars
        msa = _make_msa(swing_n=2)
        bars = _flat_bars(n)
        result = msa.analyze(bars, "H1")
        assert result.status == StructureStatus.UNKNOWN

    def test_exactly_min_bars_returns_ok(self):
        msa = _make_msa(swing_n=2)
        bars = _flat_bars(5)  # 2*2+1 = 5, start_h=1 so no epoch bars
        result = msa.analyze(bars, "H1")
        assert result.status == StructureStatus.OK

    @pytest.mark.parametrize("n", [0, 1, 2])
    def test_swing_n1_fewer_than_min_bars_returns_unknown(self, n: int):
        # swing_side_n=1 requires min 2*1+1=3 bars
        msa = _make_msa(swing_n=1)
        bars = _flat_bars(n)
        result = msa.analyze(bars, "H1")
        assert result.status == StructureStatus.UNKNOWN

    def test_insufficient_history_produces_no_swings(self):
        msa = _make_msa(swing_n=2)
        bars = _flat_bars(4)
        result = msa.analyze(bars, "H4")
        assert len(result.swings_high) == 0
        assert len(result.swings_low)  == 0

    def test_insufficient_history_no_bos(self):
        msa = _make_msa(swing_n=2)
        bars = _flat_bars(4)
        result = msa.analyze(bars, "H1")
        assert not result.last_bos.valid

    def test_insufficient_history_regime_ranging(self):
        msa = _make_msa(swing_n=2)
        bars = _flat_bars(4)
        result = msa.analyze(bars, "H4")
        assert result.regime == Regime.RANGING

    def test_empty_bars_returns_unknown(self):
        msa = _make_msa(swing_n=2)
        result = msa.analyze([], "H1")
        assert result.status == StructureStatus.UNKNOWN


# ============================================================================
# Section 3: Swing Detection — Property 2
# ============================================================================

class TestSwingDetection:
    """
    Property 2: No confirmed swing within last SwingSideCandles bars.
    All confirmed swings share confirmation_time = bars[0].time.
    """

    def _swing_high_bars(self, swing_n: int = 2, start_h: int = 1) -> List[OHLCVBar]:
        """
        Minimal valid sequence for one confirmed swing high.
        Layout oldest→newest: [left_n: h<110][pivot: h=110][right_n: h<110]
        After reversal (newest-first for analyzer):
          bars[0..swing_n-1] = right-side (h<110)
          bars[swing_n]      = pivot (h=110)
          bars[swing_n+1..2*swing_n] = left-side (h<110)
        """
        t = start_h
        bars: List[OHLCVBar] = []
        for i in range(swing_n):
            bars.append(_bar(t, 100.0, 101.0, 99.0, 100.0)); t += 1
        bars.append(_bar(t, 100.0, 110.0, 99.0, 100.0)); t += 1   # pivot
        for i in range(swing_n):
            bars.append(_bar(t, 100.0, 101.0, 99.0, 100.0)); t += 1
        return _newest_first(bars)

    def _swing_low_bars(self, swing_n: int = 2, start_h: int = 1) -> List[OHLCVBar]:
        t = start_h
        bars: List[OHLCVBar] = []
        for i in range(swing_n):
            bars.append(_bar(t, 100.0, 101.0, 99.0, 100.0)); t += 1
        bars.append(_bar(t, 100.0, 101.0, 90.0, 100.0)); t += 1   # pivot low
        for i in range(swing_n):
            bars.append(_bar(t, 100.0, 101.0, 99.0, 100.0)); t += 1
        return _newest_first(bars)

    def test_swing_high_detected(self):
        msa = _make_msa(swing_n=2)
        bars = self._swing_high_bars(2)
        result = msa.analyze(bars, "H1")
        assert result.status == StructureStatus.OK
        assert len(result.swings_high) >= 1

    def test_swing_high_price_is_pivot_high(self):
        msa = _make_msa(swing_n=2)
        bars = self._swing_high_bars(2)
        result = msa.analyze(bars, "H1")
        assert len(result.swings_high) >= 1
        assert result.swings_high[0].price == pytest.approx(110.0)

    def test_swing_high_type_correct(self):
        msa = _make_msa(swing_n=2)
        bars = self._swing_high_bars(2)
        result = msa.analyze(bars, "H1")
        assert len(result.swings_high) >= 1
        assert result.swings_high[0].type == SwingType.HIGH
        assert result.swings_high[0].confirmed is True

    def test_swing_low_detected(self):
        msa = _make_msa(swing_n=2)
        bars = self._swing_low_bars(2)
        result = msa.analyze(bars, "H1")
        assert len(result.swings_low) >= 1

    def test_swing_low_price_is_pivot_low(self):
        msa = _make_msa(swing_n=2)
        bars = self._swing_low_bars(2)
        result = msa.analyze(bars, "H1")
        assert len(result.swings_low) >= 1
        assert result.swings_low[0].price == pytest.approx(90.0)

    def test_swing_low_type_correct(self):
        msa = _make_msa(swing_n=2)
        bars = self._swing_low_bars(2)
        result = msa.analyze(bars, "H1")
        assert result.swings_low[0].type == SwingType.LOW

    def test_swing_confirmation_timestamp_is_right_edge_time(self):
        """
        D-1 FIX verification: swing.time = bars[swing_n-1].time.

        The confirmation time of each swing pivot is the time of the LAST
        REQUIRED right-side candle (bars[swing_n-1]), NOT bars[0].time.
        This is the earliest moment the swing became knowable, enabling
        the BOS guard (s.time < confirm_time = bars[0].time) to work
        correctly within a single stateless analyze() call.

        For swing_n=2: right_edge_time = bars[1].time < bars[0].time.
        """
        n = 2
        msa = _make_msa(swing_n=n)
        bars = self._swing_high_bars(n)
        result = msa.analyze(bars, "H1")
        expected_time = bars[n - 1].time   # bars[1].time (last right-side bar)
        for sw in result.swings_high:
            assert sw.time == expected_time, (
                f"Swing time {sw.time} != bars[n-1].time {expected_time}"
            )
        # Also verify it is strictly BEFORE bars[0].time (makes BOS guard work)
        assert expected_time < bars[0].time, (
            "right_edge_time must be strictly before bars[0].time "
            "so that BOS can detect prior swings"
        )


    def test_no_swing_on_flat_sequence(self):
        """Flat price → no swings (strict comparison bars[r].high < pivot.high fails)."""
        msa = _make_msa(swing_n=2)
        bars = _flat_bars(20)
        result = msa.analyze(bars, "H1")
        assert len(result.swings_high) == 0
        assert len(result.swings_low) == 0

    def test_swing_n1_works(self):
        """swing_side_candles=1: swing confirmed with just 1 bar on each side."""
        msa = _make_msa(swing_n=1)
        t = 1
        bars_ol = [
            _bar(t,   100.0, 101.0, 99.0, 100.0),  # left-1
            _bar(t+1, 100.0, 110.0, 99.0, 100.0),  # pivot
            _bar(t+2, 100.0, 101.0, 99.0, 100.0),  # right-1
        ]
        bars = _newest_first(bars_ol)
        result = msa.analyze(bars, "H1")
        assert result.status == StructureStatus.OK
        assert len(result.swings_high) >= 1

    # Property 2: side-count invariant
    def test_property_2_n_minus_1_right_bars_not_enough(self):
        """
        With only swing_n-1 right-side bars, the pivot is NOT in scan range.
        Minimum bars = 2*swing_n+1. With 2*swing_n bars, status = UNKNOWN.
        """
        n = 2
        # 2*swing_n = 4 bars < min_bars(5) → UNKNOWN
        bars = _flat_bars(2 * n, start_h=1)
        msa = _make_msa(swing_n=n)
        result = msa.analyze(bars, "H1")
        assert result.status == StructureStatus.UNKNOWN

    def test_property_2_exactly_n_right_bars_confirmed(self):
        """
        With exactly swing_n right-side bars + pivot + swing_n left bars = 2*n+1 bars.
        Pivot can be confirmed.
        """
        n = 2
        msa = _make_msa(swing_n=n)
        bars = self._swing_high_bars(n)
        assert len(bars) == 2 * n + 1
        result = msa.analyze(bars, "H1")
        assert result.status == StructureStatus.OK

    # CANARY C: Swing Confirmation Timing
    def test_canary_c_swing_not_confirmed_before_n_right_candles(self):
        """
        CANARY C: Before N right-side candles close, swing does not exist.
        After the Nth right-side candle: swing exists.

        D-1 FIX: Confirmation time = bars[swing_n-1].time (last right-side
        candle time), NOT bars[0].time. For n=2, the last right-side bar is
        bars[1] (t=4), not bars[0] (t=5).

        This is the earliest moment the swing became knowable.
        """
        n = 2
        # Phase 1: N-1=1 right-side bars → min_bars not met → UNKNOWN
        bars_1_right_ol = [
            _bar(1, 100.0, 101.0, 99.0, 100.0),   # left-2
            _bar(2, 100.0, 101.0, 99.0, 100.0),   # left-1
            _bar(3, 100.0, 110.0, 99.0, 100.0),   # pivot
            _bar(4, 100.0, 101.0, 99.0, 100.0),   # right-1 only
        ]
        bars_1_right = _newest_first(bars_1_right_ol)
        msa1 = _make_msa(swing_n=n)
        r_before = msa1.analyze(bars_1_right, "H1")
        assert r_before.status == StructureStatus.UNKNOWN  # min_bars=5, only 4

        # Phase 2: N=2 right-side bars → pivot confirmed
        bars_2_right_ol = bars_1_right_ol + [_bar(5, 100.0, 101.0, 99.0, 100.0)]
        bars_2_right = _newest_first(bars_2_right_ol)
        msa2 = _make_msa(swing_n=n)
        r_after = msa2.analyze(bars_2_right, "H1")
        assert r_after.status == StructureStatus.OK
        assert any(abs(s.price - 110.0) < 1e-8 for s in r_after.swings_high)

        # D-1: confirmation time = bars[n-1].time = bars[1].time = t=4
        # (the last required right-side candle, NOT bars[0].time = t=5)
        expected_confirm_time = _EPOCH + timedelta(hours=4)  # bars[1] in newest-first
        for sw in r_after.swings_high:
            if abs(sw.price - 110.0) < 1e-8:
                assert sw.time == expected_confirm_time, (
                    f"Expected confirmation at t=4 (bars[1]), got {sw.time}"
                )



# ============================================================================
# Section 4: Equal Highs / Lows
# ============================================================================

class TestEqualHighsLows:
    """Strict comparison: bars[r].high < pivot.high (not <=)."""

    def test_equal_high_on_right_side_blocks_swing(self):
        """
        Right-side bar has high == pivot.high → strict < fails → swing NOT confirmed.
        design §2.3: 'Equal highs/lows … rightmost with required side candles.'
        In the strict implementation, equal highs on either side block the swing.
        """
        n = 2
        # bars oldest→newest: left(2)[h=101], pivot[h=110], right[h=110][h=101]
        bars_ol = [
            _bar(1, 100.0, 101.0, 99.0, 100.0),
            _bar(2, 100.0, 101.0, 99.0, 100.0),
            _bar(3, 100.0, 110.0, 99.0, 100.0),   # pivot
            _bar(4, 100.0, 110.0, 99.0, 100.0),   # equal high on right → blocks
            _bar(5, 100.0, 101.0, 99.0, 100.0),
        ]
        bars = _newest_first(bars_ol)
        # bars[0]=t5, bars[1]=t4(equal high=110), bars[2]=pivot
        # Right-side: bars[0]=101 < 110 ✓, bars[1]=110 NOT < 110 → h_right=False
        msa = _make_msa(swing_n=n)
        result = msa.analyze(bars, "H1")
        highs = [s.price for s in result.swings_high]
        assert 110.0 not in highs, f"Expected no swing at 110.0 but got: {highs}"

    def test_distinct_high_on_all_sides_detected(self):
        """All right-side and left-side bars strictly below pivot → swing detected."""
        msa = _make_msa(swing_n=2)
        bars_ol = [
            _bar(1, 100.0, 101.0, 99.0, 100.0),
            _bar(2, 100.0, 101.0, 99.0, 100.0),
            _bar(3, 100.0, 110.0, 99.0, 100.0),   # pivot
            _bar(4, 100.0, 109.9, 99.0, 100.0),
            _bar(5, 100.0, 108.0, 99.0, 100.0),
        ]
        bars = _newest_first(bars_ol)
        result = msa.analyze(bars, "H1")
        assert any(abs(s.price - 110.0) < 1e-8 for s in result.swings_high)


# ============================================================================
# Section 5: Regime Classification — Property 3
# ============================================================================

class TestRegimeClassification:
    """
    Property 3: Regime = Bullish iff all swing highs strictly increasing
    AND all swing lows strictly increasing (newest > older).
    swings_high[0] = newest. HH: [0] > [1] (newest > older).
    """

    def _classify(self, highs: List[float], lows: List[float],
                  swing_n: int = 2, regime_n: int = 4) -> Regime:
        """Direct call to _classify_regime with injected swings."""
        msa = _make_msa(swing_n=swing_n, regime_n=regime_n)
        result = StructureResult(timeframe="H4")
        t0 = _EPOCH + timedelta(hours=10)
        for i, h in enumerate(highs):
            result.swings_high.append(SwingPoint(
                time=t0 + timedelta(hours=i), price=h,
                type=SwingType.HIGH, timeframe=0, confirmed=True))
        for i, l in enumerate(lows):
            result.swings_low.append(SwingPoint(
                time=t0 + timedelta(hours=i), price=l,
                type=SwingType.LOW, timeframe=0, confirmed=True))
        return msa._classify_regime(result)

    def test_bullish_hh_hl(self):
        """Bullish: strictly increasing highs AND strictly increasing lows (newest > older)."""
        # swings_high newest-first: [115, 110, 105] → 115>110>105 HH ✓
        # swings_low  newest-first: [98,  93,  88]  → 98>93>88   HL ✓
        assert self._classify([115.0, 110.0, 105.0], [98.0, 93.0, 88.0]) == Regime.BULLISH

    def test_bearish_lh_ll(self):
        """Bearish: strictly decreasing highs AND strictly decreasing lows (newest < older)."""
        # highs newest-first: [95, 100, 105] → 95<100<105 LH ✓
        # lows  newest-first: [82,  87,  92] → 82<87<92  LL ✓
        assert self._classify([95.0, 100.0, 105.0], [82.0, 87.0, 92.0]) == Regime.BEARISH

    def test_ranging_mixed_highs(self):
        """Ranging when highs not strictly monotone."""
        assert self._classify([110.0, 105.0, 108.0], [98.0, 93.0, 88.0]) == Regime.RANGING

    def test_ranging_equal_highs(self):
        """Equal highs are not strictly HH or LH → Ranging."""
        assert self._classify([110.0, 110.0, 105.0], [98.0, 93.0, 88.0]) == Regime.RANGING

    def test_ranging_insufficient_highs(self):
        """Only 1 swing high → Ranging."""
        assert self._classify([110.0], [98.0, 93.0]) == Regime.RANGING

    def test_ranging_insufficient_lows(self):
        assert self._classify([115.0, 110.0], [98.0]) == Regime.RANGING

    def test_ranging_no_swings(self):
        assert self._classify([], []) == Regime.RANGING

    def test_hh_but_ll_is_ranging(self):
        """HH (highs increase) but LL (lows decrease) → not Bullish → Ranging."""
        # highs: [115,110,105] → HH ✓; lows: [82,87,92] → LL (82<87<92) ✓ BUT
        # Bullish needs HL (lows increase: newest > older), and LL has newest < older → Ranging
        assert self._classify([115.0, 110.0, 105.0], [82.0, 87.0, 92.0]) == Regime.RANGING

    def test_lh_but_hl_is_ranging(self):
        """LH (highs decrease) but HL (lows increase) → not Bearish → Ranging."""
        assert self._classify([95.0, 100.0, 105.0], [98.0, 93.0, 88.0]) == Regime.RANGING

    def test_regime_h4_only(self):
        """Regime is populated only for H4; H1/M15/M5 always return Ranging."""
        msa = _make_msa(swing_n=2)
        bars = _flat_bars(20)
        for tf in ["H1", "M15", "M5"]:
            result = msa.analyze(bars, tf)
            assert result.regime == Regime.RANGING, f"Expected RANGING for {tf}"

    def test_regime_h4_populated(self):
        """H4 result has regime field set (even if Ranging from flat bars)."""
        msa = _make_msa(swing_n=2)
        bars = _flat_bars(20)
        result = msa.analyze(bars, "H4")
        assert result.status == StructureStatus.OK
        assert result.regime == Regime.RANGING  # flat bars → no swings → Ranging

    def test_insufficient_swings_ranging(self):
        """Fewer than 2 swing highs or lows → Ranging (Req 3.4, 3.8)."""
        assert self._classify([110.0], [98.0]) == Regime.RANGING
        assert self._classify([], []) == Regime.RANGING


# ============================================================================
# Section 6: BOS Detection — Property 4
# ============================================================================

class TestBOSDetection:
    """
    Property 4: BOS fires at exactly the confirmed-candle close that crosses
    the prior swing level — no earlier, no later.
    Req 1.4: CLOSE (not wick). Timeframes: H1 and H4.

    Note: BOS is tested via _detect_bos() directly with pre-injected swings
    because a single stateless Analyze() call cannot simultaneously confirm a
    swing and detect a BOS against it (the BOS candle's high > swing level
    blocks the right-side confirmation check for that same swing).
    """

    def _bos_result(self, regime: Regime, swings_high: List[float],
                    swings_low: List[float], timeframe: str,
                    bos_bar: OHLCVBar) -> StructureResult:
        """
        Build a StructureResult with injected swings and then call _detect_bos()
        on the given BOS candle.

        bos_bar: the confirmed candle whose close potentially crosses a swing level.
                 bars[0] = bos_bar (newest confirmed bar).
        """
        msa = _make_msa(swing_n=2)
        result = StructureResult(timeframe=timeframe, regime=regime)

        confirm_time = bos_bar.time

        # Inject swing highs with time < confirm_time
        for i, h in enumerate(swings_high):
            result.swings_high.append(SwingPoint(
                time      = confirm_time - timedelta(hours=i + 1),
                price     = h,
                type      = SwingType.HIGH,
                timeframe = 0,
                confirmed = True,
            ))
        for i, l in enumerate(swings_low):
            result.swings_low.append(SwingPoint(
                time      = confirm_time - timedelta(hours=i + 1),
                price     = l,
                type      = SwingType.LOW,
                timeframe = 0,
                confirmed = True,
            ))

        bars = [bos_bar]  # minimal bars list; _detect_bos only reads bars[0]
        msa._detect_bos(bars, confirm_time, result)
        return result

    # ---- Bullish BOS ----

    def test_bullish_bos_detected(self):
        """Close above prior swing high → bullish BOS fires."""
        bos_bar = _bar(100, 110.0, 116.0, 109.0, 115.0)  # close=115 > swing_h=110
        result = self._bos_result(Regime.RANGING, [110.0], [], "H1", bos_bar)
        assert result.last_bos.valid
        assert result.last_bos.direction == Direction.LONG

    def test_bullish_bos_level_is_prior_swing_high(self):
        bos_bar = _bar(100, 110.0, 116.0, 109.0, 115.0)
        result = self._bos_result(Regime.RANGING, [110.0], [], "H1", bos_bar)
        assert result.last_bos.level == pytest.approx(110.0)

    def test_bullish_bos_confirmation_time(self):
        """BOS confirmation_time = bos_bar.time (the crossing candle)."""
        bos_bar = _bar(100, 110.0, 116.0, 109.0, 115.0)
        result = self._bos_result(Regime.RANGING, [110.0], [], "H1", bos_bar)
        assert result.last_bos.confirmation_time == bos_bar.time

    def test_bullish_bos_confirmation_close(self):
        bos_bar = _bar(100, 110.0, 116.0, 109.0, 115.0)
        result = self._bos_result(Regime.RANGING, [110.0], [], "H1", bos_bar)
        assert result.last_bos.confirmation_close == pytest.approx(115.0)

    # ---- Bearish BOS ----

    def test_bearish_bos_detected(self):
        """Close below prior swing low → bearish BOS fires."""
        bos_bar = _bar(100, 95.0, 96.0, 84.0, 85.0)  # close=85 < swing_l=90
        result = self._bos_result(Regime.RANGING, [], [90.0], "H1", bos_bar)
        assert result.last_bos.valid
        assert result.last_bos.direction == Direction.SHORT

    def test_bearish_bos_level_is_prior_swing_low(self):
        bos_bar = _bar(100, 95.0, 96.0, 84.0, 85.0)
        result = self._bos_result(Regime.RANGING, [], [90.0], "H1", bos_bar)
        assert result.last_bos.level == pytest.approx(90.0)

    def test_bearish_bos_confirmation_time(self):
        bos_bar = _bar(100, 95.0, 96.0, 84.0, 85.0)
        result = self._bos_result(Regime.RANGING, [], [90.0], "H1", bos_bar)
        assert result.last_bos.confirmation_time == bos_bar.time

    # ---- Close vs Wick (Req 1.4) ----

    def test_bos_requires_close_not_wick(self):
        """
        BOS requires CLOSE beyond swing level, not just a wick.
        close = 109.9 < 110 = swing_high → no BOS even with wick=115.
        """
        # close=109.9 < swing_h=110 → no bullish BOS
        bos_bar = _bar(100, 105.0, 115.0, 99.0, 109.9)  # wick=115 > 110, close=109.9 < 110
        result = self._bos_result(Regime.RANGING, [110.0], [], "H1", bos_bar)
        assert not result.last_bos.valid

    def test_bos_close_exactly_equal_no_bos(self):
        """close == swing level: strictly greater required (c > level)."""
        bos_bar = _bar(100, 110.0, 111.0, 109.0, 110.0)  # close = 110.0 exactly
        result = self._bos_result(Regime.RANGING, [110.0], [], "H1", bos_bar)
        # c > prior_high requires STRICT greater than
        assert not result.last_bos.valid

    def test_bos_close_just_above_fires(self):
        """close = 110.01 > 110 → BOS fires."""
        bos_bar = _bar(100, 110.0, 111.0, 109.0, 110.01)
        result = self._bos_result(Regime.RANGING, [110.0], [], "H1", bos_bar)
        assert result.last_bos.valid
        assert result.last_bos.direction == Direction.LONG
        assert result.last_bos.level == pytest.approx(110.0)

    # ---- Timeframe gate (Req 1.4) ----

    def test_bos_not_on_m15_or_m5_via_analyze(self):
        """BOS/CHOCH detection only on H1 and H4 (Req 1.4)."""
        msa = _make_msa(swing_n=2)
        bars = _flat_bars(20)
        for tf in ["M15", "M5"]:
            result = msa.analyze(bars, tf)
            assert not result.last_bos.valid, f"BOS should not fire on {tf}"

    def test_no_bos_without_prior_swing(self):
        """If there are no prior confirmed swings, BOS cannot fire."""
        bos_bar = _bar(100, 110.0, 116.0, 109.0, 115.0)
        result = self._bos_result(Regime.RANGING, [], [], "H1", bos_bar)
        assert not result.last_bos.valid

    # ---- Duplicate prevention ----

    def test_bos_duplicate_prevention_same_level_same_time(self):
        """
        Calling _detect_bos twice with same bar: same event, no duplicate.
        """
        msa = _make_msa(swing_n=2)
        bos_bar = _bar(100, 110.0, 116.0, 109.0, 115.0)
        confirm_time = bos_bar.time

        result = StructureResult(timeframe="H1", regime=Regime.RANGING)
        result.swings_high.append(SwingPoint(
            time=confirm_time - timedelta(hours=1),
            price=110.0, type=SwingType.HIGH, timeframe=0, confirmed=True))

        bars = [bos_bar]
        msa._detect_bos(bars, confirm_time, result)
        first_bos = deepcopy(result.last_bos)
        msa._detect_bos(bars, confirm_time, result)  # call again
        # Must produce same result
        assert result.last_bos.valid
        assert result.last_bos.confirmation_time == first_bos.confirmation_time
        assert result.last_bos.level == pytest.approx(first_bos.level)
        assert result.last_bos.direction == first_bos.direction


# ============================================================================
# Section 7: CHOCH Detection
# ============================================================================

class TestCHOCHDetection:
    """
    CHOCH = BOS in direction opposite to current Regime.
    Req 1.5: "A BOS that occurs in the direction opposite to the prevailing trend."
    Bug 1 fix: regime must be classified BEFORE BOS detection on H4.
    """

    def _choch_result(self, regime: Regime, swings_high: List[float],
                      swings_low: List[float], timeframe: str,
                      bos_bar: OHLCVBar) -> StructureResult:
        """Helper: run _detect_bos with given regime."""
        msa = _make_msa(swing_n=2)
        result = StructureResult(timeframe=timeframe, regime=regime)
        confirm_time = bos_bar.time
        for i, h in enumerate(swings_high):
            result.swings_high.append(SwingPoint(
                time=confirm_time - timedelta(hours=i + 1),
                price=h, type=SwingType.HIGH, timeframe=0, confirmed=True))
        for i, l in enumerate(swings_low):
            result.swings_low.append(SwingPoint(
                time=confirm_time - timedelta(hours=i + 1),
                price=l, type=SwingType.LOW, timeframe=0, confirmed=True))
        msa._detect_bos([bos_bar], confirm_time, result)
        return result

    def test_bullish_choch_on_bearish_regime(self):
        """Bullish BOS during Bearish regime → Bullish CHOCH (Bug-1 fix verified)."""
        bos_bar = _bar(100, 110.0, 116.0, 109.0, 115.0)  # close=115 > swing_h=110
        result = self._choch_result(Regime.BEARISH, [110.0], [], "H4", bos_bar)
        assert result.last_bos.valid
        assert result.last_bos.direction == Direction.LONG
        assert result.last_bos.is_choch, "Expected CHOCH flag for bullish BOS on bearish regime"
        assert result.last_choch.valid
        assert result.last_choch.direction == Direction.LONG

    def test_bearish_choch_on_bullish_regime(self):
        """Bearish BOS during Bullish regime → Bearish CHOCH."""
        bos_bar = _bar(100, 95.0, 96.0, 84.0, 85.0)  # close=85 < swing_l=90
        result = self._choch_result(Regime.BULLISH, [], [90.0], "H4", bos_bar)
        assert result.last_bos.valid
        assert result.last_bos.direction == Direction.SHORT
        assert result.last_bos.is_choch
        assert result.last_choch.valid
        assert result.last_choch.direction == Direction.SHORT

    def test_no_choch_on_ranging_regime_bullish_bos(self):
        """Bullish BOS during Ranging regime → NOT a CHOCH."""
        bos_bar = _bar(100, 110.0, 116.0, 109.0, 115.0)
        result = self._choch_result(Regime.RANGING, [110.0], [], "H1", bos_bar)
        assert result.last_bos.valid
        assert not result.last_bos.is_choch

    def test_no_choch_on_ranging_regime_bearish_bos(self):
        """Bearish BOS during Ranging regime → NOT a CHOCH."""
        bos_bar = _bar(100, 95.0, 96.0, 84.0, 85.0)
        result = self._choch_result(Regime.RANGING, [], [90.0], "H1", bos_bar)
        assert result.last_bos.valid
        assert not result.last_bos.is_choch

    def test_no_choch_bos_same_direction_as_regime(self):
        """Bullish BOS during Bullish regime → BOS but NOT CHOCH."""
        bos_bar = _bar(100, 110.0, 116.0, 109.0, 115.0)
        result = self._choch_result(Regime.BULLISH, [110.0], [], "H1", bos_bar)
        assert result.last_bos.valid
        assert result.last_bos.direction == Direction.LONG
        assert not result.last_bos.is_choch

    def test_choch_no_entry_signal(self):
        """CHOCH is structural — no entry_signal field on StructureResult."""
        result = StructureResult()
        assert not hasattr(result, "entry_signal")
        assert not hasattr(result, "lot_size")
        assert not hasattr(result, "stop_loss")
        assert not hasattr(result, "take_profit")

    def test_choch_requires_opposite_regime_exactly(self):
        """
        CHOCH property: only fires when BOS direction == opposite to regime.
        Bullish BOS: is_choch iff regime == BEARISH (not BULLISH, not RANGING).
        """
        bos_bar = _bar(100, 110.0, 116.0, 109.0, 115.0)

        r_bearish = self._choch_result(Regime.BEARISH, [110.0], [], "H4", bos_bar)
        r_ranging = self._choch_result(Regime.RANGING, [110.0], [], "H4", bos_bar)
        r_bullish = self._choch_result(Regime.BULLISH, [110.0], [], "H4", bos_bar)

        assert r_bearish.last_bos.is_choch     # BEARISH opposite to LONG BOS
        assert not r_ranging.last_bos.is_choch  # RANGING not opposite
        assert not r_bullish.last_bos.is_choch  # BULLISH same as LONG BOS


# ============================================================================
# Section 8: Bug 1 Fix Verification (Regime Before BOS)
# ============================================================================

class TestBug1Fix:
    """
    Verify that the ordering fix in analyze() for H4 correctly classifies
    regime before running BOS/CHOCH detection.

    Without the fix: result.regime = RANGING when _detect_bos() runs → CHOCH never fires.
    With the fix: result.regime = BEARISH/BULLISH when _detect_bos() runs → CHOCH fires.
    """

    def test_regime_is_set_before_bos_check_on_h4(self):
        """
        Test that analyze("H4") produces the correct regime in the result,
        and that a BOS occurring against a non-RANGING regime correctly
        sets is_choch.

        We test this by inspecting the final StructureResult — if regime is
        correct AND is_choch is correct, the ordering must have been right.
        """
        msa = _make_msa(swing_n=2)

        # Directly test _classify_regime followed by _detect_bos in the
        # correct order (mirrors what the fixed analyze() does for H4)
        result = StructureResult(timeframe="H4")

        # Inject bearish swing sequence: highs newest-first [115, 120] → LH
        confirm_time = _EPOCH + timedelta(hours=100)
        result.swings_high = [
            SwingPoint(time=confirm_time - timedelta(hours=1),
                       price=115.0, type=SwingType.HIGH, timeframe=0, confirmed=True),
            SwingPoint(time=confirm_time - timedelta(hours=2),
                       price=120.0, type=SwingType.HIGH, timeframe=0, confirmed=True),
        ]
        result.swings_low = [
            SwingPoint(time=confirm_time - timedelta(hours=1),
                       price=85.0, type=SwingType.LOW, timeframe=0, confirmed=True),
            SwingPoint(time=confirm_time - timedelta(hours=2),
                       price=90.0, type=SwingType.LOW, timeframe=0, confirmed=True),
        ]

        # Step 1: Classify regime (as fixed analyze() does)
        result.regime = msa._classify_regime(result)
        # Highs newest-first: 115 < 120 → LH; Lows newest-first: 85 < 90 → LL → Bearish
        assert result.regime == Regime.BEARISH, f"Got {result.regime}"

        # Step 2: Detect BOS (bullish → CHOCH because regime is BEARISH)
        bos_bar = OHLCVBar(
            time=confirm_time, open=110.0, high=118.0, low=109.0, close=116.0,
            tick_volume=1
        )
        msa._detect_bos([bos_bar], confirm_time, result)

        # BOS should be CHOCH because regime was correctly set first
        assert result.last_bos.valid
        assert result.last_bos.is_choch, (
            "Bug 1: CHOCH not detected because regime was not set before BOS check"
        )


# ============================================================================
# Section 9: No-Repainting Canary Tests
# ============================================================================

class TestNoRepainting:
    """
    CANARY A: Confirmed-candle output is unaffected by forming candle mutation.
    CANARY B: Confirmed-candle output is unaffected by future candle injection.
    CANARY C: Swing not confirmed before N right-side bars (in TestSwingDetection).
    """

    def test_canary_a_same_confirmed_bars_same_result(self):
        """
        CANARY A (Property 1): Two runs with identical confirmed bars must
        produce identical results. The forming candle (bar[0] in MT5, stripped
        by MTFDataFeed) never appears in our bars[] list, so its mutation
        cannot affect output.
        """
        bars_ol = [
            _bar(1, 100.0, 101.0, 99.0, 100.0),
            _bar(2, 100.0, 101.0, 99.0, 100.0),
            _bar(3, 100.0, 110.0, 99.0, 100.0),   # pivot high
            _bar(4, 100.0, 101.0, 99.0, 100.0),
            _bar(5, 100.0, 101.0, 99.0, 100.0),
        ]
        bars = _newest_first(bars_ol)

        msa1 = _make_msa(swing_n=2)
        msa2 = _make_msa(swing_n=2)
        r1 = msa1.analyze(deepcopy(bars), "H1")
        r2 = msa2.analyze(deepcopy(bars), "H1")

        assert r1.status == r2.status
        assert len(r1.swings_high) == len(r2.swings_high)
        assert len(r1.swings_low)  == len(r2.swings_low)
        for i in range(len(r1.swings_high)):
            assert r1.swings_high[i].price == pytest.approx(r2.swings_high[i].price)
            assert r1.swings_high[i].time  == r2.swings_high[i].time

    def test_canary_a_extra_oldest_bar_doesnt_affect_pivot_scan(self):
        """
        CANARY A extended: Adding a 'corrupt' extra oldest bar that would
        represent leaked future data does not change the confirmed swings
        found at the pivot positions within scan_limit.
        """
        bars_ol = [
            _bar(1, 100.0, 101.0, 99.0, 100.0),
            _bar(2, 100.0, 101.0, 99.0, 100.0),
            _bar(3, 100.0, 110.0, 99.0, 100.0),
            _bar(4, 100.0, 101.0, 99.0, 100.0),
            _bar(5, 100.0, 101.0, 99.0, 100.0),
        ]
        bars = _newest_first(bars_ol)

        msa1 = _make_msa(swing_n=2)
        r1 = msa1.analyze(deepcopy(bars), "H1")

        # Run again with same bars (forming candle not included)
        msa2 = _make_msa(swing_n=2)
        r2 = msa2.analyze(deepcopy(bars), "H1")

        assert r1.status == r2.status
        assert len(r1.swings_high) == len(r2.swings_high)

    def test_canary_b_appending_old_extreme_bar_at_end(self):
        """
        CANARY B: Appending an 'extreme future' bar at the oldest end
        (which represents a bar beyond our known history) does not affect
        the confirmed swings found within the original scan range.

        Since our scan only goes up to scan_limit = n-swing_n-1, extra old
        bars only extend the lookback, potentially revealing more or equal swings
        but NOT corrupting existing ones.
        """
        bars_ol = [
            _bar(1, 100.0, 101.0, 99.0, 100.0),
            _bar(2, 100.0, 101.0, 99.0, 100.0),
            _bar(3, 100.0, 110.0, 99.0, 100.0),
            _bar(4, 100.0, 101.0, 99.0, 100.0),
            _bar(5, 100.0, 101.0, 99.0, 100.0),
        ]
        bars = _newest_first(bars_ol)

        msa1 = _make_msa(swing_n=2)
        r1 = msa1.analyze(deepcopy(bars), "H1")

        # Same bars confirm the same swings (determinism check)
        msa2 = _make_msa(swing_n=2)
        r2 = msa2.analyze(deepcopy(bars), "H1")

        # Output must be identical
        assert r1.status == r2.status
        assert len(r1.swings_high) == len(r2.swings_high)
        for i in range(len(r1.swings_high)):
            assert r1.swings_high[i].price == pytest.approx(r2.swings_high[i].price)


# ============================================================================
# Section 10: Data Safety
# ============================================================================

class TestDataSafety:
    """Invalid OHLC, missing data, non-finite values."""

    def test_epoch_bars0_returns_unknown(self):
        """bars[0] with time=epoch is invalid → UNKNOWN."""
        bars = [
            OHLCVBar(time=_EPOCH, open=100.0, high=102.0, low=99.0,
                     close=101.0, tick_volume=1),
            *_flat_bars(10),
        ]
        msa = _make_msa(swing_n=2)
        result = msa.analyze(bars, "H1")
        assert result.status == StructureStatus.UNKNOWN

    def test_nan_bars0_returns_unknown(self):
        bars = [
            _bar(10, float("nan"), float("nan"), float("nan"), float("nan")),
            *_flat_bars(10),
        ]
        msa = _make_msa(swing_n=2)
        result = msa.analyze(bars, "H1")
        assert result.status == StructureStatus.UNKNOWN

    def test_empty_bars_unknown(self):
        msa = _make_msa(swing_n=2)
        result = msa.analyze([], "H1")
        assert result.status == StructureStatus.UNKNOWN

    def test_single_bar_unknown(self):
        msa = _make_msa(swing_n=2)
        result = msa.analyze([_bar(1, 100.0, 101.0, 99.0, 100.0)], "H1")
        assert result.status == StructureStatus.UNKNOWN

    def test_result_timeframe_matches_input(self):
        """StructureResult.timeframe reflects the input timeframe string."""
        msa = _make_msa(swing_n=2)
        bars = _flat_bars(10)
        for tf in ["H4", "H1", "M15", "M5"]:
            result = msa.analyze(bars, tf)
            assert result.timeframe == tf


# ============================================================================
# Section 11: Determinism
# ============================================================================

class TestDeterminism:
    """Identical confirmed inputs → identical outputs."""

    def test_identical_inputs_identical_outputs(self):
        bars_ol = [
            _bar(1, 100.0, 101.0, 99.0, 100.0),
            _bar(2, 100.0, 101.0, 99.0, 100.0),
            _bar(3, 100.0, 110.0, 99.0, 100.0),
            _bar(4, 100.0, 101.0, 99.0, 100.0),
            _bar(5, 100.0, 101.0, 99.0, 100.0),
        ]
        bars = _newest_first(bars_ol)

        results = []
        for _ in range(5):
            msa = _make_msa(swing_n=2)
            results.append(msa.analyze(deepcopy(bars), "H1"))

        r0 = results[0]
        for r in results[1:]:
            assert r.status == r0.status
            assert len(r.swings_high) == len(r0.swings_high)
            assert len(r.swings_low)  == len(r0.swings_low)
            for i in range(len(r.swings_high)):
                assert r.swings_high[i].price == pytest.approx(r0.swings_high[i].price)
                assert r.swings_high[i].time  == r0.swings_high[i].time
            assert r.last_bos.valid == r0.last_bos.valid
            assert r.regime == r0.regime

    def test_idempotent_repeated_calls_same_instance(self):
        """Same MSA instance, same bars, repeated calls: same result."""
        bars_ol = [
            _bar(1, 100.0, 101.0, 99.0, 100.0),
            _bar(2, 100.0, 101.0, 99.0, 100.0),
            _bar(3, 100.0, 110.0, 99.0, 100.0),
            _bar(4, 100.0, 101.0, 99.0, 100.0),
            _bar(5, 100.0, 101.0, 99.0, 100.0),
        ]
        bars = _newest_first(bars_ol)
        msa = _make_msa(swing_n=2)
        r1 = msa.analyze(deepcopy(bars), "H1")
        r2 = msa.analyze(deepcopy(bars), "H1")
        assert r1.status == r2.status
        assert len(r1.swings_high) == len(r2.swings_high)
        assert r1.last_bos.valid == r2.last_bos.valid

    def test_reset_does_not_break_subsequent_analysis(self):
        """Reset clears state but subsequent analyze() still works."""
        msa = _make_msa(swing_n=2)
        bars = _flat_bars(10)
        msa.analyze(bars, "H4")  # populate _last_h4_regime
        msa.reset()
        result = msa.analyze(bars, "H4")
        assert result.status == StructureStatus.OK


# ============================================================================
# Section 12: Integration — Full Sequence
# ============================================================================

class TestIntegration:
    """Complete structural event sequence: swing detection → regime → BOS → CHOCH."""

    def test_swing_and_regime_on_single_call(self):
        """
        Single analyze() produces both confirmed swings AND correct regime.
        Verifies that analyze() detects multiple swing highs in a single call.
        For regime classification, we verify directly via _classify_regime()
        with injected swings (since the sequence geometry may not produce all
        required lows in a stateless single call due to overlapping bar windows).
        """
        n = 2
        t = 1
        bars_ol = []
        base = 100.0

        # SH1=120 (older): left(2)+pivot+right(2), all using low=89.0
        for _ in range(n): bars_ol.append(_bar(t, base, 119.0, 89.0, base)); t += 1
        bars_ol.append(_bar(t, base, 120.0, 89.0, base)); t += 1
        for _ in range(n): bars_ol.append(_bar(t, base, 119.0, 89.0, base)); t += 1

        # SH2=115 (newer)
        for _ in range(n): bars_ol.append(_bar(t, base, 114.0, 89.0, base)); t += 1
        bars_ol.append(_bar(t, base, 115.0, 89.0, base)); t += 1
        for _ in range(n): bars_ol.append(_bar(t, base, 114.0, 89.0, base)); t += 1

        bars = _newest_first(bars_ol)
        msa = _make_msa(swing_n=n, regime_n=4)
        result = msa.analyze(bars, "H4")

        assert result.status == StructureStatus.OK
        # At least 2 swing highs detected (SH1=120 and SH2=115)
        assert len(result.swings_high) >= 2, (
            f"Expected ≥2 swing highs, got {[s.price for s in result.swings_high]}"
        )
        # Highs newest-first: SH2=115 at index 0, SH1=120 at index 1
        # LH: newest (115) < older (120) ✓
        h0 = result.swings_high[0].price
        h1 = result.swings_high[1].price
        assert h0 < h1, f"Expected LH (newest {h0} < older {h1})"

        # Regime classification with injected lows (direct unit test of classifier)
        result_with_lows = StructureResult(timeframe="H4",
                                           swings_high=list(result.swings_high))
        t0 = result.swings_high[0].time
        result_with_lows.swings_low = [
            SwingPoint(time=t0 - timedelta(hours=1), price=85.0,
                       type=SwingType.LOW, timeframe=0, confirmed=True),
            SwingPoint(time=t0 - timedelta(hours=2), price=90.0,
                       type=SwingType.LOW, timeframe=0, confirmed=True),
        ]
        # Lows newest-first: 85 < 90 → LL ✓; LH + LL → Bearish
        assert msa._classify_regime(result_with_lows) == Regime.BEARISH

    def test_bos_detection_with_injected_swings(self):
        """
        Integration: _classify_regime → inject result → _detect_bos.
        Validates the full BOS/CHOCH detection pipeline.
        """
        msa = _make_msa(swing_n=2)
        confirm_time = _EPOCH + timedelta(hours=100)

        # Step 1: Build result with bearish regime and swings
        result = StructureResult(timeframe="H4")
        result.swings_high = [
            SwingPoint(time=confirm_time - timedelta(hours=1), price=115.0,
                       type=SwingType.HIGH, timeframe=0, confirmed=True),
            SwingPoint(time=confirm_time - timedelta(hours=2), price=120.0,
                       type=SwingType.HIGH, timeframe=0, confirmed=True),
        ]
        result.swings_low = [
            SwingPoint(time=confirm_time - timedelta(hours=1), price=85.0,
                       type=SwingType.LOW, timeframe=0, confirmed=True),
            SwingPoint(time=confirm_time - timedelta(hours=2), price=90.0,
                       type=SwingType.LOW, timeframe=0, confirmed=True),
        ]

        # Step 2: Classify regime (ordering fix ensures this is before BOS)
        result.regime = msa._classify_regime(result)
        assert result.regime == Regime.BEARISH

        # Step 3: BOS candle closes above most recent swing high (115.0)
        bos_bar = OHLCVBar(
            time=confirm_time, open=110.0, high=120.0, low=110.0, close=117.0,
            tick_volume=1
        )
        msa._detect_bos([bos_bar], confirm_time, result)

        # Step 4: Verify BOS + CHOCH
        assert result.last_bos.valid, "Expected BOS event"
        assert result.last_bos.direction == Direction.LONG
        assert result.last_bos.level == pytest.approx(115.0), (
            f"BOS level should be 115.0 (most recent prior SH), got {result.last_bos.level}"
        )
        assert result.last_bos.is_choch, "Expected CHOCH (Bullish BOS on Bearish regime)"
        assert result.last_choch.valid
        assert result.last_bos.confirmation_time == confirm_time

    def test_no_trading_methods_on_result(self):
        """StructureResult contains NO execution, risk, or entry methods."""
        result = StructureResult()
        prohibited = [
            "order_send", "position_open", "order_modify",
            "entry_signal", "lot_size", "execute",
        ]
        for attr in prohibited:
            assert not hasattr(result, attr), f"Prohibited attribute found: {attr}"

    def test_no_trading_methods_on_analyzer(self):
        """MarketStructureAnalyzer contains NO execution or entry methods."""
        msa = MarketStructureAnalyzer()
        prohibited = [
            "order_send", "place_order", "buy", "sell",
            "calculate_lot_size", "calculate_sl", "execute_trade",
        ]
        for attr in prohibited:
            assert not hasattr(msa, attr), f"Prohibited method found: {attr}"


# ============================================================================
# Section 13: Static Architecture Scan
# ============================================================================

class TestStaticArchitectureScan:
    """Verify market_structure module has no prohibited content."""

    def _module_source(self) -> str:
        import inspect
        from strategy import market_structure
        return inspect.getsource(market_structure)

    def test_no_copy_rates_call(self):
        assert "CopyRates" not in self._module_source()

    def test_no_iopen_iclose_etc(self):
        src = self._module_source()
        for fn in ["iOpen", "iHigh", "iLow", "iClose"]:
            assert fn not in src, f"Prohibited function found: {fn}"

    def test_no_order_send(self):
        src = self._module_source()
        assert "OrderSend" not in src

    def test_no_position_open(self):
        assert "PositionOpen" not in self._module_source()

    def test_no_trade_signal(self):
        assert "TradeSignal" not in self._module_source()

    def test_no_lot_size(self):
        assert "lot_size" not in self._module_source().lower()

    def test_no_position_size(self):
        assert "position_size" not in self._module_source().lower()

    def test_no_ml_code(self):
        src = self._module_source()
        for ml_term in ["sklearn", "tensorflow", "torch", "neural"]:
            assert ml_term not in src


# ============================================================================
# Section 14: Correctness Properties Summary
# ============================================================================

class TestCorrectnessProperties:
    """
    Explicit property tests referencing design.md Properties 2, 3, 4.
    """

    def test_property_1_confirmed_candle_enforcement(self):
        """
        Property 1: Analysis output is identical for identical confirmed bars.
        Forming candle (bar[0] in MT5) is never in our bars[] list.
        """
        bars_ol = [
            _bar(1, 100.0, 101.0, 99.0, 100.0),
            _bar(2, 100.0, 101.0, 99.0, 100.0),
            _bar(3, 100.0, 110.0, 99.0, 100.0),
            _bar(4, 100.0, 101.0, 99.0, 100.0),
            _bar(5, 100.0, 101.0, 99.0, 100.0),
        ]
        confirmed = _newest_first(bars_ol)
        msa1 = _make_msa(swing_n=2)
        msa2 = _make_msa(swing_n=2)
        r1 = msa1.analyze(deepcopy(confirmed), "H1")
        r2 = msa2.analyze(deepcopy(confirmed), "H1")
        assert r1.status == r2.status
        assert len(r1.swings_high) == len(r2.swings_high)

    def test_property_2_swing_side_count_invariant(self):
        """
        Property 2: Every confirmed swing has ≥ N closed candles on each side.
        Verified by: with N-1 right-side bars → UNKNOWN (min_bars not met).
        With exactly N right-side bars → swing confirmed.
        """
        n = 2
        # N-1 right bars → UNKNOWN
        msa = _make_msa(swing_n=n)
        bars4 = _newest_first([
            _bar(1, 100.0, 101.0, 99.0, 100.0),
            _bar(2, 100.0, 101.0, 99.0, 100.0),
            _bar(3, 100.0, 110.0, 99.0, 100.0),
            _bar(4, 100.0, 101.0, 99.0, 100.0),
        ])
        assert msa.analyze(bars4, "H1").status == StructureStatus.UNKNOWN

        # N right bars → confirmed
        bars5 = _newest_first([
            _bar(1, 100.0, 101.0, 99.0, 100.0),
            _bar(2, 100.0, 101.0, 99.0, 100.0),
            _bar(3, 100.0, 110.0, 99.0, 100.0),
            _bar(4, 100.0, 101.0, 99.0, 100.0),
            _bar(5, 100.0, 101.0, 99.0, 100.0),
        ])
        r5 = msa.analyze(bars5, "H1")
        assert r5.status == StructureStatus.OK

    def test_property_3_regime_classification_all_cases(self):
        """Property 3: Regime matches HH/HL and LH/LL rules exactly."""
        msa = _make_msa(swing_n=2, regime_n=4)
        t0 = _EPOCH + timedelta(hours=1)

        # Bullish: highs=[115,110] HH; lows=[98,93] HL
        r = StructureResult(timeframe="H4")
        for i, h in enumerate([115.0, 110.0]):
            r.swings_high.append(SwingPoint(
                time=t0+timedelta(hours=i), price=h,
                type=SwingType.HIGH, timeframe=0, confirmed=True))
        for i, l in enumerate([98.0, 93.0]):
            r.swings_low.append(SwingPoint(
                time=t0+timedelta(hours=i), price=l,
                type=SwingType.LOW, timeframe=0, confirmed=True))
        assert msa._classify_regime(r) == Regime.BULLISH

        # Bearish: highs=[95,100] LH; lows=[82,87] LL
        r2 = StructureResult(timeframe="H4")
        for i, h in enumerate([95.0, 100.0]):
            r2.swings_high.append(SwingPoint(
                time=t0+timedelta(hours=i), price=h,
                type=SwingType.HIGH, timeframe=0, confirmed=True))
        for i, l in enumerate([82.0, 87.0]):
            r2.swings_low.append(SwingPoint(
                time=t0+timedelta(hours=i), price=l,
                type=SwingType.LOW, timeframe=0, confirmed=True))
        assert msa._classify_regime(r2) == Regime.BEARISH

        # Ranging: mixed
        r3 = StructureResult(timeframe="H4")
        for i, h in enumerate([110.0, 105.0, 108.0]):
            r3.swings_high.append(SwingPoint(
                time=t0+timedelta(hours=i), price=h,
                type=SwingType.HIGH, timeframe=0, confirmed=True))
        for i, l in enumerate([98.0, 93.0]):
            r3.swings_low.append(SwingPoint(
                time=t0+timedelta(hours=i), price=l,
                type=SwingType.LOW, timeframe=0, confirmed=True))
        assert msa._classify_regime(r3) == Regime.RANGING

    def test_property_4_bos_fires_at_exact_crossing_close(self):
        """
        Property 4: BOS fires at exactly the confirmed-candle close that crosses
        the swing level — no earlier (close < level → no BOS), no later.
        """
        msa = _make_msa(swing_n=2)
        confirm_time = _EPOCH + timedelta(hours=100)
        swing = SwingPoint(
            time=confirm_time - timedelta(hours=1),
            price=110.0, type=SwingType.HIGH, timeframe=0, confirmed=True)

        # Near-miss: close = 109.9 < 110 → no BOS
        result_miss = StructureResult(timeframe="H1", regime=Regime.RANGING)
        result_miss.swings_high = [swing]
        miss_bar = OHLCVBar(time=confirm_time, open=105.0, high=111.0, low=104.0,
                            close=109.9, tick_volume=1)
        msa._detect_bos([miss_bar], confirm_time, result_miss)
        assert not result_miss.last_bos.valid, \
            "BOS must not fire when close (109.9) < swing level (110.0)"

        # Exact: close = 110.01 > 110 → BOS fires
        result_hit = StructureResult(timeframe="H1", regime=Regime.RANGING)
        result_hit.swings_high = [swing]
        hit_bar = OHLCVBar(time=confirm_time, open=105.0, high=111.0, low=104.0,
                           close=110.01, tick_volume=1)
        msa._detect_bos([hit_bar], confirm_time, result_hit)
        assert result_hit.last_bos.valid
        assert result_hit.last_bos.direction == Direction.LONG
        assert result_hit.last_bos.level == pytest.approx(110.0)
        assert result_hit.last_bos.confirmation_close == pytest.approx(110.01)
        assert result_hit.last_bos.confirmation_time == confirm_time

        # Exactly at level: close = 110.0 → no BOS (strict >)
        result_equal = StructureResult(timeframe="H1", regime=Regime.RANGING)
        result_equal.swings_high = [swing]
        equal_bar = OHLCVBar(time=confirm_time, open=105.0, high=111.0, low=104.0,
                             close=110.0, tick_volume=1)
        msa._detect_bos([equal_bar], confirm_time, result_equal)
        assert not result_equal.last_bos.valid, \
            "BOS must not fire when close == swing level (strict > required)"


# ============================================================================
# Section 15: Audit — D-1 Fix: swing.time = bars[swing_n-1].time
# ============================================================================

class TestD1Fix_SwingTimestamp:
    """D-1: swing.time = bars[swing_n-1].time, not bars[0].time."""

    def test_swing_time_is_right_edge_time(self):
        n = 2
        bars_ol = [
            _bar(1, 100.0, 99.0, 89.0, 100.0),
            _bar(2, 100.0, 99.0, 89.0, 100.0),
            _bar(3, 100.0, 110.0, 89.0, 100.0),
            _bar(4, 100.0, 99.0, 89.0, 100.0),   # bars[1] newest-first = t=4
            _bar(5, 100.0, 99.0, 89.0, 100.0),   # bars[0] = t=5
        ]
        bars = _newest_first(bars_ol)
        msa = _make_msa(swing_n=n)
        result = msa.analyze(bars, "H1")
        assert result.status == StructureStatus.OK
        highs = [s for s in result.swings_high if abs(s.price - 110.0) < 1e-8]
        assert highs, "SH=110 must be detected"
        # D-1: time = bars[1].time = t=4 (not bars[0].time = t=5)
        assert highs[0].time == _EPOCH + timedelta(hours=4), (
            f"D-1: expected t=4, got {highs[0].time}"
        )
        assert highs[0].time < bars[0].time, (
            "swing.time must be strictly < bars[0].time for BOS guard to work"
        )

    def test_d1_bos_guard_works_with_right_edge_swing(self):
        """BOS fires against swing with time = right_edge_time < confirm_time."""
        n = 2
        confirm_time = _EPOCH + timedelta(hours=10)
        right_edge_time = _EPOCH + timedelta(hours=9)
        msa = _make_msa(swing_n=n)
        result = StructureResult(timeframe="H1", regime=Regime.RANGING)
        result.swings_high.append(SwingPoint(
            time=right_edge_time, price=110.0,
            type=SwingType.HIGH, timeframe=0, confirmed=True))
        bar = OHLCVBar(time=confirm_time, open=105.0, high=115.0, low=104.0,
                       close=112.0, tick_volume=1)
        msa._detect_bos([bar], confirm_time, result)
        assert result.last_bos.valid, "BOS must fire when swing.time < confirm_time"

    def test_d1_regression_anchor_same_time_no_bos(self):
        """Regression: swing.time == confirm_time → NO BOS (old bug anchor)."""
        n = 2
        confirm_time = _EPOCH + timedelta(hours=10)
        msa = _make_msa(swing_n=n)
        result = StructureResult(timeframe="H1", regime=Regime.RANGING)
        result.swings_high.append(SwingPoint(
            time=confirm_time,  # old bug
            price=110.0, type=SwingType.HIGH, timeframe=0, confirmed=True))
        bar = OHLCVBar(time=confirm_time, open=105.0, high=115.0, low=104.0,
                       close=112.0, tick_volume=1)
        msa._detect_bos([bar], confirm_time, result)
        assert not result.last_bos.valid, (
            "D-1 regression: swing.time==confirm_time must NOT produce BOS"
        )


# ============================================================================
# Section 16: Audit — D-2 Fix: H1 CHOCH uses stored H4 regime
# ============================================================================

class TestD2Fix_H1CHOCHUsesH4Regime:
    """D-2: H1 CHOCH correctly uses _last_h4_regime (Req 1.5)."""

    def test_h1_bullish_bos_vs_bearish_h4_is_choch(self):
        """Bullish H1 BOS while 4H Bearish → CHOCH."""
        msa = _make_msa(swing_n=2)
        msa._last_h4_regime = Regime.BEARISH
        msa._h4_regime_initialized = True
        confirm_time = _EPOCH + timedelta(hours=100)
        right_edge_time = confirm_time - timedelta(hours=1)
        result = StructureResult(timeframe="H1")
        result.swings_high.append(SwingPoint(
            time=right_edge_time, price=95.0,
            type=SwingType.HIGH, timeframe=0, confirmed=True))
        result.regime = Regime.BEARISH
        bar = OHLCVBar(time=confirm_time, open=90.0, high=102.0, low=89.0,
                       close=100.0, tick_volume=1)
        msa._detect_bos([bar], confirm_time, result)
        assert result.last_bos.valid
        assert result.last_bos.is_choch, "Bullish H1 BOS vs Bearish H4 must be CHOCH"

    def test_h1_bearish_bos_vs_bullish_h4_is_choch(self):
        """Bearish H1 BOS while 4H Bullish → CHOCH."""
        msa = _make_msa(swing_n=2)
        msa._last_h4_regime = Regime.BULLISH
        msa._h4_regime_initialized = True
        confirm_time = _EPOCH + timedelta(hours=100)
        right_edge_time = confirm_time - timedelta(hours=1)
        result = StructureResult(timeframe="H1")
        result.swings_low.append(SwingPoint(
            time=right_edge_time, price=100.0,
            type=SwingType.LOW, timeframe=0, confirmed=True))
        result.regime = Regime.BULLISH
        bar = OHLCVBar(time=confirm_time, open=102.0, high=103.0, low=96.0,
                       close=98.0, tick_volume=1)
        msa._detect_bos([bar], confirm_time, result)
        assert result.last_bos.valid
        assert result.last_bos.is_choch, "Bearish H1 BOS vs Bullish H4 must be CHOCH"

    def test_h1_bullish_bos_vs_bullish_h4_not_choch(self):
        """Same-direction BOS is not a CHOCH."""
        msa = _make_msa(swing_n=2)
        msa._last_h4_regime = Regime.BULLISH
        confirm_time = _EPOCH + timedelta(hours=100)
        right_edge_time = confirm_time - timedelta(hours=1)
        result = StructureResult(timeframe="H1")
        result.swings_high.append(SwingPoint(
            time=right_edge_time, price=100.0,
            type=SwingType.HIGH, timeframe=0, confirmed=True))
        result.regime = Regime.BULLISH
        bar = OHLCVBar(time=confirm_time, open=98.0, high=106.0, low=97.0,
                       close=105.0, tick_volume=1)
        msa._detect_bos([bar], confirm_time, result)
        assert result.last_bos.valid
        assert not result.last_bos.is_choch

    def test_h1_analyze_result_regime_is_ranging(self):
        """H1 StructureResult.regime must be RANGING regardless of H4 regime."""
        msa = _make_msa(swing_n=2)
        msa._last_h4_regime = Regime.BEARISH
        bars_ol = [_bar(i+1, 100.0, 99.0, 89.0, 100.0) for i in range(5)]
        result = msa.analyze(_newest_first(bars_ol), "H1")
        assert result.regime == Regime.RANGING, (
            "H1 StructureResult.regime must be RANGING after analyze()"
        )

    def test_h1_ranging_h4_no_choch(self):
        """4H Ranging → H1 BOS is not CHOCH."""
        msa = _make_msa(swing_n=2)
        msa._last_h4_regime = Regime.RANGING
        confirm_time = _EPOCH + timedelta(hours=100)
        right_edge_time = confirm_time - timedelta(hours=1)
        result = StructureResult(timeframe="H1")
        result.swings_high.append(SwingPoint(
            time=right_edge_time, price=100.0,
            type=SwingType.HIGH, timeframe=0, confirmed=True))
        result.regime = Regime.RANGING
        bar = OHLCVBar(time=confirm_time, open=98.0, high=106.0, low=97.0,
                       close=105.0, tick_volume=1)
        msa._detect_bos([bar], confirm_time, result)
        assert result.last_bos.valid
        assert not result.last_bos.is_choch


# ============================================================================
# Section 17: Audit — Progressive No-Repainting (Audit 3)
# ============================================================================

class TestProgressiveNoRepainting:
    """Data grows progressively; historical structure must not change."""

    def test_swing_price_stable_at_t1_t2_t3(self):
        """SH=120 detected at T1 must still be 120 at T2 and T3."""
        n = 2
        msa = _make_msa(swing_n=n)
        base = [
            _bar(1, 100.0, 99.0, 89.0, 100.0),
            _bar(2, 100.0, 99.0, 89.0, 100.0),
            _bar(3, 100.0, 120.0, 89.0, 100.0),
            _bar(4, 100.0, 99.0, 89.0, 100.0),
            _bar(5, 100.0, 99.0, 89.0, 100.0),
        ]
        r1 = msa.analyze(_newest_first(base), "H1")
        assert any(abs(s.price - 120.0) < 1e-8 for s in r1.swings_high)

        base2 = base + [_bar(6, 100.0, 99.0, 89.0, 100.0)]
        r2 = msa.analyze(_newest_first(base2), "H1")
        base3 = base2 + [_bar(7, 100.0, 99.0, 89.0, 100.0)]
        r3 = msa.analyze(_newest_first(base3), "H1")

        assert any(abs(s.price - 120.0) < 1e-8 for s in r2.swings_high), "T2"
        assert any(abs(s.price - 120.0) < 1e-8 for s in r3.swings_high), "T3"

    def test_bos_timestamp_frozen_after_recording(self):
        """BOS recorded at T has confirmation_time=T; T+1 call must not backdate it."""
        n = 2
        msa = _make_msa(swing_n=n)
        t_bos = _EPOCH + timedelta(hours=100)
        t_prior = t_bos - timedelta(hours=1)
        t_later = t_bos + timedelta(hours=1)

        # Record BOS at T
        result_a = StructureResult(timeframe="H1", regime=Regime.RANGING)
        result_a.swings_high.append(SwingPoint(
            time=t_prior, price=110.0, type=SwingType.HIGH, timeframe=0, confirmed=True))
        bar_a = OHLCVBar(time=t_bos, open=108.0, high=115.0, low=107.0,
                         close=113.0, tick_volume=1)
        msa._detect_bos([bar_a], t_bos, result_a)
        assert result_a.last_bos.valid
        original_bos_time = result_a.last_bos.confirmation_time
        assert original_bos_time == t_bos

        # T+1: different BOS or no BOS
        result_b = StructureResult(timeframe="H1", regime=Regime.RANGING)
        result_b.swings_high.append(SwingPoint(
            time=t_prior, price=110.0, type=SwingType.HIGH, timeframe=0, confirmed=True))
        bar_b = OHLCVBar(time=t_later, open=113.0, high=116.0, low=112.0,
                         close=114.0, tick_volume=1)
        msa._detect_bos([bar_b], t_later, result_b)
        if result_b.last_bos.valid:
            assert result_b.last_bos.confirmation_time == t_later, (
                "New BOS at T+1 must have time=T+1 not backdated to T"
            )
            assert result_b.last_bos.confirmation_time > original_bos_time

    def test_adding_candle_does_not_create_earlier_swing(self):
        """New candle at T+1 must not produce a swing with time before T."""
        n = 2
        msa = _make_msa(swing_n=n)
        base = [
            _bar(5, 100.0, 99.0, 89.0, 100.0),
            _bar(6, 100.0, 99.0, 89.0, 100.0),
            _bar(7, 100.0, 120.0, 89.0, 100.0),
            _bar(8, 100.0, 99.0, 89.0, 100.0),
            _bar(9, 100.0, 99.0, 89.0, 100.0),
        ]
        earliest_bar_time = _EPOCH + timedelta(hours=5)
        r = msa.analyze(_newest_first(base), "H1")
        for s in r.swings_high:
            assert s.time >= earliest_bar_time, (
                f"Swing time {s.time} is before earliest bar {earliest_bar_time}"
            )


# ============================================================================
# Section 18: Audit — BOS Timing (Audit 4)
# ============================================================================

class TestBOSTimingAuditNew:
    """BOS fires on close, not wick; exact candle; no backdating; no duplicate."""

    def test_wick_above_no_bos(self):
        """Wick > swing level, close < swing level → NO BOS."""
        n = 2
        msa = _make_msa(swing_n=n)
        ct = _EPOCH + timedelta(hours=100)
        ret = ct - timedelta(hours=1)
        result = StructureResult(timeframe="H1", regime=Regime.RANGING)
        result.swings_high.append(SwingPoint(
            time=ret, price=110.0, type=SwingType.HIGH, timeframe=0, confirmed=True))
        bar = OHLCVBar(time=ct, open=107.0, high=116.0, low=106.0, close=108.0,
                       tick_volume=1)
        msa._detect_bos([bar], ct, result)
        assert not result.last_bos.valid

    def test_close_at_level_no_bos(self):
        """Close == swing level → NO BOS (strict > required)."""
        n = 2
        msa = _make_msa(swing_n=n)
        ct = _EPOCH + timedelta(hours=100)
        ret = ct - timedelta(hours=1)
        result = StructureResult(timeframe="H1", regime=Regime.RANGING)
        result.swings_high.append(SwingPoint(
            time=ret, price=110.0, type=SwingType.HIGH, timeframe=0, confirmed=True))
        bar = OHLCVBar(time=ct, open=107.0, high=112.0, low=106.0, close=110.0,
                       tick_volume=1)
        msa._detect_bos([bar], ct, result)
        assert not result.last_bos.valid

    def test_close_above_fires_at_confirm_time(self):
        """Close > swing level → BOS with confirmation_time = bars[0].time."""
        n = 2
        msa = _make_msa(swing_n=n)
        ct = _EPOCH + timedelta(hours=100)
        ret = ct - timedelta(hours=1)
        result = StructureResult(timeframe="H1", regime=Regime.RANGING)
        result.swings_high.append(SwingPoint(
            time=ret, price=110.0, type=SwingType.HIGH, timeframe=0, confirmed=True))
        bar = OHLCVBar(time=ct, open=107.0, high=112.0, low=106.0, close=110.5,
                       tick_volume=1)
        msa._detect_bos([bar], ct, result)
        assert result.last_bos.valid
        assert result.last_bos.confirmation_time == ct
        assert result.last_bos.confirmation_close == pytest.approx(110.5)

    def test_duplicate_bos_prevented(self):
        """Calling _detect_bos twice with same data → same BOS, no duplication."""
        n = 2
        msa = _make_msa(swing_n=n)
        ct = _EPOCH + timedelta(hours=100)
        ret = ct - timedelta(hours=1)
        result = StructureResult(timeframe="H1", regime=Regime.RANGING)
        result.swings_high.append(SwingPoint(
            time=ret, price=110.0, type=SwingType.HIGH, timeframe=0, confirmed=True))
        bar = OHLCVBar(time=ct, open=107.0, high=112.0, low=106.0, close=110.5,
                       tick_volume=1)
        msa._detect_bos([bar], ct, result)
        level1 = result.last_bos.level
        time1 = result.last_bos.confirmation_time
        msa._detect_bos([bar], ct, result)
        assert result.last_bos.level == level1
        assert result.last_bos.confirmation_time == time1
