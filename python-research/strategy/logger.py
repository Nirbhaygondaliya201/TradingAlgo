"""
logger.py — XAU/USD MT5 EA Python Research Environment
=======================================================
Stateless structured logging utility mirroring ``include/utils/Logger.mqh``.

Output format (one line per entry):
    LEVEL | ISO8601_UTC | MODULE | EVENT_TYPE | field1=val1 | field2=val2 ...

Rules that match MQL5 Logger exactly:
  - Log-level filtering: entries below the configured minimum are suppressed.
  - Account-number masking: all digits except the last four are replaced with *.
  - Log write failures do not raise exceptions — they are silently ignored.
  - No mutable state except the configurable minimum level and optional file handle.
  - No references to any other module (Logger is a cross-cutting utility).

Design reference: §2.14 Logger
Requirements: 12.1, 12.2, 12.3, 12.5, 12.6, 13.6, 16.1
Correctness Properties: 24, 25
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from enum import IntEnum
from typing import Optional, TextIO


# ---------------------------------------------------------------------------
# Log level — integer values match MQL5 LogLevel enum
# ---------------------------------------------------------------------------

class LogLevel(IntEnum):
    DEBUG    = 0
    INFO     = 1
    WARN     = 2
    ERROR    = 3
    CRITICAL = 4

    def __str__(self) -> str:
        return self.name  # "DEBUG", "INFO", etc.


# ---------------------------------------------------------------------------
# Logger (stateless utility class — all methods are static / class-level)
# ---------------------------------------------------------------------------

class Logger:
    """
    Stateless structured logging utility.
    Mirror of MQL5 Logger.mqh.

    All methods are class methods.
    No module-level mutable state except ``_min_level`` and ``_file_handle``
    which are class-level attributes acting as the global configuration.
    """

    _min_level:   LogLevel     = LogLevel.INFO      # Requirement 12.5 default
    _file_handle: Optional[TextIO] = None           # Optional file output

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    @classmethod
    def set_min_level(cls, level: LogLevel) -> None:
        """Set the minimum log severity. Entries below this are suppressed."""
        cls._min_level = level

    @classmethod
    def set_file_handle(cls, handle: Optional[TextIO]) -> None:
        """Attach an open text file for persistent log output. None = disabled."""
        cls._file_handle = handle

    # ------------------------------------------------------------------
    # Core write method
    # Requirement 12.2: format = LEVEL | ISO8601_UTC | MODULE | EVENT | fields
    # ------------------------------------------------------------------

    @classmethod
    def write(
        cls,
        level:      LogLevel,
        module:     str,
        event_type: str,
        fields:     str = "",
    ) -> None:
        """
        Core log method. Silently ignores write failures.
        Suppresses entries below the configured minimum level.
        """
        if level < cls._min_level:
            return

        ts   = _utc_now_iso8601()
        line = (
            f"{level.name} | {ts} | {module} | {event_type} | {fields}"
            if fields
            else f"{level.name} | {ts} | {module} | {event_type}"
        )

        # Print to stdout (mirrors MT5 Print() → Experts log)
        try:
            print(line, flush=True)
        except Exception:  # noqa: BLE001 — silently ignored per design
            pass

        # Write to file handle if set
        if cls._file_handle is not None:
            try:
                cls._file_handle.write(line + "\n")
                cls._file_handle.flush()
            except Exception:  # noqa: BLE001 — silently ignored per design
                pass

    # ------------------------------------------------------------------
    # Convenience level wrappers
    # ------------------------------------------------------------------

    @classmethod
    def debug(cls, module: str, event_type: str, fields: str = "") -> None:
        cls.write(LogLevel.DEBUG, module, event_type, fields)

    @classmethod
    def info(cls, module: str, event_type: str, fields: str = "") -> None:
        cls.write(LogLevel.INFO, module, event_type, fields)

    @classmethod
    def warn(cls, module: str, event_type: str, fields: str = "") -> None:
        cls.write(LogLevel.WARN, module, event_type, fields)

    @classmethod
    def error(cls, module: str, event_type: str, fields: str = "") -> None:
        cls.write(LogLevel.ERROR, module, event_type, fields)

    @classmethod
    def critical(cls, module: str, event_type: str, fields: str = "") -> None:
        cls.write(LogLevel.CRITICAL, module, event_type, fields)

    # ------------------------------------------------------------------
    # write_trade_event
    # Requirement 12.3: trade-related events MUST include equity, balance,
    # and open drawdown percentage.
    # ------------------------------------------------------------------

    @classmethod
    def write_trade_event(
        cls,
        level:        LogLevel,
        module:       str,
        event_type:   str,
        equity:       float,
        balance:      float,
        drawdown_pct: float,
        extra_fields: str = "",
    ) -> None:
        """
        Write a trade-related log entry with mandatory financial context.
        Requirement 12.3
        """
        financial = (
            f"equity={equity:.2f} | balance={balance:.2f} | "
            f"drawdown_pct={drawdown_pct:.4f}"
        )
        all_fields = f"{financial} | {extra_fields}" if extra_fields else financial
        cls.write(level, module, event_type, all_fields)

    # ------------------------------------------------------------------
    # mask_account_number
    # Requirement 12.6, Correctness Property 24.
    # Replaces all digit characters except the last four with '*'.
    # Non-digit characters are preserved in position.
    #
    # Examples:
    #   "12345678" → "****5678"
    #   "1234"     → "1234"   (exactly 4 digits — nothing masked)
    #   "123"      → "123"    (fewer than 4 digits — no masking)
    # ------------------------------------------------------------------

    @staticmethod
    def mask_account_number(account_str: str) -> str:
        """
        Replace all but the last 4 digit characters with '*'.
        Non-digit characters (e.g. dashes) are kept in position.
        Property 24.
        """
        if len(account_str) <= 4:
            return account_str

        result = []
        for i, ch in enumerate(account_str):
            if i < len(account_str) - 4 and ch.isdigit():
                result.append("*")
            else:
                result.append(ch)
        return "".join(result)

    # ------------------------------------------------------------------
    # build_fields
    # Convenience helper: assembles key=value pairs into a pipe-separated
    # fields string matching the log format. Mirrors Logger.BuildFields().
    # ------------------------------------------------------------------

    @staticmethod
    def build_fields(**kwargs: object) -> str:
        """
        Build a pipe-separated key=value string from keyword arguments.
        Example: Logger.build_fields(ticket=123, price=2950.50)
                 → "ticket=123 | price=2950.5"
        """
        return " | ".join(f"{k}={v}" for k, v in kwargs.items())


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _utc_now_iso8601() -> str:
    """Return the current UTC time as an ISO 8601 string (e.g. 2026-09-09T07:30:00Z)."""
    now = datetime.now(tz=timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")
