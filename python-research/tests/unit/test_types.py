"""
test_types.py — XAU/USD MT5 EA Python Research Environment
===========================================================
Task 1.3 unit tests: verify that every dataclass and enum in
``strategy/types.py`` correctly mirrors its MQL5 counterpart in
``include/core/Types.mqh``.

Tests cover:
  - All enum integer values match MQL5 enum values exactly
  - All dataclasses default-initialise to zero / empty / False
  - All required fields are present on every dataclass
  - LiquidityPool default sweep_event is None (Python equivalent of zero-init)
  - SymbolProperties.is_valid defaults to False (not yet populated)
  - EAState safety booleans default to False
  - types module is importable with no side-effects

Requirements: 13.1, 16.1
"""

import importlib
import sys
from datetime import datetime, timezone

import pytest

# ---------------------------------------------------------------------------
# Import the module under test
# ---------------------------------------------------------------------------
from strategy.types import (
    AnalysisStatus,
    ATRFilterStatus,
    ATRResult,
    Direction,
    EAOperationalState,
    EAState,
    ExecutionResult,
    ExecutionStatus,
    LiquidityPool,
    MomentumResult,
    MomentumStatus,
    OHLCVBar,
    OrderType,
    PoolSide,
    PoolStatus,
    RejectionResult,
    SignalType,
    SwingPoint,
    SwingType,
    SymbolProperties,
    TradeOrder,
    TradeSignal,
)

# UTC epoch constant used throughout (matches MQL5 zero-initialised datetime)
_UTC_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


# ===========================================================================
# 1. Module import health
# ===========================================================================

class TestModuleImport:
    """The types module must be importable with no side-effects."""

    def test_module_importable(self):
        """Importing types.py must not raise any exception."""
        mod = importlib.import_module("strategy.types")
        assert mod is not None

    def test_no_unexpected_names_exported(self):
        """All 12 required dataclasses and 10 enums must be importable from strategy.types."""
        import strategy.types as t
        required_classes = [
            # Enums
            "Direction", "SignalType", "PoolStatus", "ATRFilterStatus",
            "MomentumStatus", "ExecutionStatus", "OrderType", "SwingType",
            "PoolSide", "EAOperationalState",
            # Dataclasses
            "AnalysisStatus", "TradeSignal", "TradeOrder", "ExecutionResult",
            "RejectionResult", "SymbolProperties", "OHLCVBar", "SwingPoint",
            "LiquidityPool", "ATRResult", "MomentumResult", "EAState",
        ]
        for name in required_classes:
            assert hasattr(t, name), f"Required type not exported: {name}"
            import inspect
            assert inspect.isclass(getattr(t, name)), \
                f"{name} is exported but is not a class"


# ===========================================================================
# 2. Enum integer values (must match MQL5 enum values exactly)
# ===========================================================================

class TestDirectionEnum:
    def test_none_is_0(self):   assert Direction.NONE  == 0
    def test_long_is_1(self):   assert Direction.LONG  == 1
    def test_short_is_2(self):  assert Direction.SHORT == 2
    def test_all_distinct(self):
        vals = list(Direction)
        assert len(vals) == len(set(vals))


class TestSignalTypeEnum:
    def test_sweep_long_is_0(self):     assert SignalType.SWEEP_LONG      == 0
    def test_sweep_short_is_1(self):    assert SignalType.SWEEP_SHORT     == 1
    def test_bos_long_is_2(self):       assert SignalType.BOS_LONG        == 2
    def test_bos_short_is_3(self):      assert SignalType.BOS_SHORT       == 3
    def test_choch_long_is_4(self):     assert SignalType.CHOCH_LONG      == 4
    def test_choch_short_is_5(self):    assert SignalType.CHOCH_SHORT     == 5
    def test_regime_bullish_is_6(self): assert SignalType.REGIME_BULLISH  == 6
    def test_regime_bearish_is_7(self): assert SignalType.REGIME_BEARISH  == 7
    def test_regime_ranging_is_8(self): assert SignalType.REGIME_RANGING  == 8
    def test_filter_allowed_is_9(self): assert SignalType.FILTER_ALLOWED  == 9
    def test_filter_blocked_is_10(self):assert SignalType.FILTER_BLOCKED  == 10
    def test_filter_warn_is_11(self):   assert SignalType.FILTER_WARN     == 11
    def test_unknown_is_12(self):       assert SignalType.UNKNOWN         == 12
    def test_exactly_13_values(self):   assert len(list(SignalType)) == 13
    def test_all_distinct(self):
        vals = list(SignalType)
        assert len(vals) == len(set(vals))


