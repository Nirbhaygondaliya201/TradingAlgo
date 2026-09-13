//+------------------------------------------------------------------+
//| test_mtf_data_feed.mq5                                           |
//| XAU/USD MT5 Expert Advisor — Unit Tests                         |
//| Tasks 5.2 / 5.3: MTFDataFeed tests                             |
//|                                                                  |
//| Property 1: Confirmed-candle enforcement (no bar[0] access)     |
//| Validates: Requirements 1.1, 1.6, 2.7, 4.5, 15.5               |
//|                                                                  |
//| Tests cover:                                                     |
//|   - DataFeedResult struct defaults                              |
//|   - IsTimeframeSupported for all 4 EA timeframes               |
//|   - IsTimeframeSupported rejects unknown timeframes             |
//|   - GetLastBarTime returns 0 before any update                  |
//|   - UpdateLastBarTime stores per-timeframe times                |
//|   - ResetLastBarTimes clears all per-timeframe state            |
//|   - New-candle detection logic                                  |
//|   - count <= 0 returns BarsAvailable = 0                        |
//|   - Timeframe constant aliases match MT5 ENUM_TIMEFRAMES        |
//|   - Live GetBars() tests [LIVE_REQUIRED]                        |
//|                                                                  |
//| Run as a Script in MetaTrader 5.                                 |
//| Requirements: 1.1, 1.6, 4.5, 15.5                              |
//| Correctness Property: 1                                          |
//+------------------------------------------------------------------+
#property script_show_inputs
#include <..\include\core\Types.mqh>
#include <..\include\core\Constants.mqh>
#include <..\include\utils\Logger.mqh>
#include <..\include\data\MTFDataFeed.mqh>

int g_pass = 0;
int g_fail = 0;

#define ASSERT_EQ(label, actual, expected) \
    if((actual) == (expected)) { \
        PrintFormat("PASS | %s", (label)); g_pass++; \
    } else { \
        PrintFormat("FAIL | %s | got=%s expected=%s", \
                    (label), (string)(actual), (string)(expected)); g_fail++; \
    }

#define ASSERT_TRUE(label, expr) \
    if(expr) { PrintFormat("PASS | %s", (label)); g_pass++; } \
    else { PrintFormat("FAIL | %s | expression was false", (label)); g_fail++; }

#define ASSERT_FALSE(label, expr) \
    if(!(expr)) { PrintFormat("PASS | %s", (label)); g_pass++; } \
    else { PrintFormat("FAIL | %s | expression was true", (label)); g_fail++; }

void OnStart()
{
    Print("=== test_mtf_data_feed.mq5 START ===");
    Logger::SetMinLevel(LOG_WARN); // Suppress INFO/DEBUG in test output

    Test_StructDefaults();
    Test_TimeframeSupport();
    Test_LastBarTimeTracking();
    Test_ResetLastBarTimes();
    Test_NewCandleDetection();
    Test_InvalidCount();
    Test_TimeframeAliases();
    Test_LiveGetBars();  // Skips gracefully if no MT5 runtime data

    PrintFormat("=== test_mtf_data_feed.mq5 DONE | PASS: %d | FAIL: %d ===",
                g_pass, g_fail);
}

//+------------------------------------------------------------------+
//| Test: DataFeedResult struct defaults                             |
//+------------------------------------------------------------------+
void Test_StructDefaults()
{
    DataFeedResult r = {};
    ASSERT_EQ("Defaults.BarsAvailable",  r.BarsAvailable,  0);
    ASSERT_FALSE("Defaults.IsNewCandle",    r.IsNewCandle);
    ASSERT_FALSE("Defaults.IsSynchronised", r.IsSynchronised);
    ASSERT_EQ("Defaults.ErrorReason",    r.ErrorReason,    "");
    ASSERT_EQ("Defaults.bars size",      ArraySize(r.bars), 0);
}

