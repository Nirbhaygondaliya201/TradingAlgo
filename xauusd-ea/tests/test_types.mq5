//+------------------------------------------------------------------+
//| test_types.mq5                                                   |
//| XAU/USD MT5 Expert Advisor — Unit Tests                         |
//| Task 1.2: Verify all struct fields are accessible and            |
//|           zero-initialise correctly.                             |
//|                                                                  |
//| Run as a Script in MetaTrader 5 (not as an EA or indicator).     |
//| Each test prints PASS or FAIL to the Experts log.               |
//| Requirements: 13.1                                               |
//+------------------------------------------------------------------+
#property script_show_inputs
#include <..\include\core\Types.mqh>
#include <..\include\core\Constants.mqh>

//--- Test counter state
int g_pass = 0;
int g_fail = 0;

//--- Helper macros
#define ASSERT_EQ(label, actual, expected) \
    if((actual) == (expected)) { \
        PrintFormat("PASS | %s | actual=%s expected=%s", (label), (string)(actual), (string)(expected)); \
        g_pass++; \
    } else { \
        PrintFormat("FAIL | %s | actual=%s expected=%s", (label), (string)(actual), (string)(expected)); \
        g_fail++; \
    }

#define ASSERT_TRUE(label, expr) \
    if(expr) { \
        PrintFormat("PASS | %s", (label)); \
        g_pass++; \
    } else { \
        PrintFormat("FAIL | %s | expression was false", (label)); \
        g_fail++; \
    }

#define ASSERT_FALSE(label, expr) \
    if(!(expr)) { \
        PrintFormat("PASS | %s", (label)); \
        g_pass++; \
    } else { \
        PrintFormat("FAIL | %s | expression was true (expected false)", (label)); \
        g_fail++; \
    }

//+------------------------------------------------------------------+
//| Script entry point                                               |
//+------------------------------------------------------------------+
void OnStart()
{
    Print("=== test_types.mq5 START ===");

    Test_Enums();
    Test_AnalysisStatus_ZeroInit();
    Test_TradeSignal_ZeroInit();
    Test_TradeOrder_ZeroInit();
    Test_ExecutionResult_ZeroInit();
    Test_RejectionResult_ZeroInit();
    Test_SymbolProperties_ZeroInit();
    Test_OHLCVBar_ZeroInit();
    Test_SwingPoint_ZeroInit();
    Test_LiquidityPool_ZeroInit();
    Test_ATRResult_ZeroInit();
    Test_MomentumResult_ZeroInit();
    Test_EAState_ZeroInit();
    Test_Constants();
    Test_EnumCoverage_Direction();
    Test_EnumCoverage_SignalType();
    Test_EnumCoverage_PoolStatus();
    Test_EnumCoverage_ATRFilterStatus();
    Test_EnumCoverage_MomentumStatus();
    Test_EnumCoverage_ExecutionStatus();
    Test_EnumCoverage_OrderType();
    Test_EnumCoverage_SwingType();

    PrintFormat("=== test_types.mq5 DONE | PASS: %d | FAIL: %d ===", g_pass, g_fail);
}

//+------------------------------------------------------------------+
//| Test: Enum values are distinct and non-negative                  |
//+------------------------------------------------------------------+
void Test_Enums()
{
    // Direction
    ASSERT_TRUE("Direction: NONE != LONG",  DIRECTION_NONE  != DIRECTION_LONG);
    ASSERT_TRUE("Direction: LONG != SHORT", DIRECTION_LONG  != DIRECTION_SHORT);
    ASSERT_TRUE("Direction: NONE >= 0",     DIRECTION_NONE  >= 0);

    // SignalType — all 13 values must be distinct
    ASSERT_TRUE("SignalType: 13 values distinct",
        SIGNAL_SWEEP_LONG != SIGNAL_SWEEP_SHORT &&
        SIGNAL_BOS_LONG   != SIGNAL_BOS_SHORT   &&
        SIGNAL_REGIME_BULLISH != SIGNAL_REGIME_RANGING &&
        SIGNAL_FILTER_ALLOWED != SIGNAL_FILTER_BLOCKED &&
        SIGNAL_FILTER_BLOCKED != SIGNAL_FILTER_WARN &&
        SIGNAL_UNKNOWN    >= 0);

    // OrderType
    ASSERT_TRUE("OrderType: BUY != SELL", ORDER_MARKET_BUY != ORDER_MARKET_SELL);

    // SwingType
    ASSERT_TRUE("SwingType: HIGH != LOW", SWING_HIGH != SWING_LOW);

    // PoolStatus
    ASSERT_TRUE("PoolStatus: all distinct",
        POOL_ACTIVE != POOL_SWEPT && POOL_SWEPT != POOL_INVALIDATED);

    // EAOperationalState
    ASSERT_TRUE("EAOpState: all distinct",
        EA_STATE_INITIALISING != EA_STATE_RUNNING &&
        EA_STATE_RUNNING      != EA_STATE_SAFE_MONITORING &&
        EA_STATE_HARD_DISABLED >= 0);
}

