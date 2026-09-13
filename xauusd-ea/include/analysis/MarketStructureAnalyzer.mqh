//+------------------------------------------------------------------+
//| MarketStructureAnalyzer.mqh                                      |
//| XAU/USD MT5 Expert Advisor                                       |
//| Market structure: swing detection, BOS, CHOCH, 4H regime.       |
//|                                                                  |
//| ARCHITECTURE: Layer 2 — Analysis.                               |
//| Consumes ONLY confirmed OHLCVBar[] from MTFDataFeed.            |
//| Never accesses MT5 market-data APIs directly.                   |
//|   • No CopyRates, iOpen, iHigh, iLow, iClose, iBarShift        |
//|   • No OrderSend, PositionOpen, OrderModify, PositionClose      |
//|   • No entry signal generation                                  |
//|   • No position sizing                                          |
//|   • No live market data access                                  |
//| Produces StructureResult per timeframe for later modules.       |
//|                                                                  |
//| SPECIFICATION SOURCES:                                          |
//|   Requirements 1.1–1.7 (Swing, BOS, CHOCH, confirmed candles)  |
//|   Requirements 3.1–3.8 (Regime classification)                 |
//|   design.md §2.3 Market_Structure_Analyzer                     |
//|   Correctness Properties 2, 3, 4                               |
//|                                                                  |
//| EXACT DEFINITIONS FROM SPECIFICATION:                           |
//|   Swing_High / Swing_Low:                                       |
//|     "A confirmed local price extremum identified using a        |
//|      minimum left/right candle look-back on closed candles      |
//|      only." (requirements.md Glossary)                         |
//|     Confirmed when SwingSideCandles candles on EACH side.       |
//|   Confirmation timestamp = bars[0].time (the time the Nth      |
//|     right-side candle closed, not the pivot's own time).        |
//|   BOS: (requirements.md Glossary + Req 1.4)                   |
//|     "A confirmed CLOSE beyond a prior confirmed Swing_High      |
//|      (bullish) or Swing_Low (bearish)."                        |
//|     CLOSE, not wick. Timeframe: 1H or higher.                  |
//|   CHOCH: (requirements.md Glossary + Req 1.5)                  |
//|     "A BOS that occurs in the direction opposite to the         |
//|      prevailing trend."                                        |
//|   Regime (4H only):                                             |
//|     Bullish = strictly HH and HL. (Req 3.2)                   |
//|     Bearish = strictly LH and LL. (Req 3.3)                   |
//|     Ranging = everything else, incl. insufficient swings.       |
//|                                                                  |
//| NO-REPAINTING / CONFIRMED-CANDLE GUARANTEE:                     |
//|   bars[0] = most recently CLOSED candle.                        |
//|   Bar index 0 (forming candle) is NEVER read.                   |
//|   All confirmed swings discovered in one Analyze() call share   |
//|   confirmation_time = bars[0].time, which is when we KNEW       |
//|   those swings existed. This is the canonical no-repainting     |
//|   timestamp. (Property 2)                                       |
//|   BOS: confirmation_time = bars[0].time of the candle whose    |
//|   CLOSE first crosses the prior swing level. (Property 4)       |
//|                                                                  |
//| ORDERING FIX (Bug 1 resolution):                                |
//|   For H4: Regime is classified BEFORE BOS/CHOCH detection.     |
//|   This ensures is_choch uses the correct current regime,        |
//|   not the RANGING default. All other timeframes are unaffected. |
//|                                                                  |
//| ATR/LIQUIDITY DEPENDENCIES:                                     |
//|   None. design §2.3 lists only MTFDataFeed and Logger.         |
//|                                                                  |
//| Design reference: §2.3 Market_Structure_Analyzer               |
//| Requirements: 1.1–1.7, 3.1–3.8                                 |
//| Correctness Properties: 2, 3, 4                                 |
//+------------------------------------------------------------------+
#pragma once
#include "../core/Types.mqh"
#include "../core/Constants.mqh"
#include "../utils/Logger.mqh"

