"""
test_symbol_props.py — XAU/USD MT5 EA Python Research Environment
==================================================================
Task 4.2: SymbolPropertiesLoader unit tests.

Tests cover (matching design test seam requirements):
  - Valid full property set → is_valid = True
  - Missing mandatory property → SymbolPropertiesError
  - stop_level_points = 0 is accepted (not an error)
  - freeze_level_points = 0 is accepted
  - margin_initial = 0 is accepted (dynamic margin)
  - contract_size <= 0 is rejected
  - tick_value <= 0 is rejected
  - point <= 0 is rejected
  - min_lot <= 0 is rejected
  - max_lot < min_lot is rejected
  - max_lot <= 0 is rejected
  - lot_step <= 0 is rejected
  - negative values rejected for all non-negative fields
  - No hardcoded XM/XAUUSD-specific values in loader
  - SymbolProperties.is_valid = False on default init
  - from_dict produces immutable SymbolProperties with is_valid = True
  - Regression: Tasks 1–3 tests still pass

Requirements: 14.4, 14.5, 16.1
"""

from __future__ import annotations

from pathlib import Path

import pytest

from data.loaders.symbol_props import SymbolPropertiesLoader, SymbolPropertiesError
from strategy.types import SymbolProperties

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DEFAULT_YAML = Path(__file__).parent.parent.parent / "config" / "default_config.yaml"


def _valid() -> dict:
    """Return a complete, valid symbol properties dict.
    Values are deliberately generic — not hardcoded XM/XAUUSD values.
    """
    return {
        "digits":              2,
        "point":               0.01,
        "tick_size":           0.01,
        "tick_value":          1.0,
        "contract_size":       100.0,
        "lot_step":            0.01,
        "min_lot":             0.01,
        "max_lot":             500.0,
        "stop_level_points":   0,
        "freeze_level_points": 0,
        "margin_initial":      0.0,
    }


def _load(override: dict | None = None) -> SymbolProperties:
    d = _valid()
    if override:
        d.update(override)
    return SymbolPropertiesLoader.from_dict(d)


def _expect_fail(override: dict) -> None:
    with pytest.raises(SymbolPropertiesError):
        _load(override)


# ===========================================================================
# 1. Default SymbolProperties struct state
# ===========================================================================

class TestDefaultSymbolPropertiesState:
    """SymbolProperties must default to is_valid=False."""

    def test_default_is_valid_is_false(self):
        sp = SymbolProperties()
        assert sp.is_valid is False

    def test_default_point_is_zero(self):
        assert SymbolProperties().point == 0.0

    def test_default_contract_size_is_zero(self):
        assert SymbolProperties().contract_size == 0.0

    def test_default_stop_level_is_zero(self):
        assert SymbolProperties().stop_level_points == 0

    def test_default_freeze_level_is_zero(self):
        assert SymbolProperties().freeze_level_points == 0


# ===========================================================================
# 2. Valid full property set
# ===========================================================================

class TestValidFullPropertySet:
    def test_is_valid_true_on_full_valid_set(self):
        sp = _load()
        assert sp.is_valid is True

    def test_all_fields_populated(self):
        sp = _load()
        assert sp.point             == 0.01
        assert sp.tick_size         == 0.01
        assert sp.tick_value        == 1.0
        assert sp.contract_size     == 100.0
        assert sp.lot_step          == 0.01
        assert sp.min_lot           == 0.01
        assert sp.max_lot           == 500.0
        assert sp.stop_level_points == 0
        assert sp.freeze_level_points == 0
        assert sp.margin_initial    == 0.0
        assert sp.digits            == 2

    def test_load_from_yaml_if_present(self):
        if DEFAULT_YAML.exists():
            sp = SymbolPropertiesLoader.load(DEFAULT_YAML)
            assert sp.is_valid is True


# ===========================================================================
# 3. Stop level = 0 is valid (Requirement 14.4 special case)
# ===========================================================================

class TestStopLevelZeroIsValid:
    def test_stop_level_zero_passes(self):
        sp = _load({"stop_level_points": 0})
        assert sp.is_valid is True
        assert sp.stop_level_points == 0

    def test_stop_level_positive_passes(self):
        sp = _load({"stop_level_points": 30})
        assert sp.stop_level_points == 30

    def test_stop_level_negative_fails(self):
        _expect_fail({"stop_level_points": -1})