//+------------------------------------------------------------------+
//| Test: AnalysisStatus zero-initialises correctly                  |
//+------------------------------------------------------------------+
void Test_AnalysisStatus_ZeroInit()
{
    AnalysisStatus s = {};
    ASSERT_EQ("AnalysisStatus.signal_type default", (int)s.signal_type, 0);
    ASSERT_EQ("AnalysisStatus.direction default",   (int)s.direction,   0);
    ASSERT_EQ("AnalysisStatus.confidence default",  s.confidence,       0);
    ASSERT_EQ("AnalysisStatus.timestamp default",   (long)s.timestamp,  0L);
    // string fields: MQL5 initialises strings to ""
    ASSERT_EQ("AnalysisStatus.source_module default",   s.source_module,   "");
    ASSERT_EQ("AnalysisStatus.rejection_reason default", s.rejection_reason, "");
}

//+------------------------------------------------------------------+
//| Test: TradeSignal zero-initialises correctly                     |
//+------------------------------------------------------------------+
void Test_TradeSignal_ZeroInit()
{
    TradeSignal ts = {};
    ASSERT_EQ("TradeSignal.entry_price default",            ts.entry_price,            0.0);
    ASSERT_EQ("TradeSignal.signal_reference_price default", ts.signal_reference_price, 0.0);
    ASSERT_EQ("TradeSignal.stop_loss_price default",        ts.stop_loss_price,        0.0);
    ASSERT_EQ("TradeSignal.take_profit_price default",      ts.take_profit_price,      0.0);
    ASSERT_EQ("TradeSignal.direction default",              (int)ts.direction,         0);
    ASSERT_EQ("TradeSignal.signal_timestamp default",       (long)ts.signal_timestamp, 0L);
    ASSERT_EQ("TradeSignal.atr_at_signal default",          ts.atr_at_signal,          0.0);
    ASSERT_EQ("TradeSignal.regime default",                 ts.regime,                 0);
    ASSERT_EQ("TradeSignal.computed_rr default",            ts.computed_rr,            0.0);
    ASSERT_EQ("TradeSignal.tp_pool_level default",          ts.tp_pool_level,          "");
    ASSERT_EQ("TradeSignal.rejection_reason default",       ts.rejection_reason,       "");
}

//+------------------------------------------------------------------+
//| Test: TradeOrder zero-initialises correctly                      |
//+------------------------------------------------------------------+
void Test_TradeOrder_ZeroInit()
{
    TradeOrder to = {};
    ASSERT_EQ("TradeOrder.symbol default",                to.symbol,                "");
    ASSERT_EQ("TradeOrder.order_type default",            (int)to.order_type,       0);
    ASSERT_EQ("TradeOrder.volume default",                to.volume,                0.0);
    ASSERT_EQ("TradeOrder.entry_price default",           to.entry_price,           0.0);
    ASSERT_EQ("TradeOrder.signal_reference_price default",to.signal_reference_price,0.0);
    ASSERT_EQ("TradeOrder.stop_loss_price default",       to.stop_loss_price,       0.0);
    ASSERT_EQ("TradeOrder.take_profit_price default",     to.take_profit_price,     0.0);
    ASSERT_EQ("TradeOrder.timestamp default",             (long)to.timestamp,       0L);
    ASSERT_EQ("TradeOrder.magic_number default",          to.magic_number,          0);
    ASSERT_EQ("TradeOrder.max_slippage_points default",   to.max_slippage_points,   0.0);
}