//+------------------------------------------------------------------+
//| Test: IsTimeframeSupported                                       |
//+------------------------------------------------------------------+
void Test_TimeframeSupport()
{
    ASSERT_TRUE("Supported: PERIOD_H4",     MTFDataFeed::IsTimeframeSupported(PERIOD_H4));
    ASSERT_TRUE("Supported: PERIOD_H1",     MTFDataFeed::IsTimeframeSupported(PERIOD_H1));
    ASSERT_TRUE("Supported: PERIOD_M15",    MTFDataFeed::IsTimeframeSupported(PERIOD_M15));
    ASSERT_TRUE("Supported: PERIOD_M5",     MTFDataFeed::IsTimeframeSupported(PERIOD_M5));
    ASSERT_FALSE("Unsupported: PERIOD_D1",  MTFDataFeed::IsTimeframeSupported(PERIOD_D1));
    ASSERT_FALSE("Unsupported: PERIOD_M1",  MTFDataFeed::IsTimeframeSupported(PERIOD_M1));
    ASSERT_FALSE("Unsupported: PERIOD_W1",  MTFDataFeed::IsTimeframeSupported(PERIOD_W1));
    ASSERT_FALSE("Unsupported: 0",          MTFDataFeed::IsTimeframeSupported(0));
}

//+------------------------------------------------------------------+
//| Test: GetLastBarTime / UpdateLastBarTime                         |
//+------------------------------------------------------------------+
void Test_LastBarTimeTracking()
{
    MTFDataFeed::ResetLastBarTimes();

    // Before any update, all last-bar times are 0
    ASSERT_EQ("LastBarTime H4 initial=0",  MTFDataFeed::GetLastBarTime(PERIOD_H4),  0);
    ASSERT_EQ("LastBarTime H1 initial=0",  MTFDataFeed::GetLastBarTime(PERIOD_H1),  0);
    ASSERT_EQ("LastBarTime M15 initial=0", MTFDataFeed::GetLastBarTime(PERIOD_M15), 0);
    ASSERT_EQ("LastBarTime M5 initial=0",  MTFDataFeed::GetLastBarTime(PERIOD_M5),  0);

    // Update each timeframe independently
    datetime t_h4  = D'2026.01.01 08:00:00';
    datetime t_h1  = D'2026.01.01 08:00:00';
    datetime t_m15 = D'2026.01.01 08:15:00';
    datetime t_m5  = D'2026.01.01 08:05:00';

    MTFDataFeed::UpdateLastBarTime(PERIOD_H4,  t_h4);
    MTFDataFeed::UpdateLastBarTime(PERIOD_H1,  t_h1);
    MTFDataFeed::UpdateLastBarTime(PERIOD_M15, t_m15);
    MTFDataFeed::UpdateLastBarTime(PERIOD_M5,  t_m5);

    ASSERT_EQ("LastBarTime H4 after update",  MTFDataFeed::GetLastBarTime(PERIOD_H4),  t_h4);
    ASSERT_EQ("LastBarTime H1 after update",  MTFDataFeed::GetLastBarTime(PERIOD_H1),  t_h1);
    ASSERT_EQ("LastBarTime M15 after update", MTFDataFeed::GetLastBarTime(PERIOD_M15), t_m15);
    ASSERT_EQ("LastBarTime M5 after update",  MTFDataFeed::GetLastBarTime(PERIOD_M5),  t_m5);

    // Updating one timeframe must not affect others
    MTFDataFeed::UpdateLastBarTime(PERIOD_H4, D'2026.01.01 12:00:00');
    ASSERT_EQ("H1 unchanged after H4 update", MTFDataFeed::GetLastBarTime(PERIOD_H1), t_h1);
    ASSERT_EQ("M15 unchanged after H4 update",MTFDataFeed::GetLastBarTime(PERIOD_M15),t_m15);
}