# ===========================================================================
# 4. Freeze level = 0 is valid
# ===========================================================================

class TestFreezeLevelZeroIsValid:
    def test_freeze_level_zero_passes(self):
        sp = _load({"freeze_level_points": 0})
        assert sp.is_valid is True

    def test_freeze_level_positive_passes(self):
        sp = _load({"freeze_level_points": 20})
        assert sp.freeze_level_points == 20

    def test_freeze_level_negative_fails(self):
        _expect_fail({"freeze_level_points": -5})


# ===========================================================================
# 5. Margin initial = 0 is valid (dynamic margin)
# ===========================================================================

class TestMarginInitialZeroIsValid:
    def test_margin_zero_passes(self):
        sp = _load({"margin_initial": 0.0})
        assert sp.is_valid is True

    def test_margin_positive_passes(self):
        sp = _load({"margin_initial": 1000.0})
        assert sp.margin_initial == 1000.0

    def test_margin_negative_fails(self):
        _expect_fail({"margin_initial": -1.0})


# ===========================================================================
# 6. Point validation
# ===========================================================================

class TestPointValidation:
    def test_point_positive_passes(self):   _load({"point": 0.001})
    def test_point_zero_fails(self):        _expect_fail({"point": 0.0})
    def test_point_negative_fails(self):    _expect_fail({"point": -0.01})
    def test_point_none_fails(self):        _expect_fail({"point": None})


# ===========================================================================
# 7. Tick size validation
# ===========================================================================

class TestTickSizeValidation:
    def test_tick_size_positive_passes(self): _load({"tick_size": 0.001})
    def test_tick_size_zero_fails(self):      _expect_fail({"tick_size": 0.0})
    def test_tick_size_negative_fails(self):  _expect_fail({"tick_size": -0.01})


# ===========================================================================
# 8. Tick value validation (must be > 0, used in position sizing)
# ===========================================================================

class TestTickValueValidation:
    def test_tick_value_positive_passes(self): _load({"tick_value": 0.5})
    def test_tick_value_zero_fails(self):      _expect_fail({"tick_value": 0.0})
    def test_tick_value_negative_fails(self):  _expect_fail({"tick_value": -1.0})


# ===========================================================================
# 9. Contract size validation (must be > 0)
# ===========================================================================

class TestContractSizeValidation:
    def test_contract_size_positive_passes(self): _load({"contract_size": 1.0})
    def test_contract_size_zero_fails(self):       _expect_fail({"contract_size": 0.0})
    def test_contract_size_negative_fails(self):   _expect_fail({"contract_size": -100.0})


# ===========================================================================
# 10. Lot step validation
# ===========================================================================

class TestLotStepValidation:
    def test_lot_step_positive_passes(self): _load({"lot_step": 0.001})
    def test_lot_step_zero_fails(self):      _expect_fail({"lot_step": 0.0})
    def test_lot_step_negative_fails(self):  _expect_fail({"lot_step": -0.01})


# ===========================================================================
# 11. Min lot validation
# ===========================================================================

class TestMinLotValidation:
    def test_min_lot_positive_passes(self): _load({"min_lot": 0.001, "lot_step": 0.001})
    def test_min_lot_zero_fails(self):      _expect_fail({"min_lot": 0.0})
    def test_min_lot_negative_fails(self):  _expect_fail({"min_lot": -0.01})


# ===========================================================================
# 12. Max lot validation
# ===========================================================================

class TestMaxLotValidation:
    def test_max_lot_positive_and_gte_min_passes(self):
        _load({"min_lot": 0.01, "max_lot": 100.0})

    def test_max_lot_equals_min_lot_passes(self):
        _load({"min_lot": 0.01, "max_lot": 0.01})

    def test_max_lot_zero_fails(self):
        _expect_fail({"min_lot": 0.01, "max_lot": 0.0})

    def test_max_lot_negative_fails(self):
        _expect_fail({"min_lot": 0.01, "max_lot": -1.0})

    def test_max_lot_less_than_min_lot_fails(self):
        _expect_fail({"min_lot": 1.0, "max_lot": 0.5})


