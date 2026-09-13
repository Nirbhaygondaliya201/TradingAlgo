"""
test_phase1_checkpoint.py — XAU/USD MT5 EA Python Research Environment
=======================================================================
Task 7: Phase 1 Integration Checkpoint Tests.

This file tests the INTEGRATION of all Phase 1 foundation modules.
It does NOT test individual module internals (those are in their own
test files). This file tests that the modules work together correctly.

Checkpoint areas:
  A. Fresh startup
  B. Valid persisted state — save, restart, reload
  C. Corrupted state — SAFE_MODE, new trading blocked
  D. DataFeed confirmed-candle protection (canary test)
  E. MTF independence — H4/H1/M15/M5 state tracking
  F. Symbol-property failure — safe failure
  G. Reinitialization — deterministic behaviour
  H. Logger failure — infrastructure does not crash
  I. Circuit breaker — INIT_FAILED

Correctness-property regression:
  Property 1  — confirmed-candle enforcement
  Property 22 — state round-trip
  Property 23 — daily drawdown restoration
  Property 24 — log masking
  Property 25 — log field completeness
  Property 30 — state persistence integrity

Requirements: Phase 1 integration (all Phase 1 requirements)
"""

from __future__ import annotations

import io
from datetime import datetime, timezone
from pathlib import Path
from typing import List

import pandas as pd
import pytest

# Foundation modules
from strategy.types import (
    EAState, LiquidityPool, OHLCVBar,
    PoolStatus, PoolSide, SymbolProperties,
)
from strategy.logger import Logger, LogLevel
from config.config import ConfigLoader
from data.loaders.symbol_props import SymbolPropertiesLoader, SymbolPropertiesError
from data.loaders.data_feed import ConfirmedCandleFeed
from strategy.state_manager import (
    StateManager, StateLoadResult,
    build_payload, compute_crc32, STATE_FILE_VERSION, SAFE_MODE_FLAG_FILENAME,
)

_UTC   = timezone.utc
_EPOCH = datetime(1970, 1, 1, tzinfo=_UTC)
SYMBOL = "XAUUSD"
SUFFIX = "1234"


# ---------------------------------------------------------------------------
# Helpers shared across checkpoint tests
# ---------------------------------------------------------------------------

def _make_ohlcv(n: int) -> pd.DataFrame:
    rows = []
    for i in range(n):
        o = 2000.0 + i
        rows.append({"time": datetime(2026,1,1,i,0,0,tzinfo=_UTC),
                     "open": o, "high": o+1, "low": o-1,
                     "close": o+0.5, "tick_volume": 100})
    return pd.DataFrame(rows)


def _make_feed(n: int = 20) -> ConfirmedCandleFeed:
    df = _make_ohlcv(n)
    return ConfirmedCandleFeed({"H4": df, "H1": df, "M15": df, "M5": df})


def _make_state(symbol: str = SYMBOL) -> EAState:
    return EAState(
        daily_drawdown_pct=2.5, daily_open_equity=10000.0,
        total_drawdown_ref_equity=10000.0, consecutive_losses=2,
        cooldown_start_utc=_EPOCH, circuit_breaker_triggered=False,
        safe_mode_active=False,
        last_update_utc=datetime.now(tz=_UTC),
        state_file_version=STATE_FILE_VERSION,
        symbol=symbol, account_suffix=SUFFIX, checksum=0,
    )


def _save_state_file(path: Path, state: EAState,
                     pools: List[LiquidityPool] = None) -> None:
    if pools is None:
        pools = []
    payload = build_payload(state, pools)
    crc32   = compute_crc32(payload)
    path.write_text(payload + f"CHECKSUM={crc32:08X}\n", encoding="utf-8")


# ===========================================================================
# A. Fresh startup
# ===========================================================================