//+------------------------------------------------------------------+
//| StructureStatus — availability of structure for a timeframe     |
//+------------------------------------------------------------------+
enum StructureStatus
{
    STRUCTURE_OK      = 0,  // Valid structure available
    STRUCTURE_UNKNOWN = 1   // Insufficient data / invalid input
};

//+------------------------------------------------------------------+
//| Regime — 4H-only market classification                          |
//| Requirements 3.1–3.4                                            |
//+------------------------------------------------------------------+
enum Regime
{
    REGIME_BULLISH = 0,  // Strictly HH and HL over last N swings
    REGIME_BEARISH = 1,  // Strictly LH and LL over last N swings
    REGIME_RANGING = 2   // All other cases, including insufficient swings
};

//+------------------------------------------------------------------+
//| BOSEvent — a single BOS or CHOCH occurrence                     |
//+------------------------------------------------------------------+
struct BOSEvent
{
    bool      valid;             // false = empty/unused
    Direction direction;         // LONG = bullish BOS/CHOCH; SHORT = bearish
    bool      is_choch;          // true if this BOS is also a CHOCH
    double    level;             // the swing level that was broken
    datetime  confirmation_time; // bars[0].time of the candle whose close crossed level
    double    confirmation_close;// bars[0].close that triggered the event
};

//+------------------------------------------------------------------+
//| StructureResult — output of one Analyze() call                  |
//| design §2.3: "StructureResult per timeframe containing..."      |
//+------------------------------------------------------------------+
struct StructureResult
{
    StructureStatus status;     // OK or UNKNOWN
    int             timeframe;  // PERIOD_H4, H1, M15, M5

    // Confirmed swing lists (newest-first, up to 20 each)
    SwingPoint swings_high[20]; // confirmed Swing_High points
    SwingPoint swings_low[20];  // confirmed Swing_Low points
    int        n_swings_high;
    int        n_swings_low;

    // Most recent structural events (valid=false when none)
    BOSEvent   last_bos;
    BOSEvent   last_choch;

    // Regime (populated only for PERIOD_H4; RANGING for other timeframes)
    Regime     regime;
};

//+------------------------------------------------------------------+
//| MarketStructureAnalyzer                                          |
//|                                                                  |
//| Stateless per Analyze() call.                                   |
//| m_last_h4_regime is the only persistent field, used solely for   |
//| regime-change logging (Req 3.7). It does not affect structural   |
//| output or timestamps.                                            |
//+------------------------------------------------------------------+
class MarketStructureAnalyzer
{
public:
    //------------------------------------------------------------------
    // Constructor
    //------------------------------------------------------------------
    MarketStructureAnalyzer()
    {
        m_swing_side_n   = 2;             // default SwingSideCandles (valid: 1–5)
        m_regime_swing_n = 4;             // default RegimeSwingCount (valid: 2–10)
        m_last_h4_regime = REGIME_RANGING; // Req 3.8: default Ranging until history confirms
        m_h4_regime_initialized = false;
    }

    //------------------------------------------------------------------
    // Configure — call once after construction, before first Analyze()
    //------------------------------------------------------------------
    void Configure(int swing_side_candles, int regime_swing_count)
    {
        m_swing_side_n   = swing_side_candles;   // valid range: 1–5
        m_regime_swing_n = regime_swing_count;    // valid range: 2–10
    }

