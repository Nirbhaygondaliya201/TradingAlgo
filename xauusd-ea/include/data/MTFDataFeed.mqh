//+------------------------------------------------------------------+
//| MTFDataFeed.mqh                                                  |
//| XAU/USD MT5 Expert Advisor                                       |
//| Multi-timeframe confirmed-candle data feed.                      |
//|                                                                  |
//| ARCHITECTURE: Layer 1 — Data Acquisition.                        |
//| This module is the ONLY data-access boundary between the MT5    |
//| time-series API and the Analysis layer. Analysis modules must   |
//| never call CopyRates, CopyTime, or iOpen/iHigh/iLow/iClose     |
//| directly. All OHLCV access goes through MTFDataFeed::GetBars(). |
//|                                                                  |
//| Confirmed-candle guarantee (Correctness Property 1):            |
//|   - GetBars() ALWAYS starts at MT5 bar index 1.                 |
//|   - MT5 bar index 0 (the currently forming candle) is NEVER     |
//|     included in the returned array.                             |
//|   - Array[0] of the returned array = MT5 bar index 1.          |
//|     (The most recently closed candle.)                          |
//|                                                                  |
//| No caching: every GetBars() call fetches fresh from MT5.        |
//| Series synchronisation is checked before every fetch.           |
//| New-candle detection: callers compare OHLCVBar[0].time with    |
//| the last-seen confirmed candle time per timeframe.              |
//|                                                                  |
//| Supported timeframes: PERIOD_H4, PERIOD_H1, PERIOD_M15, PERIOD_M5|
//|                                                                  |
//| Design reference: §2.2 MultiTimeframe_DataFeed                  |
//| Requirements: 1.1, 1.6, 4.5, 15.5                              |
//| Correctness Property: 1                                          |
//+------------------------------------------------------------------+
#pragma once
#include "../core/Types.mqh"
#include "../core/Constants.mqh"
#include "../utils/Logger.mqh"

//+------------------------------------------------------------------+
//| DataFeedResult                                                   |
//| Returned by GetBars(). Callers MUST check BarsAvailable > 0    |
//| before reading the bars array.                                  |
//+------------------------------------------------------------------+
struct DataFeedResult
{
    OHLCVBar bars[];      // Confirmed bars, bars[0] = MT5 bar index 1
    int      BarsAvailable; // Actual number of bars returned (0 = no data)
    bool     IsNewCandle;   // True if bars[0].time changed since last call
    bool     IsSynchronised;// True if MT5 series is synchronised
    string   ErrorReason;   // Populated if BarsAvailable == 0
};

