"""
data_feed.py — XAU/USD MT5 EA Python Research Environment
==========================================================
Confirmed-candle enforcing data feed for the Python research environment.

Mirrors the MQL5 ``MTFDataFeed`` module. Provides a single access boundary
between raw OHLCV data and the Analysis layer.

Confirmed-candle guarantee (Correctness Property 1):
    ``get_bars(timeframe, as_of_index)`` returns ``data[0:as_of_index]``.
    This structurally prevents look-ahead: as_of_index is the *current*
    (forming) bar index; the slice excludes it by never including index
    ``as_of_index`` or beyond. The backtest engine passes
    ``as_of_index = current_bar_index`` on every iteration, which is
    equivalent to MT5 requesting from bar index 1.

Key rules:
    - ``as_of_index`` must be >= 1 (backtest engine must not pass 0).
    - Returned slice is ``data[0:as_of_index]`` — strictly before the
      forming bar.
    - If the slice is empty (insufficient history), returns empty list/array.
    - Data is passed in as a DataFrame indexed by time; each row is one
      confirmed bar.
    - No look-ahead bias is possible through this interface.

Design reference: §2.2 MultiTimeframe_DataFeed, §Backtesting Architecture
Requirements: 1.1, 1.6, 4.5, 15.5, 16.2, 16.3
Correctness Property: 1
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional
import pandas as pd

from strategy.types import OHLCVBar


# ---------------------------------------------------------------------------
# DataFeedError
# ---------------------------------------------------------------------------

class DataFeedError(ValueError):
    """Raised when a data feed operation fails a precondition."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"DataFeed error: {reason}")
        self.reason = reason


# ---------------------------------------------------------------------------
# DataFeedResult (mirrors MQL5 DataFeedResult struct)
# ---------------------------------------------------------------------------

@dataclass
class DataFeedResult:
    """
    Result from a get_bars() call. Mirrors MQL5 DataFeedResult.
    Consumers MUST check bars_available > 0 before reading bars.
    """
    bars:            List[OHLCVBar] = field(default_factory=list)
    bars_available:  int            = 0
    is_new_candle:   bool           = False
    error_reason:    str            = ""


# ---------------------------------------------------------------------------
# ConfirmedCandleFeed
# ---------------------------------------------------------------------------