    //------------------------------------------------------------------
    // Analyze
    // Compute swing structure, BOS, CHOCH, and Regime from a
    // confirmed-candle array for a single timeframe.
    //
    // Parameters:
    //   bars[]         - Confirmed OHLCVBar[], newest-first.
    //                    bars[0] = most recently CLOSED candle.
    //                    MUST NOT contain bar index 0 (forming candle).
    //                    Guaranteed by MTFDataFeed.GetBars().
    //   bars_available - Number of valid bars in bars[].
    //   timeframe      - PERIOD_H4, PERIOD_H1, PERIOD_M15, PERIOD_M5
    //
    // Returns StructureResult.
    //   status = UNKNOWN if bars < minimum lookback (Req 1.7).
    //   Regime populated only for timeframe == PERIOD_H4 (Req 3.1).
    //
    // NO-REPAINTING: All swing confirmation_time = bars[0].time.
    //   This is the timestamp of the most recently closed candle,
    //   i.e., the time the final right-side confirmation candle closed.
    //   BOS confirmation_time = bars[0].time of the crossing close.
    //
    // Correctness Properties 2 (swing side-count), 3 (regime), 4 (BOS).
    //
    // ORDERING (Bug 1 fix, 2026-09-11):
    //   For H4: regime is classified BEFORE BOS/CHOCH detection.
    //   For H1: BOS/CHOCH detected (regime check uses stored m_last_h4_regime).
    //------------------------------------------------------------------
    StructureResult Analyze(const OHLCVBar& bars[], int bars_available,
                            int timeframe)
    {
        StructureResult result = {};
        result.timeframe       = timeframe;
        result.status          = STRUCTURE_UNKNOWN;
        result.regime          = REGIME_RANGING;
        result.n_swings_high   = 0;
        result.n_swings_low    = 0;
        result.last_bos.valid  = false;
        result.last_choch.valid= false;

        // Req 1.7: minimum lookback = (2 × SwingSideCandles) + 1
        int min_bars = 2 * m_swing_side_n + 1;
        if(bars_available < min_bars)
        {
            Logger::Warn("MarketStructureAnalyzer", "INSUFFICIENT_HISTORY",
                StringFormat("tf=%d bars=%d required=%d",
                             timeframe, bars_available, min_bars));
            return result;  // status remains UNKNOWN
        }

        // Validate bar[0] (most recent confirmed candle)
        if(!IsValidBar(bars[0]))
        {
            Logger::Warn("MarketStructureAnalyzer", "INVALID_BAR0",
                StringFormat("tf=%d time=%s", timeframe,
                             TimeToString(bars[0].time)));
            return result;  // status remains UNKNOWN
        }

        // --- 1. Detect confirmed swing highs and swing lows ---
        //
        // Property 2: Every confirmed swing has ≥ SwingSideCandles closed
        // candles strictly before (left-side, older) AND strictly after
        // (right-side, newer) the pivot candle.
        //
        // Array layout (newest-first):
        //   bars[0]            = most recent closed candle (right edge)
        //   bars[pivot]        = pivot candidate
        //   bars[pivot+1..+N]  = left-side candles (older)
        //
        // Right-side: bars[0..m_swing_side_n-1] must all be < pivot.high
        //             (for a swing high) or > pivot.low (for a swing low).
        // Left-side:  bars[pivot+1..pivot+m_swing_side_n] must satisfy same.
        //
        // scan_limit: the oldest pivot we can still confirm.
        //   We need left-side candles at pivot+1 .. pivot+m_swing_side_n,
        //   so max pivot = bars_available - m_swing_side_n - 1.
        //
        // NO-REPAINTING: all swings found in this Analyze() call share
        //   confirmation_time = bars[0].time.
        //   This is the time we are running the scan — the moment these
        //   swings become knowable. (Spec §2.3, Property 2.)
        //
        // STATIC LOOK-AHEAD SCAN: no future bar is ever accessed.
        //   Right-side index range: 0 .. m_swing_side_n-1 (recent bars)
        //   Left-side index range: pivot+1 .. pivot+m_swing_side_n (older bars)
        //   All indices are < bars_available. No future access possible.

        // D-1 FIX (2026-09-12): Swing confirmation timestamp.
        // Each swing's confirmation_time = bars[m_swing_side_n-1].time.
        // This is the time the LAST REQUIRED right-side candle closed —
        // the earliest moment the swing was knowable in a live system.
        // For swing_n>=2: bars[m_swing_side_n-1].time < bars[0].time
        // (bars are newest-first, so older bars have earlier timestamps).
        // This makes the BOS guard (swing.time < confirm_time) work correctly
        // within a single stateless Analyze() call.
        //
        // The BOS anchor (confirm_time) remains bars[0].time — the time
        // of the crossing candle. Swings get their own distinct timestamps.
        datetime confirm_time    = bars[0].time;     // BOS/CHOCH anchor
        datetime right_edge_time = bars[m_swing_side_n-1].time; // D-1 swing anchor

        // --- 1. Detect confirmed swing highs and swing lows ---
        //
        // Property 2: Every confirmed swing has >= SwingSideCandles closed
        // candles strictly before (left-side, older) AND strictly after
        // (right-side, newer) the pivot candle.
        //
        // Array layout (newest-first):
        //   bars[0]            = most recent closed candle (right edge)
        //   bars[pivot]        = pivot candidate
        //   bars[pivot+1..+N]  = left-side candles (older)
        //
        // Right-side: bars[0..m_swing_side_n-1] must all be < pivot.high
        //             (for a swing high) or > pivot.low (for a swing low).
        // Left-side:  bars[pivot+1..pivot+m_swing_side_n] must satisfy same.
        //
        // scan_limit: the oldest pivot we can still confirm.
        //   We need left-side candles at pivot+1 .. pivot+m_swing_side_n,
        //   so max pivot = bars_available - m_swing_side_n - 1.
        //
        // D-1 FIX: all swings get time = right_edge_time (bars[swing_n-1].time),
        //   not bars[0].time. This is guaranteed < bars[0].time = confirm_time
        //   for swing_n >= 2, enabling the BOS prior-swing filter to work.
        //
        // STATIC LOOK-AHEAD SCAN: no future bar is ever accessed.
        //   Right-side index range: 0 .. m_swing_side_n-1 (recent bars)
        //   Left-side index range: pivot+1 .. pivot+m_swing_side_n (older bars)
        //   All indices are < bars_available. No future access possible.

        int      scan_limit  = bars_available - m_swing_side_n - 1;

        for(int pivot = m_swing_side_n; pivot <= scan_limit; pivot++)
        {
            if(!IsValidBar(bars[pivot])) continue;

            double ph = bars[pivot].high;
            double pl = bars[pivot].low;

            // Right-side check: bars[0..m_swing_side_n-1] all strictly < ph (high)
            //                   bars[0..m_swing_side_n-1] all strictly > pl (low)
            bool h_right = true, l_right = true;
            for(int r = 0; r < m_swing_side_n && (h_right || l_right); r++)
            {
                if(!IsValidBar(bars[r])) { h_right = false; l_right = false; break; }
                if(bars[r].high >= ph) h_right = false;
                if(bars[r].low  <= pl) l_right = false;
            }

            // Left-side check: bars[pivot+1..pivot+m_swing_side_n] strictly < ph / > pl
            bool h_left = true, l_left = true;
            for(int l = pivot + 1; l <= pivot + m_swing_side_n; l++)
            {
                if(l >= bars_available || !IsValidBar(bars[l]))
                { h_left = false; l_left = false; break; }
                if(bars[l].high >= ph) h_left = false;
                if(bars[l].low  <= pl) l_left = false;
            }

            // Register confirmed swing high
            if(h_right && h_left && result.n_swings_high < 20)
            {
                int idx = result.n_swings_high++;
                result.swings_high[idx].time      = right_edge_time; // D-1 FIX
                result.swings_high[idx].price     = ph;
                result.swings_high[idx].type      = SWING_HIGH;
                result.swings_high[idx].timeframe = timeframe;
                result.swings_high[idx].confirmed = true;
            }

            // Register confirmed swing low
            if(l_right && l_left && result.n_swings_low < 20)
            {
                int idx = result.n_swings_low++;
                result.swings_low[idx].time      = right_edge_time; // D-1 FIX
                result.swings_low[idx].price     = pl;
                result.swings_low[idx].type      = SWING_LOW;
                result.swings_low[idx].timeframe = timeframe;
                result.swings_low[idx].confirmed = true;
            }
        }


        // --- 2. Regime classification (4H only) — MUST come before BOS ---
        //
        // BUG-1 FIX: Regime is classified BEFORE BOS/CHOCH detection.
        // When DetectBOS() checks "is_choch", result.regime must already
        // reflect the current confirmed swing sequence, not the default RANGING.
        //
        // Req 3.1–3.4, Property 3.
        if(timeframe == PERIOD_H4)
        {
            Regime new_regime = ClassifyRegime(result);
            result.regime = new_regime;

            // Req 3.7: log regime changes with previous, new, and trigger timestamp.
            if(m_h4_regime_initialized && new_regime != m_last_h4_regime)
            {
                Logger::Info("MarketStructureAnalyzer", "REGIME_CHANGE",
                    StringFormat("prev=%s new=%s trigger_ts=%s",
                        RegimeName(m_last_h4_regime),
                        RegimeName(new_regime),
                        TimeToString(confirm_time)));
            }
            else if(!m_h4_regime_initialized)
            {
                // Req 3.8: first regime set at init — log it
                Logger::Info("MarketStructureAnalyzer", "REGIME_INIT",
                    StringFormat("regime=%s ts=%s",
                        RegimeName(new_regime),
                        TimeToString(confirm_time)));
                m_h4_regime_initialized = true;
            }
            m_last_h4_regime = new_regime;
        }

        // --- 3. BOS and CHOCH detection (1H and higher; Req 1.4) ---
        //
        // "WHEN a confirmed candle closes beyond a prior confirmed
        //  Swing_High or Swing_Low on the 1H or higher timeframe."
        // BOS uses close (not wick) per specification.
        //
        // D-2 FIX (2026-09-12): H1 CHOCH uses the stored H4 regime.
        // Req 1.5: "a BOS that occurs in the direction opposite to the
        //  current Regime." The Regime is 4H-only (Req 1.3, 3.1).
        // For H4: result.regime is already set by ClassifyRegime() above.
        // For H1: we temporarily set result.regime = m_last_h4_regime so
        //   DetectBOS() applies the correct CHOCH condition.
        //   After DetectBOS(), result.regime is reset to RANGING because
        //   H1 StructureResult.regime is meaningless per Req 3.1.
        //
        // This ensures is_choch on H1 is correctly true when a bullish H1
        // BOS occurs while the 4H regime is Bearish (and vice versa).
        if(timeframe == PERIOD_H1 || timeframe == PERIOD_H4)
        {
            if(timeframe == PERIOD_H1)
                result.regime = m_last_h4_regime;   // D-2: use stored H4 regime for CHOCH

            DetectBOS(bars, bars_available, confirm_time, result);

            if(timeframe == PERIOD_H1)
                result.regime = REGIME_RANGING;      // D-2: reset — H1 has no regime
        }

        result.status = STRUCTURE_OK;
        return result;
    }