class TestPoolStatusEnum:
    def test_active_is_0(self):      assert PoolStatus.ACTIVE      == 0
    def test_swept_is_1(self):       assert PoolStatus.SWEPT       == 1
    def test_invalidated_is_2(self): assert PoolStatus.INVALIDATED == 2
    def test_exactly_3_values(self): assert len(list(PoolStatus)) == 3


class TestATRFilterStatusEnum:
    def test_allow_is_0(self):       assert ATRFilterStatus.ALLOW       == 0
    def test_block_low_is_1(self):   assert ATRFilterStatus.BLOCK_LOW   == 1
    def test_block_high_is_2(self):  assert ATRFilterStatus.BLOCK_HIGH  == 2
    def test_unavailable_is_3(self): assert ATRFilterStatus.UNAVAILABLE == 3
    def test_exactly_4_values(self): assert len(list(ATRFilterStatus)) == 4


class TestMomentumStatusEnum:
    def test_confirmed_is_0(self):          assert MomentumStatus.CONFIRMED         == 0
    def test_rejected_is_1(self):           assert MomentumStatus.REJECTED          == 1
    def test_insufficient_data_is_2(self):  assert MomentumStatus.INSUFFICIENT_DATA == 2
    def test_exactly_3_values(self):        assert len(list(MomentumStatus)) == 3


class TestExecutionStatusEnum:
    def test_filled_is_0(self):   assert ExecutionStatus.FILLED   == 0
    def test_rejected_is_1(self): assert ExecutionStatus.REJECTED == 1
    def test_failed_is_2(self):   assert ExecutionStatus.FAILED   == 2
    def test_exactly_3_values(self): assert len(list(ExecutionStatus)) == 3


class TestOrderTypeEnum:
    def test_market_buy_is_0(self):  assert OrderType.MARKET_BUY  == 0
    def test_market_sell_is_1(self): assert OrderType.MARKET_SELL == 1
    def test_exactly_2_values(self): assert len(list(OrderType)) == 2
    def test_buy_ne_sell(self):      assert OrderType.MARKET_BUY != OrderType.MARKET_SELL


class TestSwingTypeEnum:
    def test_high_is_0(self):        assert SwingType.HIGH == 0
    def test_low_is_1(self):         assert SwingType.LOW  == 1
    def test_exactly_2_values(self): assert len(list(SwingType)) == 2


class TestPoolSideEnum:
    def test_above_is_0(self):       assert PoolSide.ABOVE == 0
    def test_below_is_1(self):       assert PoolSide.BELOW == 1
    def test_exactly_2_values(self): assert len(list(PoolSide)) == 2


class TestEAOperationalStateEnum:
    def test_initialising_is_0(self):    assert EAOperationalState.INITIALISING    == 0
    def test_running_is_1(self):         assert EAOperationalState.RUNNING         == 1
    def test_safe_monitoring_is_2(self): assert EAOperationalState.SAFE_MONITORING == 2
    def test_daily_circuit_is_3(self):   assert EAOperationalState.DAILY_CIRCUIT   == 3
    def test_cooldown_is_4(self):        assert EAOperationalState.COOLDOWN        == 4
    def test_hard_disabled_is_5(self):   assert EAOperationalState.HARD_DISABLED   == 5
    def test_exactly_6_values(self):     assert len(list(EAOperationalState)) == 6
    def test_all_distinct(self):
        vals = list(EAOperationalState)
        assert len(vals) == len(set(vals))


# ===========================================================================
# 3. Dataclass default initialisation
# ===========================================================================

