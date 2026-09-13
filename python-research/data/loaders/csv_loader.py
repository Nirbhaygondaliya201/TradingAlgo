"""
csv_loader.py — XAU/USD MT5 EA Python Research Environment
============================================================
Load OHLCV bar data from CSV files into DataFrames suitable
for use with ConfirmedCandleFeed.

Expected CSV column names (case-insensitive):
    time, open, high, low, close, tick_volume (optional)

Time column must be parseable by pandas (ISO 8601 or MT5 export format).

Requirements: 16.2
"""

from __future__ import annotations

from pathlib import Path
import pandas as pd


class CSVLoader:
    """Load OHLCV data from CSV files."""

    # Column aliases: maps various export naming conventions to canonical names
    _COLUMN_ALIASES: dict[str, str] = {
        "date":        "time",
        "datetime":    "time",
        "timestamp":   "time",
        "volume":      "tick_volume",
        "tickvolume":  "tick_volume",
        "real_volume": "tick_volume",
    }

    @staticmethod
    def load(file_path: str | Path,
             timeframe: str = "UNKNOWN",
             datetime_col: str = "time") -> pd.DataFrame:
        """
        Load a CSV file and return a DataFrame with canonical column names.

        Parameters
        ----------
        file_path    : path to the CSV file
        timeframe    : label used in error messages only
        datetime_col : name of the datetime column in the CSV

        Returns
        -------
        pd.DataFrame with columns: time, open, high, low, close, tick_volume
        Rows sorted oldest-first (ascending time).
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"CSV file not found: {path}")

        df = pd.read_csv(path)

        # Normalise column names to lowercase
        df.columns = [c.strip().lower() for c in df.columns]

        # Apply aliases
        df.rename(columns=CSVLoader._COLUMN_ALIASES, inplace=True)

        # Check required columns
        required = {"time", "open", "high", "low", "close"}
        missing  = required - set(df.columns)
        if missing:
            raise ValueError(
                f"CSV for '{timeframe}' is missing required columns: {missing}")

        # Add tick_volume if absent
        if "tick_volume" not in df.columns:
            df["tick_volume"] = 0

        # Parse time column
        df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce")
        invalid_times = df["time"].isna().sum()
        if invalid_times > 0:
            df = df.dropna(subset=["time"])

        # Sort oldest-first
        df = df.sort_values("time").reset_index(drop=True)

        # Keep only canonical columns in consistent order
        df = df[["time", "open", "high", "low", "close", "tick_volume"]]

        return df
