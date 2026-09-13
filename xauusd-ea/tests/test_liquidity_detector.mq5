//+------------------------------------------------------------------+
//| test_liquidity_detector.mq5                                      |
//| XAU/USD MT5 Expert Advisor                                       |
//| Task 11: LiquidityDetector unit tests (static verification)     |
//|                                                                  |
//| NOTE: MetaEditor compilation and MT5 runtime execution are NOT  |
//| available in this environment. This file is a static test script |
//| that mirrors the Python pytest tests in test_liquidity.py.      |
//| All correctness properties are verified by the Python suite.    |
//|                                                                  |
//| Properties tested:                                               |
//|   Property 5: Sweep round-trip                                  |
//|   Property 6: Pool lifecycle state machine                      |
//|   Property 7: MaxActivePools invariant                          |
//| Requirements: 2.1-2.7                                           |
//+------------------------------------------------------------------+
#include "../include/core/Types.mqh"
#include "../include/core/Constants.mqh"
#include "../include/utils/Logger.mqh"
#include "../include/analysis/LiquidityDetector.mqh"

static int g_tests_run    = 0;
static int g_tests_passed = 0;
static int g_tests_failed = 0;

#define ASSERT(cond, msg) \
    g_tests_run++; \
    if(cond) { g_tests_passed++; Print("  PASS: ", msg); } \
    else      { g_tests_failed++; Print("  FAIL: ", msg); }

OHLCVBar MakeBar(double h, double l, double c, datetime t)
{
    OHLCVBar b = {};
    b.time   = t; b.open  = (h+l)/2.0;
    b.high   = h; b.low   = l; b.close = c; b.volume = 100;
    return b;
}

ATRResult MakeATR(double v, ATRFilterStatus s = ATR_ALLOW)
{
    ATRResult r = {}; r.current_atr=v; r.baseline_atr=v;
    r.status=s; r.min_sl_distance=v*1.5; return r;
}

void LoadSinglePool(LiquidityDetector& det, double price, double tol,
                    PoolStatus st, PoolSide side, datetime cr, datetime sw=0)
{
    LiquidityPool p[]; ArrayResize(p,1);
    p[0].price_level=price; p[0].tolerance_band=tol; p[0].status=st;
    p[0].side=side; p[0].created_timestamp=cr; p[0].swept_timestamp=sw;
    det.LoadPools(p,1);
}

void MakeSweepBarsAbove(OHLCVBar& bars[], double pl)
{
    ArrayResize(bars,5);
    bars[0]=MakeBar(pl+1.0,  pl-5.0, pl-0.5, D'2026.01.01 00:00');
    bars[1]=MakeBar(pl+10.0, pl-5.0, pl-5.0, D'2026.01.01 00:15');
    bars[2]=MakeBar(pl-5.0, pl-15.0, pl-10.0,D'2026.01.01 00:30');
    bars[3]=MakeBar(pl-5.0, pl-15.0, pl-10.0,D'2026.01.01 00:45');
    bars[4]=MakeBar(pl-5.0, pl-15.0, pl-10.0,D'2026.01.01 01:00');
}

void TestPoolCreation()
{
    Print("--- TestPoolCreation ---");
    LiquidityDetector det; det.Configure(1,20,0.5);
    OHLCVBar b[]; ArrayResize(b,4);
    b[0]=MakeBar(2010,1990,2000,D'2026.01.01 00:00');
    b[1]=MakeBar(2020,1990,2005,D'2026.01.01 00:15');
    b[2]=MakeBar(2010,1990,2000,D'2026.01.01 00:30');
    b[3]=MakeBar(2010,1990,2000,D'2026.01.01 00:45');
    LiquidityStatus s=det.Update(b,4,MakeATR(10));
    ASSERT(s.active_above>=1, "Swing high creates ABOVE pool (Req 2.1)");
    LiquidityPool p[]; det.GetPools(p);
    bool found=false;
    for(int i=0;i<ArraySize(p);i++)
        if(p[i].side==POOL_SIDE_ABOVE && MathAbs(p[i].price_level-2020)<1e-6
           && p[i].status==POOL_ACTIVE) found=true;
    ASSERT(found, "Pool at 2020 is ACTIVE");
    ASSERT(det.GetPoolCount()>=1, "Pool registry non-empty");
}

