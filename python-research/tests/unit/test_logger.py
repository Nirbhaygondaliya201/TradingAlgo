"""
test_logger.py — XAU/USD MT5 EA Python Research Environment
=============================================================
Task 2.2 / 2.3: Logger module tests (Python mirror).

Tests cover:
  - Property 24: Account number masking (Req 12.6)
  - Property 25: Structured log field completeness (Req 12.1, 12.2, 12.3)
  - Log level filtering (Req 12.5)
  - ISO 8601 timestamp format (Req 12.2)
  - Output format structure (Req 12.2)
  - Financial fields in trade events (Req 12.3)
  - Instance independence / stateless behaviour
  - Log write failure is silently ignored (not raised)

Requirements: 12.1, 12.2, 12.3, 12.5, 12.6, 16.1
Correctness Properties: 24, 25
"""

from __future__ import annotations

import io
import re
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from strategy.logger import Logger, LogLevel, _utc_now_iso8601


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture(autouse=True)
def reset_logger():
    """Reset Logger class state before and after every test."""
    Logger.set_min_level(LogLevel.INFO)
    Logger.set_file_handle(None)
    yield
    Logger.set_min_level(LogLevel.INFO)
    Logger.set_file_handle(None)


# ===========================================================================
# 1. LogLevel enum
# ===========================================================================

class TestLogLevelEnum:
    def test_debug_is_0(self):    assert LogLevel.DEBUG    == 0
    def test_info_is_1(self):     assert LogLevel.INFO     == 1
    def test_warn_is_2(self):     assert LogLevel.WARN     == 2
    def test_error_is_3(self):    assert LogLevel.ERROR    == 3
    def test_critical_is_4(self): assert LogLevel.CRITICAL == 4

    def test_ordering(self):
        assert LogLevel.DEBUG < LogLevel.INFO < LogLevel.WARN \
               < LogLevel.ERROR < LogLevel.CRITICAL

    def test_str_returns_name(self):
        assert str(LogLevel.INFO)     == "INFO"
        assert str(LogLevel.CRITICAL) == "CRITICAL"

    def test_exactly_5_levels(self):
        assert len(list(LogLevel)) == 5

    def test_all_distinct(self):
        vals = list(LogLevel)
        assert len(vals) == len(set(vals))


# ===========================================================================
# 2. mask_account_number — Property 24, Requirement 12.6
# ===========================================================================

class TestMaskAccountNumber:
    """
    Property 24: For any account number string, all digits except the last
    four are replaced with '*'. The last four digits are unchanged.
    Masking must apply consistently regardless of account number length.
    """

    def test_8_digit_account(self):
        assert Logger.mask_account_number("12345678") == "****5678"

    def test_exactly_4_digits_no_masking(self):
        assert Logger.mask_account_number("1234") == "1234"

    def test_3_digits_no_masking(self):
        assert Logger.mask_account_number("123") == "123"

    def test_1_digit_no_masking(self):
        assert Logger.mask_account_number("9") == "9"

    def test_empty_string_no_masking(self):
        assert Logger.mask_account_number("") == ""

    def test_5_digits_one_masked(self):
        assert Logger.mask_account_number("12345") == "*2345"

    def test_10_digit_account(self):
        assert Logger.mask_account_number("1234567890") == "******7890"

    def test_20_digit_account_last_4_preserved(self):
        result = Logger.mask_account_number("12345678901234567890")
        assert result[-4:] == "7890"

    def test_20_digit_account_first_16_are_stars(self):
        result = Logger.mask_account_number("12345678901234567890")
        assert all(c == "*" for c in result[:-4])

    def test_last_4_always_unchanged(self):
        for n in range(5, 21):
            account = "".join(str(i % 10) for i in range(n))
            masked = Logger.mask_account_number(account)
            assert masked[-4:] == account[-4:], \
                f"Last 4 digits changed for length {n}"

    def test_only_digit_positions_masked(self):
        # All digits before last 4 must be *
        account = "9876543210"  # 10 digits
        masked = Logger.mask_account_number(account)
        assert masked == "******3210"

    def test_masking_count_correctness(self):
        # n digits -> n-4 stars + last 4 digits
        for n in range(5, 15):
            account = "1" * n
            masked = Logger.mask_account_number(account)
            star_count  = sum(1 for c in masked if c == "*")
            digit_count = sum(1 for c in masked if c.isdigit())
            assert star_count  == n - 4, f"Expected {n-4} stars for length {n}"
            assert digit_count == 4,     f"Expected 4 digits for length {n}"

    def test_property_24_large_account(self):
        """Property 24: length 20 — all but last 4 digits replaced with *."""
        account = "98765432101234567890"
        result  = Logger.mask_account_number(account)
        assert result[-4:] == "7890"
        for ch in result[:-4]:
            assert ch == "*", f"Expected '*' but got '{ch}'"


# ===========================================================================
# 3. Log level filtering — Requirement 12.5
# ===========================================================================