//+------------------------------------------------------------------+
//| MTFDataFeed                                                      |
//| All methods are static (no instantiation needed).               |
//+------------------------------------------------------------------+
class MTFDataFeed
{
public:
    //------------------------------------------------------------------
    // GetBars
    // Retrieve up to `count` confirmed candles for the given timeframe.
    //
    // Parameters:
    //   symbol    - Symbol name (e.g., "XAUUSD")
    //   timeframe - One of TF_4H, TF_1H, TF_15M, TF_5M
    //   count     - Maximum number of confirmed bars to return
    //
    // Returns a DataFeedResult where:
    //   - result.bars[0] = MT5 bar index 1 (most recently closed candle)
    //   - result.bars[count-1] = oldest requested candle
    //   - MT5 bar index 0 (forming candle) is NEVER present
    //   - BarsAvailable may be less than count if history is short
    //   - BarsAvailable = 0 if series is unsynchronised or fetch fails
    //
    // Correctness Property 1: no analysis module can ever receive bar[0].
    //------------------------------------------------------------------
    static DataFeedResult GetBars(const string symbol, int timeframe, int count)
    {
        DataFeedResult result;
        result.BarsAvailable  = 0;
        result.IsNewCandle    = false;
        result.IsSynchronised = false;
        result.ErrorReason    = "";
        ArrayResize(result.bars, 0);

        if(count <= 0)
        {
            result.ErrorReason = "count must be > 0";
            Logger::Warn("MTFDataFeed", "INVALID_COUNT",
                StringFormat("symbol=%s tf=%d count=%d", symbol, timeframe, count));
            return result;
        }

        // ---- 1. Check series synchronisation --------------------------
        // Requirement: if series is not yet synchronised, return 0 bars.
        // Design §2.2 edge case.
        bool is_sync = (bool)SeriesInfoInteger(symbol, (ENUM_TIMEFRAMES)timeframe,
                                               SERIES_SYNCHRONIZED);
        result.IsSynchronised = is_sync;
        if(!is_sync)
        {
            result.ErrorReason = "SERIES_NOT_SYNCHRONIZED";
            Logger::Debug("MTFDataFeed", "NOT_SYNCHRONIZED",
                StringFormat("symbol=%s tf=%d", symbol, timeframe));
            return result;
        }

        // ---- 2. Fetch confirmed bars starting at bar index 1 ----------
        // We request `count` bars starting from shift=1 (bar index 1).
        // Bar index 0 is NEVER requested. This is the core confirmed-candle
        // enforcement. Correctness Property 1.
        MqlRates rates[];
        int fetched = CopyRates(symbol, (ENUM_TIMEFRAMES)timeframe, 1, count, rates);

        if(fetched <= 0)
        {
            result.ErrorReason = "COPYRATES_FAILED_OR_NO_DATA";
            Logger::Warn("MTFDataFeed", "FETCH_FAILED",
                StringFormat("symbol=%s tf=%d count=%d fetched=%d err=%d",
                             symbol, timeframe, count, fetched, GetLastError()));
            return result;
        }

        // ---- 3. Validate returned data --------------------------------
        // CopyRates returns bars newest-first (rates[0] = bar index 1).
        ArrayResize(result.bars, fetched);

        for(int i = 0; i < fetched; i++)
        {
            // Basic OHLC sanity: skip completely zero bars (broker artefacts)
            if(rates[i].time == 0)
            {
                // Truncate at first zero-time bar
                ArrayResize(result.bars, i);
                fetched = i;
                Logger::Warn("MTFDataFeed", "ZERO_TIME_BAR",
                    StringFormat("symbol=%s tf=%d at_index=%d",
                                 symbol, timeframe, i));
                break;
            }

            // High must be >= Low and >= Open and >= Close
            if(rates[i].high < rates[i].low ||
               rates[i].high < rates[i].open ||
               rates[i].high < rates[i].close)
            {
                Logger::Warn("MTFDataFeed", "INVALID_OHLC",
                    StringFormat("symbol=%s tf=%d idx=%d "
                                 "O=%.5f H=%.5f L=%.5f C=%.5f",
                                 symbol, timeframe, i,
                                 rates[i].open, rates[i].high,
                                 rates[i].low, rates[i].close));
                // Do not include invalid bars — truncate
                ArrayResize(result.bars, i);
                fetched = i;
                break;
            }

            // Low must be <= Open and <= Close
            if(rates[i].low > rates[i].open || rates[i].low > rates[i].close)
            {
                Logger::Warn("MTFDataFeed", "INVALID_OHLC",
                    StringFormat("symbol=%s tf=%d idx=%d low=%.5f > open=%.5f or close=%.5f",
                                 symbol, timeframe, i,
                                 rates[i].low, rates[i].open, rates[i].close));
                ArrayResize(result.bars, i);
                fetched = i;
                break;
            }

            // Timestamps must be strictly increasing from older to newer.
            // CopyRates returns newest-first, so rates[i].time must be >
            // rates[i+1].time for all i < fetched-1.
            if(i > 0 && rates[i].time >= rates[i-1].time)
            {
                Logger::Warn("MTFDataFeed", "TIMESTAMP_ORDER_ERROR",
                    StringFormat("symbol=%s tf=%d idx=%d t[i]=%s t[i-1]=%s",
                                 symbol, timeframe, i,
                                 TimeToString(rates[i].time),
                                 TimeToString(rates[i-1].time)));
                // Truncate at the disorder point
                ArrayResize(result.bars, i);
                fetched = i;
                break;
            }

            // Populate OHLCVBar
            result.bars[i].time        = rates[i].time;
            result.bars[i].open        = rates[i].open;
            result.bars[i].high        = rates[i].high;
            result.bars[i].low         = rates[i].low;
            result.bars[i].close       = rates[i].close;
            result.bars[i].tick_volume = rates[i].tick_volume;
        }

        result.BarsAvailable = fetched;

        // ---- 4. New-candle detection ----------------------------------
        // Compare bars[0].time against the stored last-seen time.
        // Callers should store and update the last-seen time themselves.
        // IsNewCandle is set based on the stored per-timeframe state below.
        if(fetched > 0)
        {
            datetime last = GetLastBarTime(timeframe);
            result.IsNewCandle = (result.bars[0].time != last);
        }

        return result;
    }