//+------------------------------------------------------------------+
//| Test: ResetLastBarTimes                                          |
//+------------------------------------------------------------------+
void Test_ResetLastBarTimes()
{
    // Set non-zero values
    MTFDataFeed::UpdateLastBarTime(PERIOD_H4,  D'2026.06.01 08:00:00');
    MTFDataFeed::UpdateLastBarTime(PERIOD_H1,  D'2026.06.01 08:00:00');
    MTFDataFeed::UpdateLastBarTime(PERIOD_M15, D'2026.06.01 08:15:00');
    MTFDataFeed::UpdateLastBarTime(PERIOD_M5,  D'2026.06.01 08:05:00');

    MTFDataFeed::ResetLastBarTimes();

    ASSERT_EQ("Reset.H4 = 0",  MTFDataFeed::GetLastBarTime(PERIOD_H4),  0);
    ASSERT_EQ("Reset.H1 = 0",  MTFDataFeed::GetLastBarTime(PERIOD_H1),  0);
    ASSERT_EQ("Reset.M15 = 0", MTFDataFeed::GetLastBarTime(PERIOD_M15), 0);
    ASSERT_EQ("Reset.M5 = 0",  MTFDataFeed::GetLastBarTime(PERIOD_M5),  0);
}

//+------------------------------------------------------------------+
//| Test: New-candle detection logic                                 |
//+------------------------------------------------------------------+
void Test_NewCandleDetection()
{
    MTFDataFeed::ResetLastBarTimes(); // last = 0 for all

    // Simulate: last bar time was T1. If GetBars returns bars[0].time = T1,
    // IsNewCandle should be false. If T2 != T1, IsNewCandle should be true.

    datetime t1 = D'2026.01.01 08:00:00';
    datetime t2 = D'2026.01.01 09:00:00';

    // Update H1 to t1 (simulating prior tick result)
    MTFDataFeed::UpdateLastBarTime(PERIOD_H1, t1);
    ASSERT_EQ("LastBarTime H1 = t1", MTFDataFeed::GetLastBarTime(PERIOD_H1), t1);

    // New candle logic: bars[0].time != GetLastBarTime → IsNewCandle
    bool is_new_if_same   = (t1 != MTFDataFeed::GetLastBarTime(PERIOD_H1));
    bool is_new_if_differ = (t2 != MTFDataFeed::GetLastBarTime(PERIOD_H1));
    ASSERT_FALSE("NewCandle: same time = false",     is_new_if_same);
    ASSERT_TRUE ("NewCandle: different time = true", is_new_if_differ);
}

//+------------------------------------------------------------------+
//| Test: Invalid count returns BarsAvailable = 0                   |
//+------------------------------------------------------------------+
void Test_InvalidCount()
{
    string sym = Symbol();
    DataFeedResult r0 = MTFDataFeed::GetBars(sym, PERIOD_H1, 0);
    ASSERT_EQ("count=0 → BarsAvailable=0", r0.BarsAvailable, 0);
    ASSERT_TRUE("count=0 → ErrorReason set", StringLen(r0.ErrorReason) > 0);

    DataFeedResult rn = MTFDataFeed::GetBars(sym, PERIOD_H1, -5);
    ASSERT_EQ("count=-5 → BarsAvailable=0", rn.BarsAvailable, 0);
    ASSERT_TRUE("count=-5 → ErrorReason set", StringLen(rn.ErrorReason) > 0);
}

//+------------------------------------------------------------------+
//| Test: Timeframe alias constants match ENUM_TIMEFRAMES           |
//+------------------------------------------------------------------+
void Test_TimeframeAliases()
{
    ASSERT_EQ("TF_4H  == PERIOD_H4",  TF_4H,  (int)PERIOD_H4);
    ASSERT_EQ("TF_1H  == PERIOD_H1",  TF_1H,  (int)PERIOD_H1);
    ASSERT_EQ("TF_15M == PERIOD_M15", TF_15M, (int)PERIOD_M15);
    ASSERT_EQ("TF_5M  == PERIOD_M5",  TF_5M,  (int)PERIOD_M5);
    ASSERT_EQ("EA_TIMEFRAME_COUNT == 4", EA_TIMEFRAME_COUNT, 4);
}