class TestCheckpointA_FreshStartup:
    """A: Initialize foundation, verify expected clean state."""

    def test_A1_fresh_state_has_safe_defaults(self, tmp_path):
        mgr = StateManager(tmp_path / "state.txt", SYMBOL, SUFFIX)
        result = mgr.load_state()
        assert result == StateLoadResult.FRESH_START
        assert mgr.state.daily_drawdown_pct        == 0.0
        assert mgr.state.consecutive_losses        == 0
        assert mgr.state.circuit_breaker_triggered is False
        assert mgr.state.safe_mode_active          is False

    def test_A2_fresh_start_does_not_enter_safe_mode(self, tmp_path):
        mgr = StateManager(tmp_path / "state.txt", SYMBOL, SUFFIX)
        mgr.load_state()
        assert not mgr.is_in_safe_mode()

    def test_A3_datafeed_initializes_cleanly(self):
        feed = _make_feed()
        for tf in ("H4", "H1", "M15", "M5"):
            assert feed.get_last_bar_time(tf) is None

    def test_A4_symbol_properties_invalid_before_load(self):
        sp = SymbolProperties()
        assert sp.is_valid is False

    def test_A5_logger_works_from_fresh_state(self, capsys):
        Logger.set_min_level(LogLevel.INFO)
        Logger.info("CheckpointA", "FRESH_START_EVENT", "module=test")
        out = capsys.readouterr().out
        assert "INFO" in out
        assert "FRESH_START_EVENT" in out

    def test_A6_config_validates_defaults(self):
        raw = {
            "ea": {"magic_number": 20260901},
            "market_structure": {"swing_side_candles": 2, "regime_swing_count": 4,
                                 "ranging_mode_enabled": False},
            "liquidity": {"pool_atr_tolerance": 0.5, "max_active_pools": 20},
            "atr": {"atr_period": 14, "atr_min_multiplier": 0.5,
                    "atr_max_multiplier": 2.5, "atr_sl_multiplier": 1.5,
                    "unavailable_timeout_minutes": 5},
            "momentum": {"lookback": 10},
            "session": {
                "london": {"enabled": True, "start_utc": "07:00", "end_utc": "12:00",
                           "utc_offset_hours": 0},
                "new_york": {"enabled": True, "start_utc": "13:00", "end_utc": "17:00",
                             "utc_offset_hours": 0},
                "london_ny_overlap": {"enabled": True, "start_utc": "13:00",
                                      "end_utc": "15:00", "utc_offset_hours": 0},
            },
            "spread": {"max_spread_points": 30},
            "news": {"news_protection_mode": "BLOCK", "min_impact_level": "High",
                     "pre_event_minutes": 30, "post_event_minutes": 15,
                     "max_list_age_hours": 24, "stale_fallback": "BLOCK",
                     "news_events_file": "config/news_events.csv"},
            "risk": {"risk_per_trade_pct": 1.0, "max_lot_size": 0.5,
                     "max_open_trades": 2, "daily_max_drawdown_pct": 5.0,
                     "total_max_drawdown_pct": 15.0, "min_rr": 1.5,
                     "min_free_margin_pct": 150.0},
            "consecutive_loss": {"max_consecutive_losses": 5, "cooldown_hours": 24},
            "execution": {"max_retries": 3, "retry_delay_ms": 500,
                          "max_signal_age_seconds": 0, "max_freeze_skips": 5},
            "logger": {"min_log_level": "INFO"},
            "state": {"state_file_path": "xauusd_ea_state.txt"},
        }
        cfg = ConfigLoader.from_dict(raw)
        assert cfg.risk_per_trade_pct == 1.0
        assert cfg.magic_number == 20260901


# ===========================================================================
# B. Valid persisted state — save, restart, reload
# ===========================================================================