class TestLogLevelFiltering:
    """Entries below the configured minimum level must be suppressed."""

    def test_debug_suppressed_when_min_info(self, capsys):
        Logger.set_min_level(LogLevel.INFO)
        Logger.debug("M", "EVT")
        out = capsys.readouterr().out
        assert "DEBUG" not in out

    def test_info_passes_when_min_info(self, capsys):
        Logger.set_min_level(LogLevel.INFO)
        Logger.info("M", "EVT")
        out = capsys.readouterr().out
        assert "INFO" in out

    def test_warn_passes_when_min_info(self, capsys):
        Logger.set_min_level(LogLevel.INFO)
        Logger.warn("M", "EVT")
        out = capsys.readouterr().out
        assert "WARN" in out

    def test_all_levels_pass_when_min_debug(self, capsys):
        Logger.set_min_level(LogLevel.DEBUG)
        Logger.debug("M", "EVT")
        out = capsys.readouterr().out
        assert "DEBUG" in out

    def test_critical_always_passes(self, capsys):
        Logger.set_min_level(LogLevel.CRITICAL)
        Logger.critical("M", "EVT")
        out = capsys.readouterr().out
        assert "CRITICAL" in out

    def test_warn_and_error_suppressed_when_min_critical(self, capsys):
        Logger.set_min_level(LogLevel.CRITICAL)
        Logger.warn("M",  "EVT")
        Logger.error("M", "EVT")
        out = capsys.readouterr().out
        assert "WARN"  not in out
        assert "ERROR" not in out

    def test_default_min_level_is_info(self):
        assert Logger._min_level == LogLevel.INFO

    def test_set_min_level_persists(self):
        Logger.set_min_level(LogLevel.WARN)
        assert Logger._min_level == LogLevel.WARN


# ===========================================================================
# 4. Output format structure — Property 25, Requirements 12.1, 12.2
# ===========================================================================

class TestOutputFormat:
    """
    Property 25: every log entry must contain all required fields.
    Format: LEVEL | ISO8601_UTC | MODULE | EVENT_TYPE [| fields...]
    """

    def test_format_level_first(self, capsys):
        Logger.info("MyModule", "SIGNAL_GENERATED")
        line = capsys.readouterr().out.strip()
        assert line.startswith("INFO |"), f"Line did not start with 'INFO |': {line}"

    def test_format_contains_module(self, capsys):
        Logger.info("RiskManager", "TRADE_REJECTED")
        line = capsys.readouterr().out.strip()
        assert "RiskManager" in line

    def test_format_contains_event_type(self, capsys):
        Logger.info("M", "ORDER_SUBMITTED")
        line = capsys.readouterr().out.strip()
        assert "ORDER_SUBMITTED" in line

    def test_format_with_fields(self, capsys):
        Logger.info("M", "EVT", "ticket=99 | price=2950.50")
        line = capsys.readouterr().out.strip()
        assert "ticket=99"     in line
        assert "price=2950.50" in line

    def test_format_without_fields(self, capsys):
        Logger.info("M", "EVT")
        line = capsys.readouterr().out.strip()
        # Should have exactly 3 separators (LEVEL | TS | MODULE | EVENT)
        parts = line.split(" | ")
        assert len(parts) == 4, f"Expected 4 parts, got {len(parts)}: {parts}"

    def test_format_pipe_separator(self, capsys):
        Logger.info("M", "EVT", "k=v")
        line = capsys.readouterr().out.strip()
        assert " | " in line

    def test_iso8601_timestamp_in_output(self, capsys):
        Logger.set_min_level(LogLevel.DEBUG)
        Logger.debug("M", "EVT")
        line = capsys.readouterr().out.strip()
        # ISO 8601 pattern: YYYY-MM-DDTHH:MM:SSZ
        iso_pattern = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z"
        assert re.search(iso_pattern, line), \
            f"ISO 8601 timestamp not found in: {line}"

    def test_all_five_log_levels_produce_output(self, capsys):
        Logger.set_min_level(LogLevel.DEBUG)
        levels_and_funcs = [
            (LogLevel.DEBUG,    Logger.debug),
            (LogLevel.INFO,     Logger.info),
            (LogLevel.WARN,     Logger.warn),
            (LogLevel.ERROR,    Logger.error),
            (LogLevel.CRITICAL, Logger.critical),
        ]
        for level, func in levels_and_funcs:
            func("M", "EVT")
            out = capsys.readouterr().out.strip()
            assert level.name in out, f"{level.name} not found in output: {out}"


# ===========================================================================
# 5. ISO 8601 timestamp helper
# ===========================================================================

class TestISO8601Helper:
    def test_format_matches_pattern(self):
        ts = _utc_now_iso8601()
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", ts), \
            f"Unexpected format: {ts}"

    def test_ends_with_Z(self):
        assert _utc_now_iso8601().endswith("Z")

    def test_length_is_20(self):
        assert len(_utc_now_iso8601()) == 20

    def test_is_utc(self):
        """Timestamp must reflect UTC, not local time."""
        before = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        ts = _utc_now_iso8601()
        after = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        assert before <= ts <= after


# ===========================================================================
# 6. write_trade_event — Requirement 12.3
# ===========================================================================