//+------------------------------------------------------------------+
//| Test: Live GetBars() [LIVE_REQUIRED]                             |
//| Verifies Property 1: bar[0] is never included.                  |
//+------------------------------------------------------------------+
void Test_LiveGetBars()
{
    string sym = Symbol();
    if(!SymbolSelect(sym, true))
    {
        PrintFormat("SKIP [LIVE_REQUIRED] | symbol=%s not available", sym);
        return;
    }

    int timeframes[4] = {PERIOD_H4, PERIOD_H1, PERIOD_M15, PERIOD_M5};
    string tf_names[4] = {"H4", "H1", "M15", "M5"};
    int count = 10;

    MTFDataFeed::ResetLastBarTimes();

    for(int t = 0; t < 4; t++)
    {
        int tf = timeframes[t];
        DataFeedResult r = MTFDataFeed::GetBars(sym, tf, count);

        if(!r.IsSynchronised)
        {
            PrintFormat("SKIP [LIVE_REQUIRED] | tf=%s not synchronised", tf_names[t]);
            continue;
        }

        if(r.BarsAvailable == 0)
        {
            PrintFormat("SKIP [LIVE_REQUIRED] | tf=%s BarsAvailable=0", tf_names[t]);
            continue;
        }

        // Property 1: bars[0] must be bar index 1 (confirmed, not forming)
        // Verify: bars[0].time must be < current bar[0] open time
        datetime bar0_open = iTime(sym, (ENUM_TIMEFRAMES)tf, 0);
        ASSERT_TRUE(
            StringFormat("Property1 [%s]: bars[0].time < bar[0].time", tf_names[t]),
            r.bars[0].time < bar0_open);

        // Verify: bars[0].time == iTime(sym, tf, 1) (bar index 1)
        datetime confirmed1 = iTime(sym, (ENUM_TIMEFRAMES)tf, 1);
        ASSERT_EQ(
            StringFormat("Property1 [%s]: bars[0].time == bar_index_1", tf_names[t]),
            r.bars[0].time, confirmed1);

        // Verify: BarsAvailable <= count
        ASSERT_TRUE(
            StringFormat("[%s] BarsAvailable(%d) <= count(%d)", tf_names[t], r.BarsAvailable, count),
            r.BarsAvailable <= count);

        // Verify: timestamps are strictly decreasing (newest first)
        bool ts_ok = true;
        for(int i = 1; i < r.BarsAvailable; i++)
        {
            if(r.bars[i].time >= r.bars[i-1].time) { ts_ok = false; break; }
        }
        ASSERT_TRUE(
            StringFormat("[%s] timestamps strictly decreasing (oldest last)", tf_names[t]),
            ts_ok);

        // Verify: all OHLC values are positive
        bool ohlc_ok = true;
        for(int i = 0; i < r.BarsAvailable; i++)
        {
            if(r.bars[i].open <= 0 || r.bars[i].high <= 0 ||
               r.bars[i].low  <= 0 || r.bars[i].close <= 0)
            { ohlc_ok = false; break; }
        }
        ASSERT_TRUE(StringFormat("[%s] all OHLC > 0", tf_names[t]), ohlc_ok);

        // Verify: high >= low for all bars
        bool hl_ok = true;
        for(int i = 0; i < r.BarsAvailable; i++)
        {
            if(r.bars[i].high < r.bars[i].low) { hl_ok = false; break; }
        }
        ASSERT_TRUE(StringFormat("[%s] high >= low for all bars", tf_names[t]), hl_ok);

        // Update last bar time and verify IsNewCandle is false on repeat call
        MTFDataFeed::UpdateLastBarTime(tf, r.bars[0].time);
        DataFeedResult r2 = MTFDataFeed::GetBars(sym, tf, count);
        if(r2.BarsAvailable > 0 && r2.bars[0].time == r.bars[0].time)
        {
            ASSERT_FALSE(
                StringFormat("[%s] IsNewCandle=false when bar time unchanged", tf_names[t]),
                r2.IsNewCandle);
        }
    }
}
//+------------------------------------------------------------------+