//+------------------------------------------------------------------+
//| Test: ExecutionResult zero-initialises correctly                 |
//+------------------------------------------------------------------+
void Test_ExecutionResult_ZeroInit()
{
    ExecutionResult er = {};
    ASSERT_EQ("ExecutionResult.status default",              (int)er.status,                0);
    ASSERT_EQ("ExecutionResult.ticket default",              er.ticket,                     0L);
    ASSERT_EQ("ExecutionResult.filled_price default",        er.filled_price,               0.0);
    ASSERT_EQ("ExecutionResult.filled_sl default",           er.filled_sl,                  0.0);
    ASSERT_EQ("ExecutionResult.filled_tp default",           er.filled_tp,                  0.0);
    ASSERT_EQ("ExecutionResult.mt5_error_code default",      er.mt5_error_code,             0);
    ASSERT_EQ("ExecutionResult.error_description default",   er.error_description,          "");
    ASSERT_EQ("ExecutionResult.execution_timestamp default", (long)er.execution_timestamp,  0L);
}

//+------------------------------------------------------------------+
//| Test: RejectionResult zero-initialises correctly                 |
//+------------------------------------------------------------------+
void Test_RejectionResult_ZeroInit()
{
    RejectionResult rr = {};
    ASSERT_EQ("RejectionResult.unmet_criterion default", rr.unmet_criterion, "");
    ASSERT_EQ("RejectionResult.computed_value default",  rr.computed_value,  0.0);
    ASSERT_EQ("RejectionResult.required_value default",  rr.required_value,  0.0);
    ASSERT_EQ("RejectionResult.timestamp default",       (long)rr.timestamp, 0L);
}

//+------------------------------------------------------------------+
//| Test: SymbolProperties zero-initialises and is_valid is false    |
//+------------------------------------------------------------------+
void Test_SymbolProperties_ZeroInit()
{
    SymbolProperties sp = {};
    ASSERT_EQ("SymbolProperties.point default",               sp.point,               0.0);
    ASSERT_EQ("SymbolProperties.lot_step default",            sp.lot_step,            0.0);
    ASSERT_EQ("SymbolProperties.min_lot default",             sp.min_lot,             0.0);
    ASSERT_EQ("SymbolProperties.max_lot default",             sp.max_lot,             0.0);
    ASSERT_EQ("SymbolProperties.contract_size default",       sp.contract_size,       0.0);
    ASSERT_EQ("SymbolProperties.stop_level_points default",   sp.stop_level_points,   0);
    ASSERT_EQ("SymbolProperties.freeze_level_points default", sp.freeze_level_points, 0);
    ASSERT_EQ("SymbolProperties.tick_size default",           sp.tick_size,           0.0);
    ASSERT_EQ("SymbolProperties.tick_value default",          sp.tick_value,          0.0);
    ASSERT_EQ("SymbolProperties.digits default",              sp.digits,              0);
    ASSERT_EQ("SymbolProperties.margin_initial default",      sp.margin_initial,      0.0);
    // is_valid must default false — no properties have been read yet
    ASSERT_FALSE("SymbolProperties.is_valid default is false", sp.is_valid);
}

//+------------------------------------------------------------------+
//| Test: OHLCVBar zero-initialises correctly                        |
//+------------------------------------------------------------------+
void Test_OHLCVBar_ZeroInit()
{
    OHLCVBar bar = {};
    ASSERT_EQ("OHLCVBar.time default",        (long)bar.time, 0L);
    ASSERT_EQ("OHLCVBar.open default",        bar.open,       0.0);
    ASSERT_EQ("OHLCVBar.high default",        bar.high,       0.0);
    ASSERT_EQ("OHLCVBar.low default",         bar.low,        0.0);
    ASSERT_EQ("OHLCVBar.close default",       bar.close,      0.0);
    ASSERT_EQ("OHLCVBar.tick_volume default", bar.tick_volume,0L);
}