    //------------------------------------------------------------------
    // UpdateLastBarTime
    // Call after consuming a DataFeedResult where IsNewCandle is true.
    // Stores bars[0].time as the new reference for new-candle detection.
    //------------------------------------------------------------------
    static void UpdateLastBarTime(int timeframe, datetime new_time)
    {
        switch(timeframe)
        {
            case PERIOD_H4:  s_last_H4  = new_time; break;
            case PERIOD_H1:  s_last_H1  = new_time; break;
            case PERIOD_M15: s_last_M15 = new_time; break;
            case PERIOD_M5:  s_last_M5  = new_time; break;
            default:
                Logger::Warn("MTFDataFeed", "UNKNOWN_TIMEFRAME",
                    StringFormat("tf=%d", timeframe));
        }
    }

    //------------------------------------------------------------------
    // GetLastBarTime
    // Returns the last-seen confirmed bar time for the given timeframe.
    // Returns 0 if no bar has been seen yet (EA just started).
    //------------------------------------------------------------------
    static datetime GetLastBarTime(int timeframe)
    {
        switch(timeframe)
        {
            case PERIOD_H4:  return s_last_H4;
            case PERIOD_H1:  return s_last_H1;
            case PERIOD_M15: return s_last_M15;
            case PERIOD_M5:  return s_last_M5;
            default:         return 0;
        }
    }

    //------------------------------------------------------------------
    // ResetLastBarTimes
    // Clear all stored last-bar-time values.
    // Call during OnInit to handle EA restart correctly.
    //------------------------------------------------------------------
    static void ResetLastBarTimes()
    {
        s_last_H4  = 0;
        s_last_H1  = 0;
        s_last_M15 = 0;
        s_last_M5  = 0;
        Logger::Debug("MTFDataFeed", "RESET", "last_bar_times_cleared");
    }

    //------------------------------------------------------------------
    // IsTimeframeSupported
    // Returns true if the timeframe is one of the four EA timeframes.
    //------------------------------------------------------------------
    static bool IsTimeframeSupported(int timeframe)
    {
        return (timeframe == PERIOD_H4  ||
                timeframe == PERIOD_H1  ||
                timeframe == PERIOD_M15 ||
                timeframe == PERIOD_M5);
    }

private:
    // Per-timeframe last-seen confirmed bar timestamps.
    // Used for new-candle detection. Initialised to 0 (never seen).
    static datetime s_last_H4;
    static datetime s_last_H1;
    static datetime s_last_M15;
    static datetime s_last_M5;
};

//+------------------------------------------------------------------+
//| Static member definitions                                        |
//+------------------------------------------------------------------+
datetime MTFDataFeed::s_last_H4  = 0;
datetime MTFDataFeed::s_last_H1  = 0;
datetime MTFDataFeed::s_last_M15 = 0;
datetime MTFDataFeed::s_last_M5  = 0;
//+------------------------------------------------------------------+