class TestAnalysisStatusDefaults:
    def setup_method(self):
        self.s = AnalysisStatus()

    def test_signal_type_default(self):   assert self.s.signal_type      == SignalType.UNKNOWN
    def test_direction_default(self):     assert self.s.direction        == Direction.NONE
    def test_confidence_default(self):    assert self.s.confidence       == 0
    def test_timestamp_default(self):     assert self.s.timestamp        == _UTC_EPOCH
    def test_source_module_default(self): assert self.s.source_module    == ""
    def test_rejection_reason_default(self): assert self.s.rejection_reason == ""
    def test_has_6_fields(self):
        import dataclasses
        assert len(dataclasses.fields(AnalysisStatus)) == 6


class TestTradeSignalDefaults:
    def setup_method(self):
        self.ts = TradeSignal()

    def test_entry_price_default(self):            assert self.ts.entry_price            == 0.0
    def test_signal_reference_price_default(self): assert self.ts.signal_reference_price == 0.0
    def test_stop_loss_price_default(self):        assert self.ts.stop_loss_price        == 0.0
    def test_take_profit_price_default(self):      assert self.ts.take_profit_price      == 0.0
    def test_direction_default(self):              assert self.ts.direction              == Direction.NONE
    def test_signal_timestamp_default(self):       assert self.ts.signal_timestamp       == _UTC_EPOCH
    def test_atr_at_signal_default(self):          assert self.ts.atr_at_signal          == 0.0
    def test_regime_default(self):                 assert self.ts.regime                 == 0
    def test_computed_rr_default(self):            assert self.ts.computed_rr            == 0.0
    def test_tp_pool_level_default(self):          assert self.ts.tp_pool_level          == ""
    def test_rejection_reason_default(self):       assert self.ts.rejection_reason       == ""
    def test_has_11_fields(self):
        import dataclasses
        assert len(dataclasses.fields(TradeSignal)) == 11


class TestTradeOrderDefaults:
    def setup_method(self):
        self.to = TradeOrder()

    def test_symbol_default(self):                 assert self.to.symbol                 == ""
    def test_order_type_default(self):             assert self.to.order_type             == OrderType.MARKET_BUY
    def test_volume_default(self):                 assert self.to.volume                 == 0.0
    def test_entry_price_default(self):            assert self.to.entry_price            == 0.0
    def test_signal_reference_price_default(self): assert self.to.signal_reference_price == 0.0
    def test_stop_loss_price_default(self):        assert self.to.stop_loss_price        == 0.0
    def test_take_profit_price_default(self):      assert self.to.take_profit_price      == 0.0
    def test_timestamp_default(self):              assert self.to.timestamp              == _UTC_EPOCH
    def test_magic_number_default(self):           assert self.to.magic_number           == 0
    def test_max_slippage_points_default(self):    assert self.to.max_slippage_points    == 0.0
    def test_has_10_fields(self):
        import dataclasses
        assert len(dataclasses.fields(TradeOrder)) == 10


class TestExecutionResultDefaults:
    def setup_method(self):
        self.er = ExecutionResult()

    def test_status_default(self):               assert self.er.status               == ExecutionStatus.FAILED
    def test_ticket_default(self):               assert self.er.ticket               == 0
    def test_filled_price_default(self):         assert self.er.filled_price         == 0.0
    def test_filled_sl_default(self):            assert self.er.filled_sl            == 0.0
    def test_filled_tp_default(self):            assert self.er.filled_tp            == 0.0
    def test_mt5_error_code_default(self):       assert self.er.mt5_error_code       == 0
    def test_error_description_default(self):    assert self.er.error_description    == ""
    def test_execution_timestamp_default(self):  assert self.er.execution_timestamp  == _UTC_EPOCH
    def test_has_8_fields(self):
        import dataclasses
        assert len(dataclasses.fields(ExecutionResult)) == 8


class TestRejectionResultDefaults:
    def setup_method(self):
        self.rr = RejectionResult()

    def test_unmet_criterion_default(self): assert self.rr.unmet_criterion == ""
    def test_computed_value_default(self):  assert self.rr.computed_value  == 0.0
    def test_required_value_default(self):  assert self.rr.required_value  == 0.0
    def test_timestamp_default(self):       assert self.rr.timestamp       == _UTC_EPOCH
    def test_has_4_fields(self):
        import dataclasses
        assert len(dataclasses.fields(RejectionResult)) == 4