class TestCheckpointB_ValidPersistedState:
    """B: Save valid state, restart, reload — verify state restored."""

    def test_B1_save_and_reload_returns_ok(self, tmp_path):
        mgr = StateManager(tmp_path / "state.txt", SYMBOL, SUFFIX)
        mgr.state = _make_state()
        mgr.save_state()
        mgr2 = StateManager(tmp_path / "state.txt", SYMBOL, SUFFIX)
        result = mgr2.load_state()
        assert result == StateLoadResult.OK

    def test_B2_state_fields_survive_restart(self, tmp_path):
        state = _make_state()
        _save_state_file(tmp_path / "state.txt", state)
        mgr = StateManager(tmp_path / "state.txt", SYMBOL, SUFFIX)
        mgr.load_state()
        assert mgr.state.daily_drawdown_pct   == pytest.approx(2.5)
        assert mgr.state.consecutive_losses   == 2
        assert mgr.state.safe_mode_active     is False

    def test_B3_pool_registry_survives_restart(self, tmp_path):
        pools = [
            LiquidityPool(price_level=2950.0, tolerance_band=12.0,
                          status=PoolStatus.ACTIVE, side=PoolSide.ABOVE,
                          created_timestamp=datetime(2026,9,9,6,0,0,tzinfo=_UTC),
                          swept_timestamp=_EPOCH),
        ]
        _save_state_file(tmp_path / "state.txt", _make_state(), pools)
        mgr = StateManager(tmp_path / "state.txt", SYMBOL, SUFFIX)
        mgr.load_state()
        assert len(mgr.pool_registry) == 1
        assert mgr.pool_registry[0].price_level == pytest.approx(2950.0)
        assert mgr.pool_registry[0].status == PoolStatus.ACTIVE

    def test_B4_new_trading_not_blocked_after_valid_load(self, tmp_path):
        _save_state_file(tmp_path / "state.txt", _make_state())
        mgr = StateManager(tmp_path / "state.txt", SYMBOL, SUFFIX)
        mgr.load_state()
        assert not mgr.is_in_safe_mode()


# ===========================================================================
# C. Corrupted state — SAFE_MODE, new trading blocked
# ===========================================================================