class ConfirmedCandleFeed:
    """
    Confirmed-candle enforcing data feed for the Python backtest engine.

    Usage in backtest loop::

        feed = ConfirmedCandleFeed(ohlcv_dict)
        for bar_index in range(warmup, len(data)):
            result_4h  = feed.get_bars("H4",  bar_index)
            result_1h  = feed.get_bars("H1",  bar_index)
            result_15m = feed.get_bars("M15", bar_index)
            result_5m  = feed.get_bars("M5",  bar_index)
            # All results contain only confirmed bars (before bar_index)
    """

    # Supported timeframe identifiers (mirroring MT5 ENUM_TIMEFRAMES names)
    SUPPORTED_TIMEFRAMES = {"H4", "H1", "M15", "M5"}

    def __init__(self, ohlcv_data: dict[str, pd.DataFrame]) -> None:
        """
        Parameters
        ----------
        ohlcv_data : dict
            Keys are timeframe strings ("H4", "H1", "M15", "M5").
            Values are DataFrames with columns: time, open, high, low, close,
            tick_volume. Index must be integer (0, 1, 2, ...).
            Rows must be sorted oldest-first (ascending time).
        """
        self._data: dict[str, pd.DataFrame] = {}
        self._last_bar_time: dict[str, Optional[datetime]] = {}

        for tf, df in ohlcv_data.items():
            if tf not in self.SUPPORTED_TIMEFRAMES:
                raise DataFeedError(
                    f"Unsupported timeframe '{tf}'. "
                    f"Supported: {self.SUPPORTED_TIMEFRAMES}")
            self._validate_dataframe(tf, df)
            self._data[tf] = df.reset_index(drop=True)
            self._last_bar_time[tf] = None

    # ------------------------------------------------------------------
    # get_bars
    # ------------------------------------------------------------------

    def get_bars(self, timeframe: str, as_of_index: int) -> DataFeedResult:
        """
        Return all confirmed bars strictly before ``as_of_index``.

        Parameters
        ----------
        timeframe   : one of "H4", "H1", "M15", "M5"
        as_of_index : the current (forming) bar index in the data array.
                      Must be >= 1.  All bars at index < as_of_index are
                      confirmed and safe to use.

        Returns
        -------
        DataFeedResult with:
            bars           : list of OHLCVBar (oldest at bars[-1],
                             newest confirmed at bars[0])
            bars_available : number of bars returned
            is_new_candle  : True if the newest confirmed bar's time changed
            error_reason   : non-empty if bars_available == 0
        """
        result = DataFeedResult()

        # Precondition: as_of_index must be >= 1 (prevents look-ahead)
        if as_of_index < 1:
            result.error_reason = (
                f"as_of_index={as_of_index} must be >= 1 "
                "(bar index 0 is the forming candle — never confirmed)")
            return result

        if timeframe not in self.SUPPORTED_TIMEFRAMES:
            result.error_reason = (
                f"Unsupported timeframe '{timeframe}'")
            return result

        if timeframe not in self._data:
            result.error_reason = f"No data loaded for timeframe '{timeframe}'"
            return result

        df = self._data[timeframe]
        total = len(df)

        if total == 0:
            result.error_reason = "Empty dataset for timeframe"
            return result

        # Confirmed slice: indices 0 … (as_of_index - 1)
        # This is structurally equivalent to MT5 requesting from bar index 1.
        end = min(as_of_index, total)
        slice_df = df.iloc[0:end]

        if len(slice_df) == 0:
            result.error_reason = "No confirmed bars available yet"
            return result

        # Convert to OHLCVBar list, newest-first (mirrors MT5 CopyRates order)
        bars: List[OHLCVBar] = []
        for _, row in slice_df.iloc[::-1].iterrows():
            bar = OHLCVBar(
                time        = _to_utc_datetime(row["time"]),
                open        = float(row["open"]),
                high        = float(row["high"]),
                low         = float(row["low"]),
                close       = float(row["close"]),
                tick_volume = int(row.get("tick_volume", 0)),
            )
            bars.append(bar)

        result.bars           = bars
        result.bars_available = len(bars)

        # New-candle detection
        if bars:
            newest_time = bars[0].time
            last        = self._last_bar_time.get(timeframe)
            result.is_new_candle = (last is None or newest_time != last)

        return result

    def update_last_bar_time(self, timeframe: str, new_time: datetime) -> None:
        """Record the newest confirmed bar time after processing a result."""
        if timeframe in self.SUPPORTED_TIMEFRAMES:
            self._last_bar_time[timeframe] = new_time

    def reset_last_bar_times(self) -> None:
        """Clear all stored last-bar-time values (call at (re)initialisation)."""
        for tf in self._last_bar_time:
            self._last_bar_time[tf] = None

    def get_last_bar_time(self, timeframe: str) -> Optional[datetime]:
        """Return the last-seen confirmed bar time, or None if not yet set."""
        return self._last_bar_time.get(timeframe)

    @staticmethod
    def is_timeframe_supported(timeframe: str) -> bool:
        return timeframe in ConfirmedCandleFeed.SUPPORTED_TIMEFRAMES

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_dataframe(timeframe: str, df: pd.DataFrame) -> None:
        """Validate that a DataFrame has all required columns."""
        required = {"time", "open", "high", "low", "close"}
        missing  = required - set(df.columns)
        if missing:
            raise DataFeedError(
                f"DataFrame for '{timeframe}' is missing columns: {missing}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _to_utc_datetime(val: object) -> datetime:
    """Convert a time value to a UTC-aware datetime."""
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=timezone.utc)
        return val
    if isinstance(val, pd.Timestamp):
        dt = val.to_pydatetime()
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt
    # Fallback: epoch
    return datetime(1970, 1, 1, tzinfo=timezone.utc)