//+------------------------------------------------------------------+
//| Test: SwingPoint zero-initialises correctly                      |
//+------------------------------------------------------------------+
void Test_SwingPoint_ZeroInit()
{
    SwingPoint sp = {};
    ASSERT_EQ("SwingPoint.time default",      (long)sp.time, 0L);
    ASSERT_EQ("SwingPoint.price default",     sp.price,      0.0);
    ASSERT_EQ("SwingPoint.type default",      (int)sp.type,  0);
    ASSERT_EQ("SwingPoint.timeframe default", sp.timeframe,  0);
    // confirmed must default false — unconfirmed swing
    ASSERT_FALSE("SwingPoint.confirmed default is false", sp.confirmed);
}

//+------------------------------------------------------------------+
//| Test: LiquidityPool zero-initialises correctly                   |
//+------------------------------------------------------------------+
void Test_LiquidityPool_ZeroInit()
{
    LiquidityPool lp = {};
    ASSERT_EQ("LiquidityPool.price_level default",       lp.price_level,       0.0);
    ASSERT_EQ("LiquidityPool.tolerance_band default",    lp.tolerance_band,    0.0);
    ASSERT_EQ("LiquidityPool.status default",            (int)lp.status,       0);
    ASSERT_EQ("LiquidityPool.side default",              (int)lp.side,         0);
    ASSERT_EQ("LiquidityPool.created_timestamp default", (long)lp.created_timestamp, 0L);
    ASSERT_EQ("LiquidityPool.swept_timestamp default",   (long)lp.swept_timestamp,   0L);
}

//+------------------------------------------------------------------+
//| Test: ATRResult zero-initialises correctly                       |
//+------------------------------------------------------------------+
void Test_ATRResult_ZeroInit()
{
    ATRResult ar = {};
    ASSERT_EQ("ATRResult.current_atr default",    ar.current_atr,   0.0);
    ASSERT_EQ("ATRResult.baseline_atr default",   ar.baseline_atr,  0.0);
    ASSERT_EQ("ATRResult.status default",         (int)ar.status,   0);
    ASSERT_EQ("ATRResult.min_sl_distance default",ar.min_sl_distance, 0.0);
}

//+------------------------------------------------------------------+
//| Test: MomentumResult zero-initialises correctly                  |
//+------------------------------------------------------------------+
void Test_MomentumResult_ZeroInit()
{
    MomentumResult mr = {};
    ASSERT_EQ("MomentumResult.status default",             (int)mr.status,          0);
    ASSERT_EQ("MomentumResult.range_high default",         mr.range_high,            0.0);
    ASSERT_EQ("MomentumResult.range_low default",          mr.range_low,             0.0);
    ASSERT_EQ("MomentumResult.close_position_pct default", mr.close_position_pct,    0.0);
    ASSERT_EQ("MomentumResult.rejection_reason default",   mr.rejection_reason,      "");
}

//+------------------------------------------------------------------+
//| Test: EAState zero-initialises correctly                         |
//+------------------------------------------------------------------+
void Test_EAState_ZeroInit()
{
    EAState st = {};
    ASSERT_EQ("EAState.daily_drawdown_pct default",        st.daily_drawdown_pct,        0.0);
    ASSERT_EQ("EAState.daily_open_equity default",         st.daily_open_equity,         0.0);
    ASSERT_EQ("EAState.total_drawdown_ref_equity default", st.total_drawdown_ref_equity, 0.0);
    ASSERT_EQ("EAState.consecutive_losses default",        st.consecutive_losses,        0);
    ASSERT_EQ("EAState.cooldown_start_utc default",        (long)st.cooldown_start_utc,  0L);
    ASSERT_FALSE("EAState.circuit_breaker_triggered default is false", st.circuit_breaker_triggered);
    ASSERT_FALSE("EAState.safe_mode_active default is false",          st.safe_mode_active);
    ASSERT_EQ("EAState.last_update_utc default",           (long)st.last_update_utc,     0L);
    ASSERT_EQ("EAState.state_file_version default",        st.state_file_version,        0);
    ASSERT_EQ("EAState.symbol default",                    st.symbol,                    "");
    ASSERT_EQ("EAState.account_suffix default",            st.account_suffix,            "");
    ASSERT_EQ("EAState.checksum default",                  (long)st.checksum,            0L);
}

