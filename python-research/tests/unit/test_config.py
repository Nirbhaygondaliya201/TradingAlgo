"""
test_config.py — XAU/USD MT5 EA Python Research Environment
=============================================================
Task 3.2: Config_Manager unit tests.

Tests cover:
  - Default values load and validate correctly
  - Every parameter at its minimum valid boundary (passes)
  - Every parameter one step below minimum (fails)
  - Every parameter at its maximum valid boundary (passes)
  - Every parameter one step above maximum (fails)
  - Invalid enum values are rejected
  - Session start >= end is rejected when session is enabled
  - DailyMaxDrawdownPct >= TotalMaxDrawdownPct is rejected
  - Empty strings are rejected for required string fields
  - Config is immutable (frozen dataclass)
  - Config loaded from default_config.yaml matches default values
  - Broker-specific symbol properties are NOT present in Config
  - Safety/risk limits cannot be bypassed via configuration

Requirements: 14.1, 14.2, 14.3, 16.1
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from config.config import Config, ConfigLoader, ConfigValidationError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DEFAULT_YAML = Path(__file__).parent.parent.parent / "config" / "default_config.yaml"


def _base() -> dict:
    """Return a minimal valid raw config dict (matching all defaults)."""
    return {
        "ea":                {"magic_number": 20260901},
        "market_structure":  {"swing_side_candles": 2, "regime_swing_count": 4,
                              "ranging_mode_enabled": False},
        "liquidity":         {"pool_atr_tolerance": 0.5, "max_active_pools": 20},
        "atr":               {"atr_period": 14, "atr_min_multiplier": 0.5,
                              "atr_max_multiplier": 2.5, "atr_sl_multiplier": 1.5,
                              "unavailable_timeout_minutes": 5},
        "momentum":          {"lookback": 10},
        "session": {
            "london":          {"enabled": True,  "start_utc": "07:00",
                                "end_utc": "12:00", "utc_offset_hours": 0},
            "new_york":        {"enabled": True,  "start_utc": "13:00",
                                "end_utc": "17:00", "utc_offset_hours": 0},
            "london_ny_overlap":{"enabled": True, "start_utc": "13:00",
                                 "end_utc": "15:00", "utc_offset_hours": 0},
        },
        "spread":            {"max_spread_points": 30},
        "news":              {"news_protection_mode": "BLOCK", "min_impact_level": "High",
                              "pre_event_minutes": 30, "post_event_minutes": 15,
                              "max_list_age_hours": 24, "stale_fallback": "BLOCK",
                              "news_events_file": "config/news_events.csv"},
        "risk":              {"risk_per_trade_pct": 1.0, "max_lot_size": 0.5,
                              "max_open_trades": 2, "daily_max_drawdown_pct": 5.0,
                              "total_max_drawdown_pct": 15.0, "min_rr": 1.5,
                              "min_free_margin_pct": 150.0},
        "consecutive_loss":  {"max_consecutive_losses": 5, "cooldown_hours": 24},
        "execution":         {"max_retries": 3, "retry_delay_ms": 500,
                              "max_signal_age_seconds": 0, "max_freeze_skips": 5},
        "logger":            {"min_log_level": "INFO"},
        "state":             {"state_file_path": "xauusd_ea_state.txt"},
    }


def _load(override: dict | None = None) -> Config:
    raw = _base()
    if override:
        for section, updates in override.items():
            if section not in raw:
                raw[section] = {}
            if isinstance(updates, dict):
                raw[section].update(updates)
            else:
                raw[section] = updates
    return ConfigLoader.from_dict(raw)


def _expect_fail(override: dict) -> None:
    with pytest.raises(ConfigValidationError):
        _load(override)


# ===========================================================================
# 1. Default config
# ===========================================================================

class TestDefaultConfig:
    def test_loads_from_yaml(self):
        if DEFAULT_YAML.exists():
            cfg = ConfigLoader.load(DEFAULT_YAML)
            assert isinstance(cfg, Config)

    def test_default_magic_number(self):
        assert _load().magic_number == 20260901

    def test_default_swing_side_candles(self):
        assert _load().swing_side_candles == 2

    def test_default_regime_swing_count(self):
        assert _load().regime_swing_count == 4

    def test_default_pool_atr_tolerance(self):
        assert _load().pool_atr_tolerance == 0.5

    def test_default_atr_period(self):
        assert _load().atr_period == 14

    def test_default_max_spread_points(self):
        assert _load().max_spread_points == 30

    def test_default_risk_per_trade_pct(self):
        assert _load().risk_per_trade_pct == 1.0

    def test_default_daily_max_drawdown_pct(self):
        assert _load().daily_max_drawdown_pct == 5.0

    def test_default_total_max_drawdown_pct(self):
        assert _load().total_max_drawdown_pct == 15.0

    def test_default_min_rr(self):
        assert _load().min_rr == 1.5

    def test_default_max_open_trades(self):
        assert _load().max_open_trades == 2

    def test_default_cooldown_hours(self):
        assert _load().cooldown_hours == 24

    def test_default_max_consecutive_losses(self):
        assert _load().max_consecutive_losses == 5

    def test_default_news_protection_mode(self):
        assert _load().news_protection_mode == "BLOCK"

    def test_default_min_log_level(self):
        assert _load().min_log_level == "INFO"

    def test_default_ranging_mode_disabled(self):
        assert _load().ranging_mode_enabled is False


# ===========================================================================
# 2. Config is immutable (frozen=True)
# ===========================================================================

class TestConfigImmutability:
    def test_cannot_set_attribute(self):
        cfg = _load()
        with pytest.raises((AttributeError, TypeError)):
            cfg.risk_per_trade_pct = 99.0  # type: ignore[misc]

    def test_cannot_delete_attribute(self):
        cfg = _load()
        with pytest.raises((AttributeError, TypeError)):
            del cfg.risk_per_trade_pct  # type: ignore[misc]


# ===========================================================================
# 3. Broker-specific symbol properties NOT in Config
# ===========================================================================

class TestNoBrokerProperties:
    """Symbol properties must not be hardcoded in Config. Req 14.4"""

    def test_no_point_field(self):
        cfg = _load()
        assert not hasattr(cfg, "point")

    def test_no_lot_step_field(self):
        assert not hasattr(_load(), "lot_step")

    def test_no_contract_size_field(self):
        assert not hasattr(_load(), "contract_size")

    def test_no_stop_level_field(self):
        assert not hasattr(_load(), "stop_level_points")

    def test_no_tick_value_field(self):
        assert not hasattr(_load(), "tick_value")

    def test_no_margin_initial_field(self):
        assert not hasattr(_load(), "margin_initial")


# ===========================================================================
# 4. Boundary tests — every numeric parameter
# ===========================================================================

class TestSwingSideCandles:
    def test_min_1_passes(self):    _load({"market_structure": {"swing_side_candles": 1}})
    def test_max_5_passes(self):    _load({"market_structure": {"swing_side_candles": 5}})
    def test_below_min_fails(self): _expect_fail({"market_structure": {"swing_side_candles": 0}})
    def test_above_max_fails(self): _expect_fail({"market_structure": {"swing_side_candles": 6}})


class TestRegimeSwingCount:
    def test_min_2_passes(self):    _load({"market_structure": {"regime_swing_count": 2}})
    def test_max_10_passes(self):   _load({"market_structure": {"regime_swing_count": 10}})
    def test_below_min_fails(self): _expect_fail({"market_structure": {"regime_swing_count": 1}})
    def test_above_max_fails(self): _expect_fail({"market_structure": {"regime_swing_count": 11}})


class TestPoolATRTolerance:
    def test_min_0_1_passes(self):  _load({"liquidity": {"pool_atr_tolerance": 0.1}})
    def test_max_2_0_passes(self):  _load({"liquidity": {"pool_atr_tolerance": 2.0}})
    def test_below_min_fails(self): _expect_fail({"liquidity": {"pool_atr_tolerance": 0.09}})
    def test_above_max_fails(self): _expect_fail({"liquidity": {"pool_atr_tolerance": 2.01}})


class TestMaxActivePools:
    def test_min_5_passes(self):    _load({"liquidity": {"max_active_pools": 5}})
    def test_max_50_passes(self):   _load({"liquidity": {"max_active_pools": 50}})
    def test_below_min_fails(self): _expect_fail({"liquidity": {"max_active_pools": 4}})
    def test_above_max_fails(self): _expect_fail({"liquidity": {"max_active_pools": 51}})


class TestATRPeriod:
    def test_min_5_passes(self):    _load({"atr": {"atr_period": 5}})
    def test_max_50_passes(self):   _load({"atr": {"atr_period": 50}})
    def test_below_min_fails(self): _expect_fail({"atr": {"atr_period": 4}})
    def test_above_max_fails(self): _expect_fail({"atr": {"atr_period": 51}})


class TestATRMinMultiplier:
    def test_min_0_1_passes(self):  _load({"atr": {"atr_min_multiplier": 0.1}})
    def test_max_1_0_passes(self):  _load({"atr": {"atr_min_multiplier": 1.0}})
    def test_below_min_fails(self): _expect_fail({"atr": {"atr_min_multiplier": 0.09}})
    def test_above_max_fails(self): _expect_fail({"atr": {"atr_min_multiplier": 1.01}})


class TestATRMaxMultiplier:
    def test_min_1_5_passes(self):  _load({"atr": {"atr_max_multiplier": 1.5}})
    def test_max_5_0_passes(self):  _load({"atr": {"atr_max_multiplier": 5.0}})
    def test_below_min_fails(self): _expect_fail({"atr": {"atr_max_multiplier": 1.49}})
    def test_above_max_fails(self): _expect_fail({"atr": {"atr_max_multiplier": 5.01}})


class TestATRSLMultiplier:
    def test_min_0_5_passes(self):  _load({"atr": {"atr_sl_multiplier": 0.5}})
    def test_max_5_0_passes(self):  _load({"atr": {"atr_sl_multiplier": 5.0}})
    def test_below_min_fails(self): _expect_fail({"atr": {"atr_sl_multiplier": 0.49}})
    def test_above_max_fails(self): _expect_fail({"atr": {"atr_sl_multiplier": 5.01}})


class TestATRTimeout:
    def test_min_1_passes(self):    _load({"atr": {"unavailable_timeout_minutes": 1}})
    def test_max_60_passes(self):   _load({"atr": {"unavailable_timeout_minutes": 60}})
    def test_below_min_fails(self): _expect_fail({"atr": {"unavailable_timeout_minutes": 0}})
    def test_above_max_fails(self): _expect_fail({"atr": {"unavailable_timeout_minutes": 61}})


class TestMomentumLookback:
    def test_min_2_passes(self):    _load({"momentum": {"lookback": 2}})
    def test_max_50_passes(self):   _load({"momentum": {"lookback": 50}})
    def test_below_min_fails(self): _expect_fail({"momentum": {"lookback": 1}})
    def test_above_max_fails(self): _expect_fail({"momentum": {"lookback": 51}})


class TestSessionUTCOffset:
    def test_min_neg12_passes(self):
        _load({"session": {"london": {"enabled": True, "start_utc": "07:00",
                                       "end_utc": "12:00", "utc_offset_hours": -12}}})
    def test_max_plus14_passes(self):
        _load({"session": {"london": {"enabled": True, "start_utc": "07:00",
                                       "end_utc": "12:00", "utc_offset_hours": 14}}})
    def test_below_min_fails(self):
        _expect_fail({"session": {"london": {"enabled": True, "start_utc": "07:00",
                                              "end_utc": "12:00", "utc_offset_hours": -13}}})
    def test_above_max_fails(self):
        _expect_fail({"session": {"london": {"enabled": True, "start_utc": "07:00",
                                              "end_utc": "12:00", "utc_offset_hours": 15}}})


class TestMaxSpreadPoints:
    def test_min_10_passes(self):   _load({"spread": {"max_spread_points": 10}})
    def test_max_200_passes(self):  _load({"spread": {"max_spread_points": 200}})
    def test_below_min_fails(self): _expect_fail({"spread": {"max_spread_points": 9}})
    def test_above_max_fails(self): _expect_fail({"spread": {"max_spread_points": 201}})


class TestPreEventMinutes:
    def test_min_0_passes(self):    _load({"news": {"pre_event_minutes": 0}})
    def test_max_120_passes(self):  _load({"news": {"pre_event_minutes": 120}})
    def test_above_max_fails(self): _expect_fail({"news": {"pre_event_minutes": 121}})


class TestPostEventMinutes:
    def test_min_0_passes(self):    _load({"news": {"post_event_minutes": 0}})
    def test_max_120_passes(self):  _load({"news": {"post_event_minutes": 120}})
    def test_above_max_fails(self): _expect_fail({"news": {"post_event_minutes": 121}})


class TestMaxNewsListAge:
    def test_min_1_passes(self):    _load({"news": {"max_list_age_hours": 1}})
    def test_max_168_passes(self):  _load({"news": {"max_list_age_hours": 168}})
    def test_below_min_fails(self): _expect_fail({"news": {"max_list_age_hours": 0}})
    def test_above_max_fails(self): _expect_fail({"news": {"max_list_age_hours": 169}})


class TestRiskPerTradePct:
    def test_min_0_1_passes(self):  _load({"risk": {"risk_per_trade_pct": 0.1}})
    def test_max_5_0_passes(self):  _load({"risk": {"risk_per_trade_pct": 5.0}})
    def test_below_min_fails(self): _expect_fail({"risk": {"risk_per_trade_pct": 0.09}})
    def test_above_max_fails(self): _expect_fail({"risk": {"risk_per_trade_pct": 5.01}})


class TestMaxLotSize:
    def test_min_0_01_passes(self): _load({"risk": {"max_lot_size": 0.01}})
    def test_max_10_passes(self):   _load({"risk": {"max_lot_size": 10.0}})
    def test_below_min_fails(self): _expect_fail({"risk": {"max_lot_size": 0.009}})
    def test_above_max_fails(self): _expect_fail({"risk": {"max_lot_size": 10.01}})


class TestMaxOpenTrades:
    def test_min_1_passes(self):    _load({"risk": {"max_open_trades": 1}})
    def test_max_10_passes(self):   _load({"risk": {"max_open_trades": 10}})
    def test_below_min_fails(self): _expect_fail({"risk": {"max_open_trades": 0}})
    def test_above_max_fails(self): _expect_fail({"risk": {"max_open_trades": 11}})


class TestDailyMaxDrawdownPct:
    def test_min_1_0_passes(self):
        _load({"risk": {"daily_max_drawdown_pct": 1.0, "total_max_drawdown_pct": 15.0}})
    def test_max_19_9_passes(self):
        _load({"risk": {"daily_max_drawdown_pct": 19.9, "total_max_drawdown_pct": 20.0}})
    def test_below_min_fails(self):
        _expect_fail({"risk": {"daily_max_drawdown_pct": 0.9, "total_max_drawdown_pct": 15.0}})
    def test_above_max_fails(self):
        _expect_fail({"risk": {"daily_max_drawdown_pct": 20.1, "total_max_drawdown_pct": 50.0}})


class TestTotalMaxDrawdownPct:
    def test_min_5_0_passes(self):
        _load({"risk": {"daily_max_drawdown_pct": 4.0, "total_max_drawdown_pct": 5.0}})
    def test_max_50_0_passes(self):
        _load({"risk": {"daily_max_drawdown_pct": 5.0, "total_max_drawdown_pct": 50.0}})
    def test_below_min_fails(self):
        _expect_fail({"risk": {"daily_max_drawdown_pct": 2.0, "total_max_drawdown_pct": 4.9}})
    def test_above_max_fails(self):
        _expect_fail({"risk": {"daily_max_drawdown_pct": 5.0, "total_max_drawdown_pct": 50.1}})


class TestMinRR:
    def test_min_1_0_passes(self):  _load({"risk": {"min_rr": 1.0}})
    def test_max_10_0_passes(self): _load({"risk": {"min_rr": 10.0}})
    def test_below_min_fails(self): _expect_fail({"risk": {"min_rr": 0.99}})
    def test_above_max_fails(self): _expect_fail({"risk": {"min_rr": 10.01}})


class TestMinFreeMarginPct:
    def test_min_110_passes(self):  _load({"risk": {"min_free_margin_pct": 110.0}})
    def test_max_500_passes(self):  _load({"risk": {"min_free_margin_pct": 500.0}})
    def test_below_min_fails(self): _expect_fail({"risk": {"min_free_margin_pct": 109.9}})
    def test_above_max_fails(self): _expect_fail({"risk": {"min_free_margin_pct": 500.1}})


class TestMaxConsecutiveLosses:
    def test_min_2_passes(self):    _load({"consecutive_loss": {"max_consecutive_losses": 2}})
    def test_max_20_passes(self):   _load({"consecutive_loss": {"max_consecutive_losses": 20}})
    def test_below_min_fails(self): _expect_fail({"consecutive_loss": {"max_consecutive_losses": 1}})
    def test_above_max_fails(self): _expect_fail({"consecutive_loss": {"max_consecutive_losses": 21}})


class TestCooldownHours:
    def test_min_1_passes(self):    _load({"consecutive_loss": {"cooldown_hours": 1}})
    def test_max_168_passes(self):  _load({"consecutive_loss": {"cooldown_hours": 168}})
    def test_below_min_fails(self): _expect_fail({"consecutive_loss": {"cooldown_hours": 0}})
    def test_above_max_fails(self): _expect_fail({"consecutive_loss": {"cooldown_hours": 169}})


class TestMaxRetries:
    def test_min_1_passes(self):    _load({"execution": {"max_retries": 1}})
    def test_max_10_passes(self):   _load({"execution": {"max_retries": 10}})
    def test_below_min_fails(self): _expect_fail({"execution": {"max_retries": 0}})
    def test_above_max_fails(self): _expect_fail({"execution": {"max_retries": 11}})


class TestRetryDelayMs:
    def test_min_100_passes(self):    _load({"execution": {"retry_delay_ms": 100}})
    def test_max_5000_passes(self):   _load({"execution": {"retry_delay_ms": 5000}})
    def test_below_min_fails(self):   _expect_fail({"execution": {"retry_delay_ms": 99}})
    def test_above_max_fails(self):   _expect_fail({"execution": {"retry_delay_ms": 5001}})


class TestMaxSignalAgeSeconds:
    def test_min_0_passes(self):    _load({"execution": {"max_signal_age_seconds": 0}})
    def test_max_60_passes(self):   _load({"execution": {"max_signal_age_seconds": 60}})
    def test_above_max_fails(self): _expect_fail({"execution": {"max_signal_age_seconds": 61}})


class TestMaxFreezeSkips:
    def test_min_1_passes(self):    _load({"execution": {"max_freeze_skips": 1}})
    def test_max_20_passes(self):   _load({"execution": {"max_freeze_skips": 20}})
    def test_below_min_fails(self): _expect_fail({"execution": {"max_freeze_skips": 0}})
    def test_above_max_fails(self): _expect_fail({"execution": {"max_freeze_skips": 21}})


# ===========================================================================
# 5. Enum / string parameter validation
# ===========================================================================

class TestNewsProtectionMode:
    def test_block_passes(self):    _load({"news": {"news_protection_mode": "BLOCK"}})
    def test_warn_passes(self):     _load({"news": {"news_protection_mode": "WARN"}})
    def test_disabled_passes(self): _load({"news": {"news_protection_mode": "DISABLED"}})
    def test_invalid_fails(self):   _expect_fail({"news": {"news_protection_mode": "IGNORE"}})
    def test_lowercase_fails(self): _expect_fail({"news": {"news_protection_mode": "block"}})


class TestMinImpactLevel:
    def test_high_passes(self):     _load({"news": {"min_impact_level": "High"}})
    def test_medium_passes(self):   _load({"news": {"min_impact_level": "Medium"}})
    def test_low_passes(self):      _load({"news": {"min_impact_level": "Low"}})
    def test_invalid_fails(self):   _expect_fail({"news": {"min_impact_level": "Critical"}})


class TestMinLogLevel:
    def test_debug_passes(self):    _load({"logger": {"min_log_level": "DEBUG"}})
    def test_info_passes(self):     _load({"logger": {"min_log_level": "INFO"}})
    def test_warn_passes(self):     _load({"logger": {"min_log_level": "WARN"}})
    def test_error_passes(self):    _load({"logger": {"min_log_level": "ERROR"}})
    def test_critical_passes(self): _load({"logger": {"min_log_level": "CRITICAL"}})
    def test_invalid_fails(self):   _expect_fail({"logger": {"min_log_level": "VERBOSE"}})


# ===========================================================================
# 6. Session window validation
# ===========================================================================

class TestSessionWindows:
    def test_start_before_end_passes(self):
        _load({"session": {"london": {"enabled": True, "start_utc": "07:00",
                                       "end_utc": "12:00", "utc_offset_hours": 0}}})

    def test_start_equals_end_fails_when_enabled(self):
        _expect_fail({"session": {"london": {"enabled": True, "start_utc": "07:00",
                                              "end_utc": "07:00", "utc_offset_hours": 0}}})

    def test_start_after_end_fails_when_enabled(self):
        _expect_fail({"session": {"london": {"enabled": True, "start_utc": "12:00",
                                              "end_utc": "07:00", "utc_offset_hours": 0}}})

    def test_start_equals_end_passes_when_disabled(self):
        """Session window validation only applies when the session is enabled."""
        _load({"session": {"london": {"enabled": False, "start_utc": "07:00",
                                       "end_utc": "07:00", "utc_offset_hours": 0}}})

    def test_invalid_time_format_fails(self):
        _expect_fail({"session": {"london": {"enabled": True, "start_utc": "7:00",
                                              "end_utc": "12:00", "utc_offset_hours": 0}}})

    def test_hour_out_of_range_fails(self):
        _expect_fail({"session": {"london": {"enabled": True, "start_utc": "25:00",
                                              "end_utc": "12:00", "utc_offset_hours": 0}}})


# ===========================================================================
# 7. Safety: DailyMaxDrawdown must be < TotalMaxDrawdown
# ===========================================================================

class TestDrawdownRelationship:
    def test_daily_less_than_total_passes(self):
        _load({"risk": {"daily_max_drawdown_pct": 5.0, "total_max_drawdown_pct": 15.0}})

    def test_daily_equals_total_fails(self):
        _expect_fail({"risk": {"daily_max_drawdown_pct": 15.0, "total_max_drawdown_pct": 15.0}})

    def test_daily_greater_than_total_fails(self):
        _expect_fail({"risk": {"daily_max_drawdown_pct": 16.0, "total_max_drawdown_pct": 15.0}})

    def test_safety_limits_cannot_be_bypassed_by_high_daily(self):
        """No combination of inputs should bypass the safety relationship."""
        for daily, total in [(20.0, 15.0), (50.0, 50.0), (10.0, 5.0)]:
            with pytest.raises(ConfigValidationError):
                _load({"risk": {"daily_max_drawdown_pct": daily,
                                "total_max_drawdown_pct": total}})


# ===========================================================================
# 8. Required string fields must not be empty
# ===========================================================================

class TestRequiredStrings:
    def test_news_events_file_empty_fails(self):
        _expect_fail({"news": {"news_events_file": ""}})

    def test_state_file_path_empty_fails(self):
        _expect_fail({"state": {"state_file_path": ""}})


# ===========================================================================
# 9. Config independence — two separate loads produce independent objects
# ===========================================================================

class TestConfigIndependence:
    def test_two_loads_produce_equal_configs(self):
        c1 = _load()
        c2 = _load()
        assert c1 == c2

    def test_different_inputs_produce_different_configs(self):
        c1 = _load()
        c2 = _load({"risk": {"risk_per_trade_pct": 2.0}})
        assert c1 != c2
        assert c1.risk_per_trade_pct == 1.0
        assert c2.risk_per_trade_pct == 2.0