    //------------------------------------------------------------------
    // Reset — call on reinitialization (e.g., strategy restart)
    //------------------------------------------------------------------
    void Reset()
    {
        m_last_h4_regime        = REGIME_RANGING;
        m_h4_regime_initialized = false;
        Logger::Info("MarketStructureAnalyzer", "RESET", "structure_state_cleared");
    }

private:
    int    m_swing_side_n;
    int    m_regime_swing_n;
    Regime m_last_h4_regime;        // for regime-change logging only (Req 3.7)
    bool   m_h4_regime_initialized; // true after first successful H4 Analyze()

    //------------------------------------------------------------------
    // IsValidBar — basic OHLCV sanity guard
    // Handles: zero time, invalid OHLC, non-finite values.
    //------------------------------------------------------------------
    static bool IsValidBar(const OHLCVBar& bar)
    {
        if(bar.time == 0)             return false;
        if(bar.high < bar.low)        return false;
        if(bar.close <= 0.0)          return false;
        if(bar.open  <= 0.0)          return false;
        if(!MathIsValidNumber(bar.high))  return false;
        if(!MathIsValidNumber(bar.low))   return false;
        if(!MathIsValidNumber(bar.close)) return false;
        if(!MathIsValidNumber(bar.open))  return false;
        return true;
    }

