"""
config.py — XAU/USD MT5 EA Python Research Environment
=======================================================
Python mirror of ``include/utils/ConfigManager.mqh``.

Loads configuration from a YAML file (default: ``config/default_config.yaml``),
validates every parameter against the same rules as the MQL5 ConfigManager,
and returns an immutable ``Config`` dataclass.

Rules that match MQL5 ConfigManager exactly:
  - Same parameter names and groupings
  - Same valid ranges for every numeric parameter
  - Same enum valid values
  - Rejection (not clamping) on out-of-range values
  - Broker-specific symbol properties are NOT stored here —
    they come from SymbolProperties at runtime.
  - Session start time must be strictly < end time when session is enabled.
  - DailyMaxDrawdownPct must be < TotalMaxDrawdownPct.

Design reference: §2.15 Config_Manager
Requirements: 14.1, 14.2, 14.3, 16.1
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from strategy.logger import Logger, LogLevel

# ---------------------------------------------------------------------------
# Config dataclass — mirrors MQL5 Config struct
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Config:
    """
    Immutable validated configuration snapshot.
    All fields have the same defaults as the MQL5 ConfigManager input parameters.
    frozen=True enforces immutability after construction.
    """

    # --- EA Identity ---
    magic_number: int = 20260901

    # --- Market Structure Settings ---
    swing_side_candles:     int  = 2       # valid: 1–5
    regime_swing_count:     int  = 4       # valid: 2–10
    ranging_mode_enabled:   bool = False

    # --- Liquidity Settings ---
    pool_atr_tolerance: float = 0.5        # valid: 0.1–2.0
    max_active_pools:   int   = 20         # valid: 5–50

    # --- ATR / Volatility Settings ---
    atr_period:                    int   = 14    # valid: 5–50
    atr_min_multiplier:            float = 0.5   # valid: 0.1–1.0
    atr_max_multiplier:            float = 2.5   # valid: 1.5–5.0
    atr_sl_multiplier:             float = 1.5   # valid: 0.5–5.0
    atr_unavailable_timeout_min:   int   = 5     # valid: 1–60

    # --- Momentum Settings ---
    momentum_lookback: int = 10            # valid: 2–50

    # --- Session Filter Settings ---
    london_enabled:           bool  = True
    london_start_utc:         str   = "07:00"
    london_end_utc:           str   = "12:00"
    london_utc_offset_hours:  int   = 0    # valid: -12–+14

    new_york_enabled:         bool  = True
    new_york_start_utc:       str   = "13:00"
    new_york_end_utc:         str   = "17:00"
    new_york_utc_offset_hours:int   = 0

    ln_overlap_enabled:           bool  = True
    ln_overlap_start_utc:         str   = "13:00"
    ln_overlap_end_utc:           str   = "15:00"
    ln_overlap_utc_offset_hours:  int   = 0

    # --- Spread Filter Settings ---
    max_spread_points: int = 30            # valid: 10–200

    # --- News Filter Settings ---
    news_protection_mode:   str  = "BLOCK"    # BLOCK | WARN | DISABLED
    min_impact_level:       str  = "High"     # Low | Medium | High
    pre_event_minutes:      int  = 30         # valid: 0–120
    post_event_minutes:     int  = 15         # valid: 0–120
    max_news_list_age_hours:int  = 24         # valid: 1–168
    stale_fallback_block:   bool = True
    news_events_file:       str  = "config/news_events.csv"

    # --- Risk Settings ---
    risk_per_trade_pct:     float = 1.0    # valid: 0.1–5.0
    max_lot_size:           float = 0.5    # valid: 0.01–10.0
    max_open_trades:        int   = 2      # valid: 1–10
    daily_max_drawdown_pct: float = 5.0    # valid: 1.0–20.0
    total_max_drawdown_pct: float = 15.0   # valid: 5.0–50.0
    min_rr:                 float = 1.5    # valid: 1.0–10.0
    min_free_margin_pct:    float = 150.0  # valid: 110.0–500.0

    # --- Consecutive Loss / Cooldown ---
    max_consecutive_losses: int = 5        # valid: 2–20
    cooldown_hours:         int = 24       # valid: 1–168

    # --- Execution Settings ---
    max_retries:           int = 3         # valid: 1–10
    retry_delay_ms:        int = 500       # valid: 100–5000
    max_signal_age_seconds:int = 0         # valid: 0–60
    max_freeze_skips:      int = 5         # valid: 1–20

    # --- Logging Settings ---
    min_log_level: str = "INFO"            # DEBUG|INFO|WARN|ERROR|CRITICAL

    # --- State Manager Settings ---
    state_file_path: str = "xauusd_ea_state.txt"


# ---------------------------------------------------------------------------
# ConfigValidationError
# ---------------------------------------------------------------------------

class ConfigValidationError(ValueError):
    """Raised when a parameter value is outside its documented valid range."""

    def __init__(self, param: str, value: object, constraint: str) -> None:
        self.param      = param
        self.value      = value
        self.constraint = constraint
        super().__init__(
            f"PARAM_INVALID param={param} value={value} constraint=[{constraint}]"
        )


# ---------------------------------------------------------------------------
# ConfigLoader — mirrors ConfigManager::Validate()
# ---------------------------------------------------------------------------

class ConfigLoader:
    """
    Load and validate configuration from a YAML file.
    Mirrors MQL5 ConfigManager::Validate() — same rules, same rejections.
    """

    @staticmethod
    def load(yaml_path: str | Path = "config/default_config.yaml") -> Config:
        """
        Load YAML, validate all parameters, return an immutable Config.
        Raises ConfigValidationError on first invalid parameter.
        Does NOT clamp invalid values — rejects them outright.
        """
        path = Path(yaml_path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        with path.open(encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)

        return ConfigLoader._validate(raw)

    @staticmethod
    def from_dict(raw: dict) -> Config:
        """Build and validate a Config from a plain dict (useful for tests)."""
        return ConfigLoader._validate(raw)

    # ------------------------------------------------------------------
    # Internal validation — same order as MQL5 ConfigManager::Validate()
    # ------------------------------------------------------------------

    @staticmethod
    def _validate(raw: dict) -> Config:  # noqa: C901
        def get(section: str, key: str, default: object) -> object:
            sec = raw.get(section, {})
            if not isinstance(sec, dict):
                return default
            return sec.get(key, default)

        def _chk_int(name: str, val: object, lo: int, hi: int) -> int:
            v = int(val) if isinstance(val, (int, float)) else None
            if v is None or not (lo <= v <= hi):
                raise ConfigValidationError(name, val, f"{lo}–{hi}")
            return v

        def _chk_float(name: str, val: object, lo: float, hi: float) -> float:
            try:
                v = float(val)
            except (TypeError, ValueError):
                v = None  # type: ignore[assignment]
            if v is None or not (lo <= v <= hi):
                raise ConfigValidationError(name, val, f"{lo}–{hi}")
            return v

        def _chk_enum(name: str, val: object, choices: list) -> object:
            if val not in choices:
                raise ConfigValidationError(name, val, f"one of {choices}")
            return val

        def _chk_time(name: str, val: str) -> str:
            """Validate HH:MM format — exactly two-digit hour and minute."""
            try:
                s = str(val)
                parts = s.split(":")
                if len(parts) != 2 or len(parts[0]) != 2 or len(parts[1]) != 2:
                    raise ValueError
                h, m = int(parts[0]), int(parts[1])
                if not (0 <= h <= 23 and 0 <= m <= 59):
                    raise ValueError
            except (ValueError, AttributeError):
                raise ConfigValidationError(name, val, "HH:MM (00:00–23:59)")
            return val

        def _time_to_minutes(t: str) -> int:
            h, m = int(t.split(":")[0]), int(t.split(":")[1])
            return h * 60 + m

        # ---- EA Identity ----
        magic = _chk_int("magic_number", get("ea", "magic_number", 20260901), 1, 2_147_483_647)

        # ---- Market Structure ----
        ssc = _chk_int("swing_side_candles", get("market_structure", "swing_side_candles", 2), 1, 5)
        rsc = _chk_int("regime_swing_count", get("market_structure", "regime_swing_count", 4), 2, 10)
        rme = bool(get("market_structure", "ranging_mode_enabled", False))

        # ---- Liquidity ----
        pat  = _chk_float("pool_atr_tolerance", get("liquidity", "pool_atr_tolerance", 0.5), 0.1, 2.0)
        map_ = _chk_int("max_active_pools",     get("liquidity", "max_active_pools",   20),  5,  50)

        # ---- ATR / Volatility ----
        atr_period = _chk_int("atr_period",
                        get("atr", "atr_period", 14), 5, 50)
        atr_min_m  = _chk_float("atr_min_multiplier",
                        get("atr", "atr_min_multiplier", 0.5), 0.1, 1.0)
        atr_max_m  = _chk_float("atr_max_multiplier",
                        get("atr", "atr_max_multiplier", 2.5), 1.5, 5.0)
        atr_sl_m   = _chk_float("atr_sl_multiplier",
                        get("atr", "atr_sl_multiplier", 1.5),  0.5, 5.0)
        atr_timeout= _chk_int("atr_unavailable_timeout_min",
                        get("atr", "unavailable_timeout_minutes", 5), 1, 60)

        # ---- Momentum ----
        mom_lb = _chk_int("momentum_lookback", get("momentum", "lookback", 10), 2, 50)

        # ---- Session Filter ----
        lon_en     = bool(get("session", "london", {}).get("enabled", True))
        lon_start  = _chk_time("london_start_utc",
                        get("session", "london", {}).get("start_utc", "07:00"))
        lon_end    = _chk_time("london_end_utc",
                        get("session", "london", {}).get("end_utc",   "12:00"))
        lon_offset = _chk_int("london_utc_offset_hours",
                        get("session", "london", {}).get("utc_offset_hours", 0), -12, 14)
        if lon_en and _time_to_minutes(lon_start) >= _time_to_minutes(lon_end):
            raise ConfigValidationError("london_session",
                f"{lon_start}–{lon_end}", "start time must be < end time")

        ny_en     = bool(get("session", "new_york", {}).get("enabled", True))
        ny_start  = _chk_time("new_york_start_utc",
                        get("session", "new_york", {}).get("start_utc", "13:00"))
        ny_end    = _chk_time("new_york_end_utc",
                        get("session", "new_york", {}).get("end_utc",   "17:00"))
        ny_offset = _chk_int("new_york_utc_offset_hours",
                        get("session", "new_york", {}).get("utc_offset_hours", 0), -12, 14)
        if ny_en and _time_to_minutes(ny_start) >= _time_to_minutes(ny_end):
            raise ConfigValidationError("new_york_session",
                f"{ny_start}–{ny_end}", "start time must be < end time")

        ln_ov_en     = bool(get("session", "london_ny_overlap", {}).get("enabled", True))
        ln_ov_start  = _chk_time("ln_overlap_start_utc",
                            get("session", "london_ny_overlap", {}).get("start_utc", "13:00"))
        ln_ov_end    = _chk_time("ln_overlap_end_utc",
                            get("session", "london_ny_overlap", {}).get("end_utc",   "15:00"))
        ln_ov_offset = _chk_int("ln_overlap_utc_offset_hours",
                            get("session", "london_ny_overlap", {}).get("utc_offset_hours", 0), -12, 14)
        if ln_ov_en and _time_to_minutes(ln_ov_start) >= _time_to_minutes(ln_ov_end):
            raise ConfigValidationError("ln_overlap_session",
                f"{ln_ov_start}–{ln_ov_end}", "start time must be < end time")

        # ---- Spread ----
        max_sp = _chk_int("max_spread_points", get("spread", "max_spread_points", 30), 10, 200)

        # ---- News ----
        npm  = _chk_enum("news_protection_mode",
                    get("news", "news_protection_mode", "BLOCK"),
                    ["BLOCK", "WARN", "DISABLED"])
        nil_ = _chk_enum("min_impact_level",
                    get("news", "min_impact_level", "High"),
                    ["Low", "Medium", "High"])
        pre  = _chk_int("pre_event_minutes",     get("news", "pre_event_minutes",  30), 0, 120)
        post = _chk_int("post_event_minutes",    get("news", "post_event_minutes", 15), 0, 120)
        nage = _chk_int("max_news_list_age_hours",get("news","max_list_age_hours", 24), 1, 168)
        sfb  = bool(get("news", "stale_fallback", "BLOCK") == "BLOCK"
                    if isinstance(get("news", "stale_fallback", "BLOCK"), str)
                    else get("news", "stale_fallback", True))
        nef  = str(get("news", "news_events_file", "config/news_events.csv"))
        if not nef:
            raise ConfigValidationError("news_events_file", nef, "must not be empty")

        # ---- Risk ----
        rpt = _chk_float("risk_per_trade_pct",   get("risk", "risk_per_trade_pct",   1.0),  0.1,  5.0)
        mls = _chk_float("max_lot_size",          get("risk", "max_lot_size",         0.5),  0.01, 10.0)
        mot = _chk_int  ("max_open_trades",       get("risk", "max_open_trades",      2),    1,    10)
        ddd = _chk_float("daily_max_drawdown_pct",get("risk", "daily_max_drawdown_pct",5.0), 1.0,  20.0)
        tdd = _chk_float("total_max_drawdown_pct",get("risk", "total_max_drawdown_pct",15.0),5.0,  50.0)
        mrr = _chk_float("min_rr",                get("risk", "min_rr",               1.5),  1.0,  10.0)
        mfm = _chk_float("min_free_margin_pct",   get("risk", "min_free_margin_pct",  150.0),110.0,500.0)

        # Safety: DailyMaxDrawdownPct must be < TotalMaxDrawdownPct
        if ddd >= tdd:
            raise ConfigValidationError(
                "daily_max_drawdown_pct/total_max_drawdown_pct",
                f"daily={ddd} total={tdd}",
                "daily_max_drawdown_pct must be < total_max_drawdown_pct")

        # ---- Cooldown ----
        mcl = _chk_int("max_consecutive_losses", get("consecutive_loss","max_consecutive_losses",5), 2, 20)
        ch  = _chk_int("cooldown_hours",          get("consecutive_loss","cooldown_hours",24),        1, 168)

        # ---- Execution ----
        mr_  = _chk_int("max_retries",           get("execution","max_retries",           3),   1,    10)
        rdm  = _chk_int("retry_delay_ms",        get("execution","retry_delay_ms",        500), 100,  5000)
        msas = _chk_int("max_signal_age_seconds",get("execution","max_signal_age_seconds",0),   0,    60)
        mfs  = _chk_int("max_freeze_skips",      get("execution","max_freeze_skips",      5),   1,    20)

        # ---- Logger ----
        mll = _chk_enum("min_log_level",
                    get("logger","min_log_level","INFO"),
                    ["DEBUG","INFO","WARN","ERROR","CRITICAL"])

        # ---- State Manager ----
        sfp = str(get("state","state_file_path","xauusd_ea_state.txt"))
        if not sfp:
            raise ConfigValidationError("state_file_path", sfp, "must not be empty")

        # ---- Build immutable Config ----
        return Config(
            magic_number              = magic,
            swing_side_candles        = ssc,
            regime_swing_count        = rsc,
            ranging_mode_enabled      = rme,
            pool_atr_tolerance        = pat,
            max_active_pools          = map_,
            atr_period                = atr_period,
            atr_min_multiplier        = atr_min_m,
            atr_max_multiplier        = atr_max_m,
            atr_sl_multiplier         = atr_sl_m,
            atr_unavailable_timeout_min = atr_timeout,
            momentum_lookback         = mom_lb,
            london_enabled            = lon_en,
            london_start_utc          = lon_start,
            london_end_utc            = lon_end,
            london_utc_offset_hours   = lon_offset,
            new_york_enabled          = ny_en,
            new_york_start_utc        = ny_start,
            new_york_end_utc          = ny_end,
            new_york_utc_offset_hours = ny_offset,
            ln_overlap_enabled            = ln_ov_en,
            ln_overlap_start_utc          = ln_ov_start,
            ln_overlap_end_utc            = ln_ov_end,
            ln_overlap_utc_offset_hours   = ln_ov_offset,
            max_spread_points         = max_sp,
            news_protection_mode      = npm,
            min_impact_level          = nil_,
            pre_event_minutes         = pre,
            post_event_minutes        = post,
            max_news_list_age_hours   = nage,
            stale_fallback_block      = sfb,
            news_events_file          = nef,
            risk_per_trade_pct        = rpt,
            max_lot_size              = mls,
            max_open_trades           = mot,
            daily_max_drawdown_pct    = ddd,
            total_max_drawdown_pct    = tdd,
            min_rr                    = mrr,
            min_free_margin_pct       = mfm,
            max_consecutive_losses    = mcl,
            cooldown_hours            = ch,
            max_retries               = mr_,
            retry_delay_ms            = rdm,
            max_signal_age_seconds    = msas,
            max_freeze_skips          = mfs,
            min_log_level             = mll,
            state_file_path           = sfp,
        )