class TestSymbolPropertiesDefaults:
    def setup_method(self):
        self.sp = SymbolProperties()

    def test_point_default(self):               assert self.sp.point               == 0.0
    def test_lot_step_default(self):            assert self.sp.lot_step            == 0.0
    def test_min_lot_default(self):             assert self.sp.min_lot             == 0.0
    def test_max_lot_default(self):             assert self.sp.max_lot             == 0.0
    def test_contract_size_default(self):       assert self.sp.contract_size       == 0.0
    def test_stop_level_points_default(self):   assert self.sp.stop_level_points   == 0
    def test_freeze_level_points_default(self): assert self.sp.freeze_level_points == 0
    def test_tick_size_default(self):           assert self.sp.tick_size           == 0.0
    def test_tick_value_default(self):          assert self.sp.tick_value          == 0.0
    def test_digits_default(self):              assert self.sp.digits              == 0
    def test_margin_initial_default(self):      assert self.sp.margin_initial      == 0.0
    # Critical: is_valid must be False on default-init — no properties read yet
    def test_is_valid_is_false_on_default_init(self):
        assert self.sp.is_valid is False, \
            "is_valid must be False until all mandatory broker properties are populated"
    def test_has_12_fields(self):
        import dataclasses
        assert len(dataclasses.fields(SymbolProperties)) == 12


class TestOHLCVBarDefaults:
    def setup_method(self):
        self.bar = OHLCVBar()

    def test_time_default(self):        assert self.bar.time        == _UTC_EPOCH
    def test_open_default(self):        assert self.bar.open        == 0.0
    def test_high_default(self):        assert self.bar.high        == 0.0
    def test_low_default(self):         assert self.bar.low         == 0.0
    def test_close_default(self):       assert self.bar.close       == 0.0
    def test_tick_volume_default(self): assert self.bar.tick_volume == 0
    def test_has_6_fields(self):
        import dataclasses
        assert len(dataclasses.fields(OHLCVBar)) == 6


class TestSwingPointDefaults:
    def setup_method(self):
        self.sp = SwingPoint()

    def test_time_default(self):      assert self.sp.time      == _UTC_EPOCH
    def test_price_default(self):     assert self.sp.price     == 0.0
    def test_type_default(self):      assert self.sp.type      == SwingType.HIGH
    def test_timeframe_default(self): assert self.sp.timeframe == 0
    # confirmed defaults False — pending swings should never be stored
    def test_confirmed_is_false_on_default_init(self):
        assert self.sp.confirmed is False, \
            "confirmed must be False at default init — pending swings are never stored"
    def test_has_5_fields(self):
        import dataclasses
        assert len(dataclasses.fields(SwingPoint)) == 5


class TestLiquidityPoolDefaults:
    def setup_method(self):
        self.lp = LiquidityPool()

    def test_price_level_default(self):       assert self.lp.price_level       == 0.0
    def test_tolerance_band_default(self):    assert self.lp.tolerance_band    == 0.0
    def test_status_default(self):            assert self.lp.status            == PoolStatus.ACTIVE
    def test_side_default(self):              assert self.lp.side              == PoolSide.ABOVE
    def test_created_timestamp_default(self): assert self.lp.created_timestamp == _UTC_EPOCH
    def test_swept_timestamp_default(self):   assert self.lp.swept_timestamp   == _UTC_EPOCH
    # sweep_event is None when pool has not been swept (Python equivalent of MQL5 zero-init)
    def test_sweep_event_is_none_on_default_init(self):
        assert self.lp.sweep_event is None, \
            "sweep_event must be None until a sweep is confirmed"
    def test_has_7_fields(self):
        import dataclasses
        assert len(dataclasses.fields(LiquidityPool)) == 7


class TestATRResultDefaults:
    def setup_method(self):
        self.ar = ATRResult()

    def test_current_atr_default(self):     assert self.ar.current_atr     == 0.0
    def test_baseline_atr_default(self):    assert self.ar.baseline_atr    == 0.0
    def test_status_default(self):          assert self.ar.status          == ATRFilterStatus.UNAVAILABLE
    def test_min_sl_distance_default(self): assert self.ar.min_sl_distance == 0.0
    def test_has_4_fields(self):
        import dataclasses
        assert len(dataclasses.fields(ATRResult)) == 4