class TestCheckpointC_CorruptedState:
    """C: Corrupt state, restart, verify SAFE_MODE, verify trading blocked."""

    def test_C1_corrupted_state_triggers_safe_mode(self, tmp_path):
        _save_state_file(tmp_path / "state.txt", _make_state())
        # Corrupt CHECKSUM line
        content = (tmp_path / "state.txt").read_text("utf-8")
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if line.startswith("CHECKSUM="):
                lines[i] = "CHECKSUM=00000000"
        (tmp_path / "state.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        mgr = StateManager(tmp_path / "state.txt", SYMBOL, SUFFIX)
        result = mgr.load_state()
        assert result == StateLoadResult.SAFE_MODE

    def test_C2_safe_mode_blocks_new_trading(self, tmp_path):
        _save_state_file(tmp_path / "state.txt", _make_state())
        (tmp_path / "state.txt").write_text("corrupt\n", encoding="utf-8")
        mgr = StateManager(tmp_path / "state.txt", SYMBOL, SUFFIX)
        mgr.load_state()
        assert mgr.is_in_safe_mode()

    def test_C3_sentinel_flag_created_on_safe_mode(self, tmp_path):
        (tmp_path / "state.txt").write_text("bad content\n", encoding="utf-8")
        mgr = StateManager(tmp_path / "state.txt", SYMBOL, SUFFIX)
        mgr.load_state()
        flag = tmp_path / SAFE_MODE_FLAG_FILENAME
        assert flag.exists()

    def test_C4_corrupted_state_does_not_restore_tradable_state(self, tmp_path):
        """No code path in Phase 1 where invalid state silently becomes tradable."""
        _save_state_file(tmp_path / "state.txt", _make_state())
        content = (tmp_path / "state.txt").read_text("utf-8")
        (tmp_path / "state.txt").write_text(
            content.replace("DAILY_DRAWDOWN_PCT=2.5000000000",
                            "DAILY_DRAWDOWN_PCT=99.9999999999"),
            encoding="utf-8")
        mgr = StateManager(tmp_path / "state.txt", SYMBOL, SUFFIX)
        result = mgr.load_state()
        # Either SAFE_MODE (CRC mismatch) or SAFE_MODE (validation failure)
        # Either way, new trading must be blocked
        assert mgr.is_in_safe_mode() or result == StateLoadResult.SAFE_MODE


# ===========================================================================
# D. DataFeed confirmed-candle protection — canary test
# ===========================================================================

class TestCheckpointD_DataFeedCanary:
    """D: Property 1 canary — mutate forming candle, verify result unchanged."""

    def test_D1_forming_candle_mutation_does_not_affect_result(self):
        n  = 20
        df = pd.DataFrame([{
            "time": datetime(2026,1,1,i,0,0,tzinfo=_UTC),
            "open": 2000.0+i, "high": 2001.0+i, "low": 1999.0+i,
            "close": 2000.5+i, "tick_volume": 100,
        } for i in range(n)])

        feed1 = ConfirmedCandleFeed({"H1": df.copy()})

        # Corrupt the forming candle (bar at as_of_index=10) with extreme values
        df2 = df.copy()
        df2.at[10, "open"]  = 999999.0
        df2.at[10, "high"]  = 999999.0
        df2.at[10, "low"]   = 0.0001
        df2.at[10, "close"] = 999999.0
        feed2 = ConfirmedCandleFeed({"H1": df2})

        r1 = feed1.get_bars("H1", as_of_index=10)
        r2 = feed2.get_bars("H1", as_of_index=10)

        assert r1.bars_available == r2.bars_available
        for b1, b2 in zip(r1.bars, r2.bars):
            assert b1.time  == b2.time
            assert b1.close == b2.close

    def test_D2_bar_0_never_in_result(self):
        feed = _make_feed(10)
        forming_time = datetime(2026,1,1,5,0,0,tzinfo=_UTC)  # index 5
        result = feed.get_bars("H1", as_of_index=5)
        times = [b.time for b in result.bars]
        assert forming_time not in times

    def test_D3_as_of_0_returns_nothing(self):
        feed = _make_feed(5)
        result = feed.get_bars("H1", as_of_index=0)
        assert result.bars_available == 0
        assert len(result.error_reason) > 0


# ===========================================================================
# E. MTF independence — H4/H1/M15/M5 state tracking
# ===========================================================================

class TestCheckpointE_MTFIndependence:
    def test_E1_four_timeframes_independent(self):
        feed = _make_feed(20)
        t_h4 = datetime(2026,1,1,4,0,0,tzinfo=_UTC)
        t_h1 = datetime(2026,1,1,1,0,0,tzinfo=_UTC)
        feed.update_last_bar_time("H4",  t_h4)
        feed.update_last_bar_time("H1",  t_h1)
        # M15 and M5 must still be None
        assert feed.get_last_bar_time("M15") is None
        assert feed.get_last_bar_time("M5")  is None
        assert feed.get_last_bar_time("H4")  == t_h4
        assert feed.get_last_bar_time("H1")  == t_h1

    def test_E2_reset_clears_all_timeframes(self):
        feed = _make_feed(20)
        for tf in ("H4","H1","M15","M5"):
            feed.update_last_bar_time(tf, datetime(2026,1,1,tzinfo=_UTC))
        feed.reset_last_bar_times()
        for tf in ("H4","H1","M15","M5"):
            assert feed.get_last_bar_time(tf) is None

    def test_E3_statemanager_reset_does_not_affect_datafeed(self, tmp_path):
        """StateManager reset must not introduce stale bar times in DataFeed."""
        feed = _make_feed(20)
        feed.update_last_bar_time("H1", datetime(2026,1,1,5,0,0,tzinfo=_UTC))
        # StateManager fresh start
        mgr = StateManager(tmp_path / "state.txt", SYMBOL, SUFFIX)
        mgr.load_state()
        # DataFeed must be unchanged
        assert feed.get_last_bar_time("H1") == datetime(2026,1,1,5,0,0,tzinfo=_UTC)


# ===========================================================================
# F. Symbol-property failure — safe failure
# ===========================================================================

class TestCheckpointF_SymbolPropertyFailure:
    def test_F1_missing_point_raises(self):
        d = {"tick_size":0.01,"tick_value":1.0,"contract_size":100.0,
             "lot_step":0.01,"min_lot":0.01,"max_lot":500.0,
             "stop_level_points":0,"freeze_level_points":0,"margin_initial":0.0,
             "digits":2}
        with pytest.raises(SymbolPropertiesError):
            SymbolPropertiesLoader.from_dict(d)

    def test_F2_zero_contract_size_raises(self):
        d = {"point":0.01,"tick_size":0.01,"tick_value":1.0,"contract_size":0.0,
             "lot_step":0.01,"min_lot":0.01,"max_lot":500.0,
             "stop_level_points":0,"freeze_level_points":0,"margin_initial":0.0}
        with pytest.raises(SymbolPropertiesError):
            SymbolPropertiesLoader.from_dict(d)

    def test_F3_negative_tick_value_raises(self):
        d = {"point":0.01,"tick_size":0.01,"tick_value":-1.0,"contract_size":100.0,
             "lot_step":0.01,"min_lot":0.01,"max_lot":500.0,
             "stop_level_points":0,"freeze_level_points":0,"margin_initial":0.0}
        with pytest.raises(SymbolPropertiesError):
            SymbolPropertiesLoader.from_dict(d)

    def test_F4_invalid_props_is_valid_is_false(self):
        sp = SymbolProperties()
        assert sp.is_valid is False

    def test_F5_symbol_props_not_in_config(self):
        """Broker properties must not be in Config (Req 14.4)."""
        from config.config import Config
        assert not hasattr(Config(), "point")
        assert not hasattr(Config(), "contract_size")
        assert not hasattr(Config(), "tick_value")


# ===========================================================================
# G. Reinitialization — deterministic behaviour
# ===========================================================================

class TestCheckpointG_Reinitialization:
    def test_G1_datafeed_reinitialization_is_deterministic(self):
        feed = _make_feed(10)
        for tf in ("H4","H1","M15","M5"):
            feed.update_last_bar_time(tf, datetime(2026,1,1,tzinfo=_UTC))
        feed.reset_last_bar_times()
        for tf in ("H4","H1","M15","M5"):
            assert feed.get_last_bar_time(tf) is None

    def test_G2_state_manager_multiple_inits_deterministic(self, tmp_path):
        """Multiple fresh starts produce the same default state."""
        mgr1 = StateManager(tmp_path / "state1.txt", SYMBOL, SUFFIX)
        mgr1.load_state()
        mgr2 = StateManager(tmp_path / "state2.txt", SYMBOL, SUFFIX)
        mgr2.load_state()
        assert mgr1.state.daily_drawdown_pct == mgr2.state.daily_drawdown_pct
        assert mgr1.state.consecutive_losses == mgr2.state.consecutive_losses

    def test_G3_config_revalidation_is_deterministic(self):
        raw = {"ea":{"magic_number":20260901},
               "market_structure":{"swing_side_candles":2,"regime_swing_count":4,
                                   "ranging_mode_enabled":False},
               "liquidity":{"pool_atr_tolerance":0.5,"max_active_pools":20},
               "atr":{"atr_period":14,"atr_min_multiplier":0.5,
                      "atr_max_multiplier":2.5,"atr_sl_multiplier":1.5,
                      "unavailable_timeout_minutes":5},
               "momentum":{"lookback":10},
               "session":{"london":{"enabled":True,"start_utc":"07:00",
                                    "end_utc":"12:00","utc_offset_hours":0},
                          "new_york":{"enabled":True,"start_utc":"13:00",
                                      "end_utc":"17:00","utc_offset_hours":0},
                          "london_ny_overlap":{"enabled":True,"start_utc":"13:00",
                                               "end_utc":"15:00","utc_offset_hours":0}},
               "spread":{"max_spread_points":30},
               "news":{"news_protection_mode":"BLOCK","min_impact_level":"High",
                       "pre_event_minutes":30,"post_event_minutes":15,
                       "max_list_age_hours":24,"stale_fallback":"BLOCK",
                       "news_events_file":"config/news_events.csv"},
               "risk":{"risk_per_trade_pct":1.0,"max_lot_size":0.5,
                       "max_open_trades":2,"daily_max_drawdown_pct":5.0,
                       "total_max_drawdown_pct":15.0,"min_rr":1.5,
                       "min_free_margin_pct":150.0},
               "consecutive_loss":{"max_consecutive_losses":5,"cooldown_hours":24},
               "execution":{"max_retries":3,"retry_delay_ms":500,
                            "max_signal_age_seconds":0,"max_freeze_skips":5},
               "logger":{"min_log_level":"INFO"},
               "state":{"state_file_path":"xauusd_ea_state.txt"}}
        c1 = ConfigLoader.from_dict(raw)
        c2 = ConfigLoader.from_dict(raw)
        assert c1 == c2


# ===========================================================================
# H. Logger failure — infrastructure does not crash
# ===========================================================================

class TestCheckpointH_LoggerFailure:
    def test_H1_broken_file_handle_does_not_crash(self, capsys):
        class BrokenStream:
            def write(self, _):   raise OSError("disk full")
            def flush(self):      raise OSError("disk full")
        Logger.set_file_handle(BrokenStream())
        # Must not raise — infrastructure must never crash because logging fails
        Logger.info("CheckpointH", "EVENT", "k=v")
        Logger.set_file_handle(None)
        out = capsys.readouterr().out
        assert "INFO" in out  # stdout still works

    def test_H2_none_file_handle_is_safe(self, capsys):
        Logger.set_file_handle(None)
        Logger.info("CheckpointH", "NULL_HANDLE", "k=v")
        out = capsys.readouterr().out
        assert "NULL_HANDLE" in out

    def test_H3_critical_safe_mode_event_is_loggable(self, capsys):
        Logger.set_min_level(LogLevel.CRITICAL)
        Logger.critical("StateManager", "SAFE_MODE_ENTERED",
                        "reason=CRC32_MISMATCH safe_mode=ENTERED")
        out = capsys.readouterr().out
        assert "CRITICAL"         in out
        assert "SAFE_MODE_ENTERED" in out
        Logger.set_min_level(LogLevel.INFO)


# ===========================================================================
# I. Circuit breaker — INIT_FAILED
# ===========================================================================

class TestCheckpointI_CircuitBreaker:
    def test_I1_circuit_breaker_returns_init_failed(self, tmp_path):
        import dataclasses
        state = dataclasses.replace(_make_state(), circuit_breaker_triggered=True)
        _save_state_file(tmp_path / "state.txt", state)
        mgr = StateManager(tmp_path / "state.txt", SYMBOL, SUFFIX)
        result = mgr.load_state()
        assert result == StateLoadResult.INIT_FAILED

    def test_I2_circuit_breaker_false_returns_ok(self, tmp_path):
        _save_state_file(tmp_path / "state.txt", _make_state())
        mgr = StateManager(tmp_path / "state.txt", SYMBOL, SUFFIX)
        result = mgr.load_state()
        assert result == StateLoadResult.OK

    def test_I3_circuit_breaker_is_explicit_in_state(self, tmp_path):
        payload = build_payload(_make_state(), [])
        assert "CIRCUIT_BREAKER_TRIGGERED=0" in payload


# ===========================================================================
# Correctness property regression
# ===========================================================================

class TestCorrectnessProperties:
    """Re-run all Phase 1 correctness properties explicitly."""

    # Property 1 — confirmed-candle enforcement
    def test_P1_confirmed_candle_enforcement(self):
        n  = 15
        df = pd.DataFrame([{
            "time": datetime(2026,1,1,i,0,0,tzinfo=_UTC),
            "open": 2000.0+i, "high": 2001.0+i, "low": 1999.0+i,
            "close": 2000.5+i, "tick_volume": 100,
        } for i in range(n)])
        feed1 = ConfirmedCandleFeed({"H1": df.copy()})
        df2 = df.copy()
        df2.at[7, "open"] = df2.at[7, "high"] = df2.at[7, "low"] = df2.at[7, "close"] = 999999.0
        feed2 = ConfirmedCandleFeed({"H1": df2})
        r1 = feed1.get_bars("H1", as_of_index=7)
        r2 = feed2.get_bars("H1", as_of_index=7)
        assert r1.bars_available == r2.bars_available
        for b1, b2 in zip(r1.bars, r2.bars):
            assert b1.close == b2.close

    # Property 22 — state round-trip
    def test_P22_state_round_trip(self, tmp_path):
        state = _make_state()
        _save_state_file(tmp_path / "state.txt", state)
        mgr = StateManager(tmp_path / "state.txt", SYMBOL, SUFFIX)
        mgr.load_state()
        assert mgr.state.daily_drawdown_pct   == pytest.approx(2.5)
        assert mgr.state.consecutive_losses   == 2

    # Property 23 — daily drawdown restoration on same-day restart
    def test_P23_same_day_restores_daily_drawdown(self, tmp_path):
        import dataclasses
        state = dataclasses.replace(_make_state(),
                                    daily_drawdown_pct=3.75,
                                    last_update_utc=datetime.now(tz=_UTC))
        _save_state_file(tmp_path / "state.txt", state)
        mgr = StateManager(tmp_path / "state.txt", SYMBOL, SUFFIX)
        mgr.load_state()
        assert mgr.state.daily_drawdown_pct == pytest.approx(3.75)

    # Property 24 — log masking for account numbers
    def test_P24_account_masking(self):
        assert Logger.mask_account_number("12345678") == "****5678"
        assert Logger.mask_account_number("1234")     == "1234"
        for n in range(5, 21):
            acct   = "1" * n
            masked = Logger.mask_account_number(acct)
            assert masked[-4:] == acct[-4:]
            assert all(c == "*" for c in masked[:-4])

    # Property 25 — structured log field completeness
    def test_P25_log_field_completeness(self, capsys):
        Logger.set_min_level(LogLevel.DEBUG)
        Logger.debug("ModuleX", "EVENT_TYPE", "key=value")
        out = capsys.readouterr().out.strip()
        import re
        assert re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", out)
        assert "ModuleX"    in out
        assert "EVENT_TYPE" in out
        Logger.set_min_level(LogLevel.INFO)

    # Property 30 — state persistence integrity
    def test_P30_corruption_triggers_safe_mode(self, tmp_path):
        _save_state_file(tmp_path / "state.txt", _make_state())
        content = (tmp_path / "state.txt").read_text("utf-8")
        lines   = content.splitlines()
        for i, line in enumerate(lines):
            if line.startswith("CHECKSUM="):
                lines[i] = "CHECKSUM=DEADBEEF"
        (tmp_path / "state.txt").write_text("\n".join(lines)+"\n", encoding="utf-8")
        mgr = StateManager(tmp_path / "state.txt", SYMBOL, SUFFIX)
        result = mgr.load_state()
        assert result == StateLoadResult.SAFE_MODE
        assert mgr.is_in_safe_mode()

    def test_P30_valid_state_does_not_trigger_safe_mode(self, tmp_path):
        _save_state_file(tmp_path / "state.txt", _make_state())
        mgr = StateManager(tmp_path / "state.txt", SYMBOL, SUFFIX)
        result = mgr.load_state()
        assert result == StateLoadResult.OK
        assert not mgr.is_in_safe_mode()


# ===========================================================================
# Architecture boundary verification (Python-level)
# ===========================================================================

class TestArchitectureBoundaries:
    def test_no_order_execution_in_data_feed(self):
        """DataFeed must not contain order execution concepts."""
        import inspect
        import data.loaders.data_feed as df_module
        source = inspect.getsource(df_module)
        for term in ("OrderSend", "OrderModify", "OrderClose",
                     "PositionOpen", "execute_order"):
            assert term not in source, f"'{term}' found in data_feed.py"

    def test_no_strategy_logic_in_state_manager(self):
        """StateManager must not contain strategy concepts."""
        import inspect
        import strategy.state_manager as sm_module
        source = inspect.getsource(sm_module)
        for term in ("swing_detection", "liquidity_pool_detect",
                     "bos_signal", "choch_signal", "entry_confirm"):
            assert term not in source, f"'{term}' found in state_manager.py"

    def test_no_hardcoded_broker_values_in_datafeed(self):
        """DataFeed must not hardcode point/lot/contract values."""
        import inspect
        import data.loaders.data_feed as df_module
        source = inspect.getsource(df_module)
        # Hardcoded XAUUSD-specific values
        for val in ("contract_size=100", "lot_step=0.01", "tick_value=1.0"):
            assert val not in source.replace(" ", ""), \
                f"Hardcoded broker value '{val}' found in data_feed.py"

    def test_logger_is_cross_cutting_no_upward_calls(self):
        """Logger must not import or call any strategy/risk/execution module."""
        import inspect
        import strategy.logger as logger_module
        source = inspect.getsource(logger_module)
        for term in ("RiskManager", "OrderExecutor", "EntryConfirmation",
                     "MarketStructure", "LiquidityDetector"):
            assert term not in source, f"'{term}' found in logger.py"
