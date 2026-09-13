"""
symbol_props.py — XAU/USD MT5 EA Python Research Environment
=============================================================
Python mirror of ``include/data/SymbolPropertiesReader.mqh``.

In backtesting there is no live MT5 runtime available. This module
loads SymbolProperties from the YAML configuration file instead of
calling MT5 SymbolInfo functions. All the same validation rules apply.

Rules that match MQL5 SymbolPropertiesReader exactly:
  - Same 11 properties (same field names as SymbolProperties dataclass)
  - Mandatory properties: point, tick_size, tick_value, contract_size,
    lot_step, min_lot, max_lot, stop_level_points, margin_initial
  - stop_level_points = 0 is valid (some brokers allow any stop distance)
  - freeze_level_points = 0 is valid
  - contract_size and tick_value must be > 0
  - min_lot must be > 0
  - max_lot must be > 0 and >= min_lot
  - lot_step must be > 0
  - point must be > 0
  - margin_initial >= 0 (0 = dynamic, valid)
  - NO XM-specific or XAUUSD-specific values are hardcoded
  - is_valid = True only after all validations pass

Design reference: §2.1 Symbol_Properties_Reader
Requirements: 14.4, 14.5, 16.1
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional

import yaml

from strategy.types import SymbolProperties


# ---------------------------------------------------------------------------
# SymbolPropertiesError
# ---------------------------------------------------------------------------

class SymbolPropertiesError(ValueError):
    """Raised when a required symbol property is missing or invalid."""

    def __init__(self, param: str, value: object, constraint: str) -> None:
        self.param      = param
        self.value      = value
        self.constraint = constraint
        super().__init__(
            f"SYMBOL_PROP_INVALID param={param} value={value} constraint=[{constraint}]"
        )


# ---------------------------------------------------------------------------
# SymbolPropertiesLoader
# ---------------------------------------------------------------------------

class SymbolPropertiesLoader:
    """
    Load and validate symbol properties from a YAML config file.
    Mirrors MQL5 SymbolPropertiesReader::Read() — same validation rules,
    same rejection semantics.

    Returns an immutable SymbolProperties instance with is_valid=True,
    or raises SymbolPropertiesError on the first invalid property.
    """

    @staticmethod
    def load(yaml_path: str | Path = "config/default_config.yaml") -> SymbolProperties:
        """Load from YAML, validate, return populated SymbolProperties."""
        path = Path(yaml_path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")
        with path.open(encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
        sec = raw.get("symbol_properties", {})
        return SymbolPropertiesLoader.from_dict(sec)

    @staticmethod
    def from_dict(props: dict) -> SymbolProperties:
        """
        Build and validate a SymbolProperties from a plain dict.
        Raises SymbolPropertiesError on the first invalid property.
        """
        def _get(key: str, default: object = None) -> object:
            return props.get(key, default)

        def _chk_positive(name: str, val: object) -> float:
            try:
                v = float(val)
            except (TypeError, ValueError):
                raise SymbolPropertiesError(name, val, "must be a positive number")
            if v <= 0.0:
                raise SymbolPropertiesError(name, val, "must be > 0")
            return v

        def _chk_nonneg(name: str, val: object) -> float:
            try:
                v = float(val)
            except (TypeError, ValueError):
                raise SymbolPropertiesError(name, val, "must be a non-negative number")
            if v < 0.0:
                raise SymbolPropertiesError(name, val, "must be >= 0")
            return v

        def _chk_nonneg_int(name: str, val: object) -> int:
            try:
                v = int(val)
            except (TypeError, ValueError):
                raise SymbolPropertiesError(name, val, "must be a non-negative integer")
            if v < 0:
                raise SymbolPropertiesError(name, val, "must be >= 0")
            return v

        # ---- 1. Digits (non-negative int, default 0) ----
        digits = _chk_nonneg_int("digits", _get("digits", 0))

        # ---- 2. Point (mandatory, > 0) ----
        point = _chk_positive("point", _get("point"))

        # ---- 3. Tick size (mandatory, > 0) ----
        tick_size = _chk_positive("tick_size", _get("tick_size"))

        # ---- 4. Tick value (mandatory, > 0) ----
        tick_value = _chk_positive("tick_value", _get("tick_value"))

        # ---- 5. Contract size (mandatory, > 0) ----
        contract_size = _chk_positive("contract_size", _get("contract_size"))

        # ---- 6. Lot step (mandatory, > 0) ----
        lot_step = _chk_positive("lot_step", _get("lot_step"))

        # ---- 7. Min lot (mandatory, > 0) ----
        min_lot = _chk_positive("min_lot", _get("min_lot"))

        # ---- 8. Max lot (mandatory, > 0, >= min_lot) ----
        max_lot_raw = _get("max_lot")
        try:
            max_lot = float(max_lot_raw)
        except (TypeError, ValueError):
            raise SymbolPropertiesError("max_lot", max_lot_raw, "must be a positive number")
        if max_lot <= 0.0:
            raise SymbolPropertiesError("max_lot", max_lot, "must be > 0")
        if max_lot < min_lot:
            raise SymbolPropertiesError(
                "max_lot", max_lot,
                f"must be >= min_lot ({min_lot})")

        # ---- 9. Stop level (non-negative int; 0 is valid) ----
        stop_level_points = _chk_nonneg_int(
            "stop_level_points", _get("stop_level_points", 0))

        # ---- 10. Freeze level (non-negative int; 0 is valid) ----
        freeze_level_points = _chk_nonneg_int(
            "freeze_level_points", _get("freeze_level_points", 0))

        # ---- 11. Margin initial (>= 0; 0 = dynamic, valid) ----
        margin_initial = _chk_nonneg(
            "margin_initial", _get("margin_initial", 0.0))

        return SymbolProperties(
            point               = point,
            lot_step            = lot_step,
            min_lot             = min_lot,
            max_lot             = max_lot,
            contract_size       = contract_size,
            stop_level_points   = stop_level_points,
            freeze_level_points = freeze_level_points,
            tick_size           = tick_size,
            tick_value          = tick_value,
            digits              = digits,
            margin_initial      = margin_initial,
            is_valid            = True,
        )