void TestATRUnavailable()
{
    Print("--- TestATRUnavailable ---");
    LiquidityDetector det; det.Configure(1,20,0.5);
    OHLCVBar b[]; ArrayResize(b,4);
    b[0]=MakeBar(2010,1990,2000,D'2026.01.01 00:00');
    b[1]=MakeBar(2020,1990,2005,D'2026.01.01 00:15');
    b[2]=MakeBar(2010,1990,2000,D'2026.01.01 00:30');
    b[3]=MakeBar(2010,1990,2000,D'2026.01.01 00:45');
    LiquidityStatus s=det.Update(b,4,MakeATR(0,ATR_UNAVAILABLE));
    ASSERT(s.atr_available==false,"atr_available=false when ATR UNAVAILABLE (Req 2.6)");
    ASSERT(det.GetPoolCount()==0,"No pools created when ATR UNAVAILABLE");
}

void TestATRUnavailableRetainsPools()
{
    LiquidityDetector det; det.Configure(1,20,0.5);
    LoadSinglePool(det,2100,5,POOL_ACTIVE,POOL_SIDE_ABOVE,D'2026.01.01 00:00');
    OHLCVBar b[]; ArrayResize(b,4);
    for(int i=0;i<4;i++) b[i]=MakeBar(2010,1990,2000,D'2026.01.01 00:00'+i*900);
    det.Update(b,4,MakeATR(0,ATR_UNAVAILABLE));
    ASSERT(det.GetPoolCount()==1,"Existing pool retained when ATR UNAVAILABLE");
}

void TestProperty5_SweepRoundTrip()
{
    Print("--- TestProperty5: Sweep round-trip ---");
    LiquidityDetector det; det.Configure(1,20,0.5);
    LoadSinglePool(det,2100,5,POOL_ACTIVE,POOL_SIDE_ABOVE,D'2026.01.01 00:00');
    OHLCVBar b[]; MakeSweepBarsAbove(b,2100);
    LiquidityStatus s=det.Update(b,5,MakeATR(10));
    ASSERT(s.sweep_occurred==true,"Property 5: Sweep detected (Req 2.2)");
    ASSERT(s.swept_pool.status==POOL_SWEPT,"Property 5: swept_pool.status=SWEPT");
    ASSERT(s.swept_pool.swept_timestamp==b[0].time,"Property 5: swept_ts=bars[0].time");
}

void TestProperty5_NoSweepWithoutWick()
{
    LiquidityDetector det; det.Configure(1,20,0.5);
    LoadSinglePool(det,2100,5,POOL_ACTIVE,POOL_SIDE_ABOVE,D'2026.01.01 00:00');
    OHLCVBar b[]; ArrayResize(b,5);
    for(int i=0;i<5;i++) b[i]=MakeBar(2095,2085,2090,D'2026.01.01 00:00'+i*900);
    LiquidityStatus s=det.Update(b,5,MakeATR(10));
    ASSERT(s.sweep_occurred==false,"Property 5: No sweep without wick-through");
}

void TestProperty5_Bar0IsNotSweepCandle()
{
    LiquidityDetector det; det.Configure(1,20,0.5);
    LoadSinglePool(det,2100,5,POOL_ACTIVE,POOL_SIDE_ABOVE,D'2026.01.01 00:00');
    OHLCVBar b[]; ArrayResize(b,5);
    b[0]=MakeBar(2115,2095,2099,D'2026.01.01 00:00'); // wick above but bars[0]
    b[1]=MakeBar(2095,2085,2090,D'2026.01.01 00:15'); // bars[1] stays below
    for(int i=2;i<5;i++) b[i]=MakeBar(2095,2085,2090,D'2026.01.01 00:00'+i*900);
    LiquidityStatus s=det.Update(b,5,MakeATR(10));
    ASSERT(s.sweep_occurred==false,"Req 2.7: bars[0] is never the sweep candle");
}

void TestProperty6_SweptNoFurtherSweep()
{
    Print("--- TestProperty6: Lifecycle state machine ---");
    LiquidityDetector det; det.Configure(1,20,0.5);
    LoadSinglePool(det,2100,5,POOL_ACTIVE,POOL_SIDE_ABOVE,D'2026.01.01 00:00');
    OHLCVBar b[]; MakeSweepBarsAbove(b,2100);
    LiquidityStatus s1=det.Update(b,5,MakeATR(10));
    ASSERT(s1.sweep_occurred,"Property 6: First sweep fires");
    LiquidityStatus s2=det.Update(b,5,MakeATR(10));
    ASSERT(s2.sweep_occurred==false,"Property 6: Swept pool no further sweep (Req 2.4)");
}