class TestMomentumResultDefaults:
    def setup_method(self):
        self.mr = MomentumResult()

    def test_status_default(self):             assert self.mr.status             == MomentumStatus.INSUFFICIENT_DATA
    def test_range_high_default(self):         assert self.mr.range_high         == 0.0
    def test_range_low_default(self):          assert self.mr.range_low          == 0.0
    def test_close_position_pct_default(self): assert self.mr.close_position_pct == 0.0
    def test_rejection_reason_default(self):   assert self.mr.rejection_reason   == ""
    def test_has_5_fields(self):
        import dataclasses
        assert len(dataclasses.fields(MomentumResult)) == 5


class TestEAStateDefaults:
    def setup_method(self):
        self.st = EAState()

    def test_daily_drawdown_pct_default(self):        assert self.st.daily_drawdown_pct        == 0.0
    def test_daily_open_equity_default(self):         assert self.st.daily_open_equity         == 0.0
    def test_total_drawdown_ref_equity_default(self): assert self.st.total_drawdown_ref_equity == 0.0
    def test_consecutive_losses_default(self):        assert self.st.consecutive_losses        == 0
    def test_cooldown_start_utc_default(self):        assert self.st.cooldown_start_utc        == _UTC_EPOCH
    # Safety booleans MUST default to False
    def test_circuit_breaker_triggered_is_false(self):
        assert self.st.circuit_breaker_triggered is False, \
            "circuit_breaker_triggered must default False — EA must not start in triggered state"
    def test_safe_mode_active_is_false(self):
        assert self.st.safe_mode_active is False, \
            "safe_mode_active must default False — EA must not start in SAFE_MODE"
    def test_last_update_utc_default(self):     assert self.st.last_update_utc     == _UTC_EPOCH
    def test_state_file_version_default(self):  assert self.st.state_file_version  == 0
    def test_symbol_default(self):              assert self.st.symbol              == ""
    def test_account_suffix_default(self):      assert self.st.account_suffix      == ""
    def test_checksum_default(self):            assert self.st.checksum            == 0
    def test_has_12_fields(self):
        import dataclasses
        assert len(dataclasses.fields(EAState)) == 12


# ===========================================================================
# 4. Enum-value cross-consistency (Python IntEnum arithmetic)
# ===========================================================================

class TestEnumArithmetic:
    """Verify that enum values behave as integers (IntEnum contract)."""

    def test_direction_as_int(self):
        assert int(Direction.LONG) == 1
        assert Direction.LONG + 1  == Direction.SHORT

    def test_signal_type_as_int(self):
        assert int(SignalType.FILTER_ALLOWED) == 9
        assert SignalType.UNKNOWN - SignalType.SWEEP_LONG == 12

    def test_pool_status_ordering(self):
        assert PoolStatus.ACTIVE < PoolStatus.SWEPT < PoolStatus.INVALIDATED

    def test_atr_status_ordering(self):
        assert ATRFilterStatus.ALLOW < ATRFilterStatus.UNAVAILABLE

    def test_execution_status_as_int(self):
        assert int(ExecutionStatus.FILLED) == 0

    def test_ea_state_hard_disabled_is_max(self):
        assert EAOperationalState.HARD_DISABLED == max(EAOperationalState)


# ===========================================================================
# 5. Immutability of independent instances (no shared state)
# ===========================================================================

class TestInstanceIndependence:
    """Modifying one instance must not affect another."""

    def test_analysis_status_instances_independent(self):
        a = AnalysisStatus()
        b = AnalysisStatus()
        a.confidence = 75
        assert b.confidence == 0, "Instances must not share state"

    def test_ea_state_instances_independent(self):
        s1 = EAState()
        s2 = EAState()
        s1.consecutive_losses = 3
        assert s2.consecutive_losses == 0

    def test_liquidity_pool_sweep_event_independent(self):
        p1 = LiquidityPool()
        p2 = LiquidityPool()
        p1.sweep_event = AnalysisStatus(confidence=50)
        assert p2.sweep_event is None, "sweep_event must be independent per instance"