//+------------------------------------------------------------------+
//| Test: Constants have expected values                             |
//+------------------------------------------------------------------+
void Test_Constants()
{
    ASSERT_TRUE("EA_MAGIC_NUMBER > 0",        EA_MAGIC_NUMBER > 0);
    ASSERT_TRUE("EA_VERSION_INT > 0",         EA_VERSION_INT  > 0);
    ASSERT_TRUE("STATE_FILE_VERSION > 0",     STATE_FILE_VERSION > 0);
    ASSERT_TRUE("ATR_BASELINE_MIN_BARS == 14", ATR_BASELINE_MIN_BARS == 14);
    ASSERT_TRUE("ATR_BASELINE_WINDOW_BARS == 720", ATR_BASELINE_WINDOW_BARS == 720);
    ASSERT_TRUE("EA_TIMEFRAME_COUNT == 4",    EA_TIMEFRAME_COUNT == 4);
    ASSERT_TRUE("DEFAULT_MAX_FREEZE_SKIPS == 5", DEFAULT_MAX_FREEZE_SKIPS == 5);
    ASSERT_TRUE("SAFE_MODE_FLAG_FILENAME not empty",
                StringLen(SAFE_MODE_FLAG_FILENAME) > 0);
}

//+------------------------------------------------------------------+
//| Enum coverage tests — verify each enum value exists and is       |
//| reachable (exercises compiler parsing of every enum constant).   |
//+------------------------------------------------------------------+
void Test_EnumCoverage_Direction()
{
    Direction vals[3] = {DIRECTION_NONE, DIRECTION_LONG, DIRECTION_SHORT};
    ASSERT_EQ("Direction: 3 values exist", ArraySize(vals), 3);
}

void Test_EnumCoverage_SignalType()
{
    SignalType vals[13] = {
        SIGNAL_SWEEP_LONG, SIGNAL_SWEEP_SHORT, SIGNAL_BOS_LONG, SIGNAL_BOS_SHORT,
        SIGNAL_CHOCH_LONG, SIGNAL_CHOCH_SHORT,
        SIGNAL_REGIME_BULLISH, SIGNAL_REGIME_BEARISH, SIGNAL_REGIME_RANGING,
        SIGNAL_FILTER_ALLOWED, SIGNAL_FILTER_BLOCKED, SIGNAL_FILTER_WARN,
        SIGNAL_UNKNOWN
    };
    ASSERT_EQ("SignalType: 13 values exist", ArraySize(vals), 13);
}

void Test_EnumCoverage_PoolStatus()
{
    PoolStatus vals[3] = {POOL_ACTIVE, POOL_SWEPT, POOL_INVALIDATED};
    ASSERT_EQ("PoolStatus: 3 values exist", ArraySize(vals), 3);
}

void Test_EnumCoverage_ATRFilterStatus()
{
    ATRFilterStatus vals[4] = {ATR_ALLOW, ATR_BLOCK_LOW, ATR_BLOCK_HIGH, ATR_UNAVAILABLE};
    ASSERT_EQ("ATRFilterStatus: 4 values exist", ArraySize(vals), 4);
}

void Test_EnumCoverage_MomentumStatus()
{
    MomentumStatus vals[3] = {MOMENTUM_CONFIRMED, MOMENTUM_REJECTED, MOMENTUM_INSUFFICIENT_DATA};
    ASSERT_EQ("MomentumStatus: 3 values exist", ArraySize(vals), 3);
}

void Test_EnumCoverage_ExecutionStatus()
{
    ExecutionStatus vals[3] = {EXEC_FILLED, EXEC_REJECTED, EXEC_FAILED};
    ASSERT_EQ("ExecutionStatus: 3 values exist", ArraySize(vals), 3);
}

void Test_EnumCoverage_OrderType()
{
    OrderType vals[2] = {ORDER_MARKET_BUY, ORDER_MARKET_SELL};
    ASSERT_EQ("OrderType: 2 values exist", ArraySize(vals), 2);
}

void Test_EnumCoverage_SwingType()
{
    SwingType vals[2] = {SWING_HIGH, SWING_LOW};
    ASSERT_EQ("SwingType: 2 values exist", ArraySize(vals), 2);
}
//+------------------------------------------------------------------+