void TestProperty6_SweptNotInvalidated()
{
    LiquidityDetector det; det.Configure(1,20,0.5);
    LoadSinglePool(det,2100,5,POOL_SWEPT,POOL_SIDE_ABOVE,D'2026.01.01 00:00',D'2026.01.01 01:00');
    OHLCVBar b[]; ArrayResize(b,5);
    b[0]=MakeBar(2120,2106,2112,D'2026.01.01 02:00');
    for(int i=1;i<5;i++) b[i]=MakeBar(2095,2085,2090,D'2026.01.01 00:00'+i*900);
    det.Update(b,5,MakeATR(10));
    LiquidityPool p[]; det.GetPools(p);
    for(int i=0;i<ArraySize(p);i++)
        if(MathAbs(p[i].price_level-2100)<1e-6)
            ASSERT(p[i].status==POOL_SWEPT,"Property 6: Swept->Invalidated is invalid transition");
}

void TestProperty6_InvalidatedNotSwept()
{
    LiquidityDetector det; det.Configure(1,20,0.5);
    LoadSinglePool(det,2100,5,POOL_INVALIDATED,POOL_SIDE_ABOVE,D'2026.01.01 00:00');
    OHLCVBar b[]; MakeSweepBarsAbove(b,2100);
    LiquidityStatus s=det.Update(b,5,MakeATR(10));
    ASSERT(s.sweep_occurred==false,"Property 6: Invalidated pool cannot be swept");
}

void TestProperty7_MaxPoolsInvariant()
{
    Print("--- TestProperty7: MaxActivePools invariant ---");
    const int MAX=5;
    LiquidityDetector det; det.Configure(1,MAX,0.001);
    for(int batch=0;batch<10;batch++)
    {
        double ph=2000.0+batch*20.0;
        OHLCVBar b[]; ArrayResize(b,4);
        b[0]=MakeBar(ph-5,ph-15,ph-10,D'2026.01.01 00:00'+batch*3600);
        b[1]=MakeBar(ph,  ph-10,ph-5, D'2026.01.01 00:15'+batch*3600);
        b[2]=MakeBar(ph-5,ph-15,ph-10,D'2026.01.01 00:30'+batch*3600);
        b[3]=MakeBar(ph-5,ph-15,ph-10,D'2026.01.01 00:45'+batch*3600);
        LiquidityStatus s=det.Update(b,4,MakeATR(0.001));
        ASSERT(s.active_pool_count<=MAX,
            StringFormat("Property 7: pool_count(%d)<=max(%d) at batch %d",
                         s.active_pool_count,MAX,batch));
    }
}

void TestArchitecture_ToleranceLockedAtCreation()
{
    Print("--- TestArchitecture ---");
    LiquidityDetector det; det.Configure(1,20,0.5);
    OHLCVBar b[]; ArrayResize(b,4);
    b[0]=MakeBar(2010,1990,2000,D'2026.01.01 00:00');
    b[1]=MakeBar(2020,1990,2005,D'2026.01.01 00:15');
    b[2]=MakeBar(2010,1990,2000,D'2026.01.01 00:30');
    b[3]=MakeBar(2010,1990,2000,D'2026.01.01 00:45');
    det.Update(b,4,MakeATR(10));
    LiquidityPool p1[]; det.GetPools(p1);
    double ctol=-1;
    for(int i=0;i<ArraySize(p1);i++)
        if(p1[i].status==POOL_ACTIVE) ctol=p1[i].tolerance_band;
    det.Update(b,4,MakeATR(100));
    LiquidityPool p2[]; det.GetPools(p2);
    for(int i=0;i<ArraySize(p2);i++)
        if(p2[i].status==POOL_ACTIVE && ctol>0)
            ASSERT(MathAbs(p2[i].tolerance_band-ctol)<1e-8,
                   "Design 2.4: Pool tolerance locked at creation ATR");
}

void OnStart()
{
    Print("=============================================================");
    Print("test_liquidity_detector.mq5 - Task 11 Unit Tests");
    Print("=============================================================");
    TestPoolCreation();
    TestATRUnavailable();
    TestATRUnavailableRetainsPools();
    TestProperty5_SweepRoundTrip();
    TestProperty5_NoSweepWithoutWick();
    TestProperty5_Bar0IsNotSweepCandle();
    TestProperty6_SweptNoFurtherSweep();
    TestProperty6_SweptNotInvalidated();
    TestProperty6_InvalidatedNotSwept();
    TestProperty7_MaxPoolsInvariant();
    TestArchitecture_ToleranceLockedAtCreation();
    Print("=============================================================");
    Print(StringFormat("Tests run: %d  Passed: %d  Failed: %d",
          g_tests_run, g_tests_passed, g_tests_failed));
    if(g_tests_failed==0) Print("RESULT: ALL TESTS PASSED");
    else Print("RESULT: FAILURES DETECTED");
    Print("NOTE: MetaEditor/MT5 runtime NOT executed - Python pytest is");
    Print("the authoritative test runner for this project.");
    Print("=============================================================");
}
