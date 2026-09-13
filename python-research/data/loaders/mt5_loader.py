"""
mt5_loader.py — XAU/USD MT5 EA Python Research Environment
============================================================
Load historical OHLCV bar data via the MetaTrader 5 Python API.

This module is used ONLY in the research/analysis environment to
download historical data for backtesting. It is NOT connected to
live order execution.

The MT5 Python API (MetaTrader5 package) is an optional dependency.
If it is not installed, this loader raises a clear ImportError.

Requirements: 16.2
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd


class MT5Loader:
    """
    Load historical OHLCV data from a running MetaTrader 5 terminal
    using the MetaTrader5 Python package.

    Requires:
        pip install MetaTrader5
    """

    # MT5 timeframe integer constants (matches MetaTrader5 package values)
    TIMEFRAME_MAP: dict[str, int] = {
        "M5":  5,
        "M15": 15,
        "H1":  60,
        "H4":  240,
    }

    def __init__(self, symbol: str = "XAUUSD") -> None:
        self.symbol = symbol
        self._mt5 = MT5Loader._import_mt5()

    @staticmethod
    def _import_mt5():
        try:
            import MetaTrader5 as mt5
            return mt5
        except ImportError:
            raise ImportError(
                "MetaTrader5 Python package is not installed. "
                "Install with: pip install MetaTrader5\n"
                "MT5Loader is only available in environments with MT5 installed."
            )

    def connect(self) -> bool:
        """Initialize and connect to MT5 terminal. Returns True on success."""
        return bool(self._mt5.initialize())

    def disconnect(self) -> None:
        """Shut down MT5 terminal connection."""
        self._mt5.shutdown()

    def load(
        self,
        timeframe: str,
        n_bars: int = 5000,
        from_date: Optional[datetime] = None,
    ) -> pd.DataFrame:
        """
        Load up to n_bars of OHLCV history for self.symbol.

        Parameters
        ----------
        timeframe : one of "M5", "M15", "H1", "H4"
        n_bars    : maximum number of bars to retrieve
        from_date : optional UTC start date (default: earliest available)

        Returns
        -------
        pd.DataFrame with columns: time, open, high, low, close, tick_volume
        Sorted oldest-first (ascending time).
        """
        if timeframe not in self.TIMEFRAME_MAP:
            raise ValueError(
                f"Unsupported timeframe '{timeframe}'. "
                f"Supported: {list(self.TIMEFRAME_MAP.keys())}")

        mt5_tf = self.TIMEFRAME_MAP[timeframe]

        if from_date is not None:
            rates = self._mt5.copy_rates_from(
                self.symbol, mt5_tf, from_date, n_bars)
        else:
            rates = self._mt5.copy_rates_from_pos(
                self.symbol, mt5_tf, 0, n_bars)

        if rates is None or len(rates) == 0:
            raise RuntimeError(
                f"MT5 returned no data for {self.symbol} {timeframe}. "
                f"Error: {self._mt5.last_error()}")

        df = pd.DataFrame(rates)

        # MT5 uses 'time' as Unix timestamp (seconds) and 'tick_volume'
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df[["time", "open", "high", "low", "close", "tick_volume"]]
        df = df.sort_values("time").reset_index(drop=True)

        return df