# ===========================================================================
# 13. Digits validation
# ===========================================================================

class TestDigitsValidation:
    def test_digits_zero_passes(self):     assert _load({"digits": 0}).digits == 0
    def test_digits_positive_passes(self): assert _load({"digits": 5}).digits == 5
    def test_digits_negative_fails(self):  _expect_fail({"digits": -1})


# ===========================================================================
# 14. Missing mandatory properties
# ===========================================================================

class TestMissingMandatoryProperties:
    """Every mandatory property must cause SymbolPropertiesError when absent."""

    def test_missing_point_fails(self):
        d = _valid(); del d["point"]
        with pytest.raises(SymbolPropertiesError):
            SymbolPropertiesLoader.from_dict(d)

    def test_missing_tick_size_fails(self):
        d = _valid(); del d["tick_size"]
        with pytest.raises(SymbolPropertiesError):
            SymbolPropertiesLoader.from_dict(d)

    def test_missing_tick_value_fails(self):
        d = _valid(); del d["tick_value"]
        with pytest.raises(SymbolPropertiesError):
            SymbolPropertiesLoader.from_dict(d)

    def test_missing_contract_size_fails(self):
        d = _valid(); del d["contract_size"]
        with pytest.raises(SymbolPropertiesError):
            SymbolPropertiesLoader.from_dict(d)

    def test_missing_lot_step_fails(self):
        d = _valid(); del d["lot_step"]
        with pytest.raises(SymbolPropertiesError):
            SymbolPropertiesLoader.from_dict(d)

    def test_missing_min_lot_fails(self):
        d = _valid(); del d["min_lot"]
        with pytest.raises(SymbolPropertiesError):
            SymbolPropertiesLoader.from_dict(d)

    def test_missing_max_lot_fails(self):
        d = _valid(); del d["max_lot"]
        with pytest.raises(SymbolPropertiesError):
            SymbolPropertiesLoader.from_dict(d)


# ===========================================================================
# 15. No hardcoded broker/symbol values
# ===========================================================================

class TestNoHardcodedValues:
    """
    Verify the loader contains no XM-specific or XAUUSD-specific magic numbers.
    We do this by passing deliberately different (but valid) values and confirming
    they are accepted without modification.
    """

    def test_accepts_non_xauusd_contract_size(self):
        sp = _load({"contract_size": 1.0})   # e.g. forex pair, not 100 oz XAU
        assert sp.contract_size == 1.0

    def test_accepts_5_digit_forex_point(self):
        sp = _load({"point": 0.00001, "tick_size": 0.00001, "digits": 5})
        assert sp.point == 0.00001

    def test_accepts_large_stop_level(self):
        sp = _load({"stop_level_points": 300})
        assert sp.stop_level_points == 300

    def test_accepts_very_small_lot_step(self):
        sp = _load({"lot_step": 0.001, "min_lot": 0.001, "max_lot": 100.0})
        assert sp.lot_step == 0.001

    def test_accepts_large_margin(self):
        sp = _load({"margin_initial": 50000.0})
        assert sp.margin_initial == 50000.0


# ===========================================================================
# 16. SymbolProperties is immutable (frozen dataclass)
# ===========================================================================

class TestSymbolPropertiesImmutability:
    def test_cannot_set_is_valid(self):
        sp = _load()
        with pytest.raises((AttributeError, TypeError)):
            sp.is_valid = False  # type: ignore[misc]

    def test_cannot_set_point(self):
        sp = _load()
        with pytest.raises((AttributeError, TypeError)):
            sp.point = 99.0     # type: ignore[misc]


# ===========================================================================
# 17. Error message content
# ===========================================================================

class TestErrorMessages:
    def test_error_includes_param_name(self):
        try:
            _load({"point": 0.0})
        except SymbolPropertiesError as e:
            assert "point" in str(e)

    def test_error_includes_constraint(self):
        try:
            _load({"contract_size": -1.0})
        except SymbolPropertiesError as e:
            assert ">" in str(e) or "positive" in str(e).lower()

    def test_error_includes_value(self):
        try:
            _load({"tick_value": 0.0})
        except SymbolPropertiesError as e:
            assert "0" in str(e)