class TestWriteTradeEvent:
    """Trade-related events MUST include equity, balance, and drawdown_pct."""

    def test_equity_in_output(self, capsys):
        Logger.write_trade_event(
            LogLevel.INFO, "M", "ORDER_FILLED",
            equity=10000.00, balance=9950.00, drawdown_pct=0.005)
        out = capsys.readouterr().out
        assert "equity=10000.00" in out

    def test_balance_in_output(self, capsys):
        Logger.write_trade_event(
            LogLevel.INFO, "M", "ORDER_FILLED",
            equity=10000.00, balance=9950.00, drawdown_pct=0.005)
        out = capsys.readouterr().out
        assert "balance=9950.00" in out

    def test_drawdown_pct_in_output(self, capsys):
        Logger.write_trade_event(
            LogLevel.INFO, "M", "ORDER_FILLED",
            equity=10000.00, balance=9950.00, drawdown_pct=0.005)
        out = capsys.readouterr().out
        assert "drawdown_pct=" in out

    def test_extra_fields_appended(self, capsys):
        Logger.write_trade_event(
            LogLevel.INFO, "M", "ORDER_SUBMITTED",
            equity=10000.0, balance=9950.0, drawdown_pct=0.0,
            extra_fields="ticket=42 | symbol=XAUUSD")
        out = capsys.readouterr().out
        assert "ticket=42"        in out
        assert "symbol=XAUUSD"    in out

    def test_all_three_financial_fields_present(self, capsys):
        Logger.write_trade_event(
            LogLevel.INFO, "M", "SIGNAL_APPROVED",
            equity=5000.0, balance=5000.0, drawdown_pct=0.0)
        out = capsys.readouterr().out
        assert "equity="        in out
        assert "balance="       in out
        assert "drawdown_pct="  in out

    def test_respects_min_level_filtering(self, capsys):
        Logger.set_min_level(LogLevel.WARN)
        Logger.write_trade_event(
            LogLevel.INFO, "M", "SIGNAL_GENERATED",
            equity=1.0, balance=1.0, drawdown_pct=0.0)
        out = capsys.readouterr().out
        assert out == "", "INFO trade event should be suppressed when min=WARN"


# ===========================================================================
# 7. build_fields helper
# ===========================================================================

class TestBuildFields:
    def test_single_kwarg(self):
        result = Logger.build_fields(ticket=123)
        assert result == "ticket=123"

    def test_two_kwargs(self):
        result = Logger.build_fields(symbol="XAUUSD", volume=0.1)
        assert "symbol=XAUUSD" in result
        assert "volume=0.1"    in result
        assert " | " in result

    def test_empty_kwargs_returns_empty(self):
        result = Logger.build_fields()
        assert result == ""

    def test_order_preserved(self):
        result = Logger.build_fields(a=1, b=2, c=3)
        parts = result.split(" | ")
        assert parts[0] == "a=1"
        assert parts[1] == "b=2"
        assert parts[2] == "c=3"


# ===========================================================================
# 8. File handle output
# ===========================================================================

class TestFileOutput:
    def test_writes_to_file_when_handle_set(self, capsys):
        buf = io.StringIO()
        Logger.set_file_handle(buf)
        Logger.info("M", "EVT", "key=val")
        out = buf.getvalue()
        assert "INFO" in out
        assert "key=val" in out

    def test_no_file_output_when_handle_none(self, capsys):
        Logger.set_file_handle(None)
        buf = io.StringIO()
        Logger.info("M", "EVT")
        # buf should be empty since handle not set
        assert buf.getvalue() == ""

    def test_file_output_includes_newline(self):
        buf = io.StringIO()
        Logger.set_file_handle(buf)
        Logger.info("M", "EVT")
        assert buf.getvalue().endswith("\n")


# ===========================================================================
# 9. Write failure is silently ignored
# ===========================================================================

class TestSilentFailure:
    def test_broken_file_handle_does_not_raise(self, capsys):
        """Log write failure must not crash the EA/test."""
        class BrokenFile:
            def write(self, _): raise OSError("disk full")
            def flush(self):    raise OSError("disk full")

        Logger.set_file_handle(BrokenFile())
        # Must not raise
        Logger.info("M", "EVT")
        # stdout should still have the line (Print() succeeds)
        out = capsys.readouterr().out
        assert "INFO" in out


# ===========================================================================
# 10. Statelessness / independence between calls
# ===========================================================================

class TestStatelessness:
    def test_two_calls_are_independent(self, capsys):
        Logger.info("ModA", "EVT_1", "k=1")
        Logger.info("ModB", "EVT_2", "k=2")
        out = capsys.readouterr().out
        lines = [l for l in out.splitlines() if l.strip()]
        assert len(lines) == 2
        assert "ModA" in lines[0] and "EVT_1" in lines[0]
        assert "ModB" in lines[1] and "EVT_2" in lines[1]

    def test_fields_not_leaked_between_calls(self, capsys):
        Logger.info("M", "EVT_A", "secret=abc123")
        Logger.info("M", "EVT_B")
        out = capsys.readouterr().out
        lines = [l for l in out.splitlines() if l.strip()]
        assert "secret=abc123" not in lines[1], \
            "Field from previous call leaked into next call"