    //------------------------------------------------------------------
    // RegimeName — string label for logging
    //------------------------------------------------------------------
    static string RegimeName(Regime r)
    {
        switch(r)
        {
            case REGIME_BULLISH: return "BULLISH";
            case REGIME_BEARISH: return "BEARISH";
            default:             return "RANGING";
        }
    }

    //------------------------------------------------------------------
    // DetectBOS
    //
    // Req 1.4: "WHEN a confirmed candle closes beyond a prior confirmed
    //           Swing_High or Swing_Low on the 1H or higher timeframe."
    // BOS = CLOSE (not wick) beyond the most recent prior swing level.
    // CHOCH = BOS in direction opposite to result.regime (Req 1.5).
    //
    // IMPORTANT: result.regime must already be set before this call.
    //   For H4: ClassifyRegime() is called first (Bug-1 fix).
    //   For H1: result.regime is RANGING (H1 has no standalone regime).
    //
    // Confirmation time = bars[0].time.
    // Duplicate guard: (direction, confirmation_time, level) triple.
    // Property 4: BOS fires at exactly the bar whose close crosses level.
    //
    // NO-LOOK-AHEAD PROOF:
    //   bars[0].close is the most recently CLOSED candle's close.
    //   We compare it against prior swing levels whose confirmation_time
    //   < bars[0].time, so all prior data. No future bar is read.
    //------------------------------------------------------------------
    void DetectBOS(const OHLCVBar& bars[], int bars_available,
                   datetime confirm_time, StructureResult& result)
    {
        if(!IsValidBar(bars[0])) return;
        double c = bars[0].close;

        // ---- Bullish BOS: bars[0].close ABOVE most recent prior Swing_High ----
        // "Most recent prior": swing with confirmation_time < current confirm_time.
        // We take the first entry in swings_high[] with time < confirm_time.
        double   prior_high      = 0.0;
        datetime prior_high_time = 0;
        for(int i = 0; i < result.n_swings_high; i++)
        {
            if(result.swings_high[i].time < confirm_time)
            {
                prior_high      = result.swings_high[i].price;
                prior_high_time = result.swings_high[i].time;
                break;  // most recent prior swing high
            }
        }

        if(prior_high > 0.0 && c > prior_high)
        {
            // Duplicate prevention: reject if same direction+time+level already recorded
            bool is_dup = result.last_bos.valid &&
                          result.last_bos.direction == DIRECTION_LONG &&
                          result.last_bos.confirmation_time == confirm_time &&
                          MathAbs(result.last_bos.level - prior_high) < 1e-10;

            if(!is_dup)
            {
                bool is_choch = (result.regime == REGIME_BEARISH);
                result.last_bos.valid             = true;
                result.last_bos.direction         = DIRECTION_LONG;
                result.last_bos.level             = prior_high;
                result.last_bos.confirmation_time = confirm_time;
                result.last_bos.confirmation_close= c;
                result.last_bos.is_choch          = is_choch;

                if(is_choch)
                {
                    result.last_choch = result.last_bos;
                    Logger::Info("MarketStructureAnalyzer", "CHOCH_BULLISH",
                        StringFormat("tf=%d level=%.5f close=%.5f ts=%s",
                            result.timeframe, prior_high, c,
                            TimeToString(confirm_time)));
                }
                else
                {
                    Logger::Info("MarketStructureAnalyzer", "BOS_BULLISH",
                        StringFormat("tf=%d level=%.5f close=%.5f ts=%s",
                            result.timeframe, prior_high, c,
                            TimeToString(confirm_time)));
                }
            }
        }

        // ---- Bearish BOS: bars[0].close BELOW most recent prior Swing_Low ----
        double   prior_low      = 0.0;
        datetime prior_low_time = 0;
        for(int i = 0; i < result.n_swings_low; i++)
        {
            if(result.swings_low[i].time < confirm_time)
            {
                prior_low      = result.swings_low[i].price;
                prior_low_time = result.swings_low[i].time;
                break;
            }
        }

        if(prior_low > 0.0 && c < prior_low)
        {
            bool is_dup = result.last_bos.valid &&
                          result.last_bos.direction == DIRECTION_SHORT &&
                          result.last_bos.confirmation_time == confirm_time &&
                          MathAbs(result.last_bos.level - prior_low) < 1e-10;

            if(!is_dup)
            {
                bool is_choch = (result.regime == REGIME_BULLISH);
                result.last_bos.valid             = true;
                result.last_bos.direction         = DIRECTION_SHORT;
                result.last_bos.level             = prior_low;
                result.last_bos.confirmation_time = confirm_time;
                result.last_bos.confirmation_close= c;
                result.last_bos.is_choch          = is_choch;

                if(is_choch)
                {
                    result.last_choch = result.last_bos;
                    Logger::Info("MarketStructureAnalyzer", "CHOCH_BEARISH",
                        StringFormat("tf=%d level=%.5f close=%.5f ts=%s",
                            result.timeframe, prior_low, c,
                            TimeToString(confirm_time)));
                }
                else
                {
                    Logger::Info("MarketStructureAnalyzer", "BOS_BEARISH",
                        StringFormat("tf=%d level=%.5f close=%.5f ts=%s",
                            result.timeframe, prior_low, c,
                            TimeToString(confirm_time)));
                }
            }
        }
    }

    //------------------------------------------------------------------
    // ClassifyRegime (4H only)
    //
    // Requirements 3.1–3.4, Correctness Property 3.
    //
    // Bullish: all N most recent alternating swing highs form strictly
    //          increasing sequence AND all swing lows form strictly
    //          increasing sequence (HH + HL).
    // Bearish: all N most recent swing highs form strictly decreasing
    //          sequence AND all swing lows form strictly decreasing
    //          sequence (LH + LL).
    // Ranging: everything else, including insufficient history.
    //
    // "alternating confirmed Swing_High and Swing_Low points" (Req 3.1):
    //   We take the most recent min(m_regime_swing_n/2 + 1, available)
    //   highs and lows separately and check strict monotonicity.
    //   This mirrors the spec's intent: "all N configured swing points".
    //
    // swings_high[0] = most recently confirmed (newest), so [0]>[1]>[2]
    // means the sequence is getting LOWER over time (LH), while
    // [0]<[1] means getting HIGHER... wait:
    //   swings_high[0] = newest, swings_high[1] = older.
    //   HH means each newer high is higher than the older one.
    //   So HH: swings_high[0] > swings_high[1] > ... (newest > oldest).
    //   LH: swings_high[0] < swings_high[1] < ... (newest < oldest).
    //------------------------------------------------------------------
    Regime ClassifyRegime(const StructureResult& result)
    {
        // Req 3.4/3.8: insufficient swings → Ranging
        if(result.n_swings_high < 2 || result.n_swings_low < 2)
            return REGIME_RANGING;

        // Take min(m_regime_swing_n/2 + 1, available) — enough for comparisons
        int n_h = MathMin(result.n_swings_high, m_regime_swing_n / 2 + 1);
        int n_l = MathMin(result.n_swings_low,  m_regime_swing_n / 2 + 1);
        if(n_h < 2 || n_l < 2) return REGIME_RANGING;

        // Higher Highs: swings_high[0] > swings_high[1] > ... (newest > older)
        bool all_hh = true;
        bool all_lh = true;
        for(int i = 0; i < n_h - 1; i++)
        {
            if(result.swings_high[i].price <= result.swings_high[i+1].price)
                all_hh = false;   // Not strictly higher
            if(result.swings_high[i].price >= result.swings_high[i+1].price)
                all_lh = false;   // Not strictly lower
        }

        // Higher Lows / Lower Lows
        bool all_hl = true;
        bool all_ll = true;
        for(int i = 0; i < n_l - 1; i++)
        {
            if(result.swings_low[i].price <= result.swings_low[i+1].price)
                all_hl = false;
            if(result.swings_low[i].price >= result.swings_low[i+1].price)
                all_ll = false;
        }

        if(all_hh && all_hl) return REGIME_BULLISH;
        if(all_lh && all_ll) return REGIME_BEARISH;
        return REGIME_RANGING;
    }
};
//+------------------------------------------------------------------+
