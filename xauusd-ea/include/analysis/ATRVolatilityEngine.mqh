//+------------------------------------------------------------------+
//| ATRVolatilityEngine.mqh                                          |
//| XAU/USD MT5 Expert Advisor                                       |
//| ATR volatility analysis — confirmed candles only.               |
//|                                                                  |
//| ARCHITECTURE: Layer 2 — Analysis.                               |
//| Consumes ONLY confirmed 1H OHLCVBar[] from MTFDataFeed.         |
//| Never accesses MT5 market data APIs directly.                   |
//| Produces ATRResult for the Entry_Confirmation_Engine and         |
//| Risk_Manager.                                                    |
//|                                                                  |
//| ATR METHODOLOGY (Wilder's smoothing / RMA):                     |
//|   True Range for bar i:                                         |
//|     TR(i) = max(High(i) - Low(i),                               |
//|                 |High(i) - Close(i-1)|,                          |
//|                 |Low(i)  - Close(i-1)|)                          |
//|   Seed (first ATR):                                             |
//|     ATR_0 = simple average of first ATRPeriod TR values         |
//|   Subsequent bars (Wilder's RMA):                               |
//|     ATR_n = (ATR_{n-1} × (period-1) + TR_n) / period           |
//|                                                                  |
//| CONFIRMED-CANDLE GUARANTEE:                                     |
//|   All bars used in calculation are confirmed bars from          |
//|   MTFDataFeed (bar index ≥ 1). Bar index 0 is NEVER used.      |
//|   Correctness Property 1 / Property 10 / Property 11.          |
//|                                                                  |
//| Design reference: §2.5 ATR_Volatility_Engine                   |
//| Requirements: 5.1–5.6, 14.4                                     |
//| Correctness Properties: 1, 10, 11                               |
//+------------------------------------------------------------------+
#pragma once
#include "../core/Types.mqh"
#include "../core/Constants.mqh"
#include "../utils/Logger.mqh"

//+------------------------------------------------------------------+
//| ATRVolatilityEngine                                              |
//| All methods are static — no instantiation needed.               |
//+------------------------------------------------------------------+
class ATRVolatilityEngine
{
public:
    //------------------------------------------------------------------
    // Calculate
    // Compute ATR and filter status from a confirmed 1H candle array.
    //
    // Parameters:
    //   bars[]          - Confirmed 1H OHLCVBar array from MTFDataFeed.
    //                     bars[0] = most recently closed candle.
    //                     bars[n-1] = oldest candle.
    //                     MUST NOT contain bar index 0 (forming candle).
    //   bars_available  - Number of valid bars in bars[].
    //   atr_period      - ATR lookback period (valid range: 5–50, default: 14)
    //   atr_min_mult    - Block if ATR < baseline × this (default: 0.5)
    //   atr_max_mult    - Block if ATR > baseline × this (default: 2.5)
    //   atr_sl_mult     - Min SL = ATR × this (default: 1.5)
    //   stop_level_pts  - Broker minimum stop level in points (from SymbolProperties)
    //   point_size      - Symbol point size (from SymbolProperties)
    //   baseline_window - Number of bars for baseline average (default: 720)
    //
    // Returns ATRResult with all fields populated.
    //
    // Correctness Properties 1, 10, 11.
    //------------------------------------------------------------------
    static ATRResult Calculate(
        const OHLCVBar& bars[],
        int             bars_available,
        int             atr_period,
        double          atr_min_mult,
        double          atr_max_mult,
        double          atr_sl_mult,
        int             stop_level_pts,
        double          point_size,
        int             baseline_window = ATR_BASELINE_WINDOW_BARS
    )
    {
        ATRResult result = {};
        result.status           = ATR_UNAVAILABLE;
        result.current_atr      = 0.0;
        result.baseline_atr     = 0.0;
        result.min_sl_distance  = 0.0;

        // --- Input validation ---
        if(atr_period < 5 || atr_period > 50)
        {
            Logger::Error("ATRVolatilityEngine", "INVALID_ATR_PERIOD",
                StringFormat("atr_period=%d valid_range=5-50", atr_period));
            return result;
        }
        if(bars_available <= 0)
        {
            Logger::Warn("ATRVolatilityEngine", "NO_BARS",
                "bars_available=0");
            return result;
        }

        // Require at least atr_period + 1 bars to compute TR for the first
        // ATR seed (we need bars[0].close through bars[period].close for
        // period TR values; each TR needs the previous close).
        int required = atr_period + 1;
        if(bars_available < required)
        {
            Logger::Warn("ATRVolatilityEngine", "INSUFFICIENT_HISTORY",
                StringFormat("bars_available=%d required=%d atr_period=%d",
                             bars_available, required, atr_period));
            return result;
        }

        // --- Compute True Range for all bars ---
        // bars[] is newest-first: bars[0] is the most recently closed bar.
        // TR(i) uses bars[i] (current) and bars[i+1] (previous close).
        // We can compute TR for bars[0] through bars[bars_available-2].
        int tr_count = bars_available - 1; // Need prev close for first bar

        double tr_values[];
        ArrayResize(tr_values, tr_count);

        for(int i = 0; i < tr_count; i++)
        {
            // Basic OHLC sanity
            if(bars[i].high < bars[i].low || bars[i].close <= 0 ||
               bars[i].open <= 0 || bars[i+1].close <= 0)
            {
                Logger::Warn("ATRVolatilityEngine", "INVALID_OHLC",
                    StringFormat("bar_idx=%d H=%.5f L=%.5f C=%.5f PrevC=%.5f",
                                 i, bars[i].high, bars[i].low,
                                 bars[i].close, bars[i+1].close));
                return result;
            }

            double hl = bars[i].high - bars[i].low;
            double hpc = MathAbs(bars[i].high - bars[i+1].close);
            double lpc = MathAbs(bars[i].low  - bars[i+1].close);
            tr_values[i] = MathMax(hl, MathMax(hpc, lpc));
        }

        // Check we have enough TR values for the seed
        if(tr_count < atr_period)
        {
            Logger::Warn("ATRVolatilityEngine", "INSUFFICIENT_TR",
                StringFormat("tr_count=%d atr_period=%d", tr_count, atr_period));
            return result;
        }

        // --- Seed ATR: simple mean of the oldest atr_period TR values ---
        // TR is computed from bars[0..tr_count-1] (newest-first).
        // We need the atr_period oldest TR values, which are at the END.
        double seed_sum = 0.0;
        for(int i = tr_count - atr_period; i < tr_count; i++)
            seed_sum += tr_values[i];
        double atr_val = seed_sum / atr_period;

        if(atr_val <= 0.0)
        {
            Logger::Warn("ATRVolatilityEngine", "ZERO_SEED_ATR",
                StringFormat("seed_sum=%.10f atr_period=%d", seed_sum, atr_period));
            return result;
        }

        // --- Wilder's RMA: apply from (tr_count - atr_period - 1) down to 0 ---
        // We walk from older bars toward newer bars.
        // After seeding at the oldest atr_period TRs, we smooth each
        // subsequent (newer) TR in chronological order.
        for(int i = tr_count - atr_period - 1; i >= 0; i--)
        {
            atr_val = ((atr_val * (atr_period - 1)) + tr_values[i]) / atr_period;
        }

        if(atr_val <= 0.0 || !MathIsValidNumber(atr_val))
        {
            Logger::Error("ATRVolatilityEngine", "INVALID_ATR_RESULT",
                StringFormat("atr_val=%.10f", atr_val));
            return result;
        }

        result.current_atr = atr_val;

        // --- Baseline ATR: simple average of up to baseline_window TR values ---
        // Use as many TR values as available, minimum atr_period bars.
        int baseline_count = MathMin(tr_count, baseline_window);
        if(baseline_count < ATR_BASELINE_MIN_BARS)
        {
            // Not enough for a reliable baseline — still proceed with what we have
            Logger::Warn("ATRVolatilityEngine", "SHORT_BASELINE",
                StringFormat("baseline_count=%d min=%d",
                             baseline_count, ATR_BASELINE_MIN_BARS));
        }
        double baseline_sum = 0.0;
        for(int i = 0; i < baseline_count; i++)
            baseline_sum += tr_values[i];
        result.baseline_atr = baseline_sum / baseline_count;

        if(result.baseline_atr <= 0.0 || !MathIsValidNumber(result.baseline_atr))
        {
            Logger::Error("ATRVolatilityEngine", "INVALID_BASELINE",
                StringFormat("baseline=%.10f", result.baseline_atr));
            return result;
        }

        // --- Filter status ---
        // Requirements 5.2 / 5.3: boundary is inclusive (equal = ALLOW)
        if(result.current_atr < result.baseline_atr * atr_min_mult)
            result.status = ATR_BLOCK_LOW;
        else if(result.current_atr > result.baseline_atr * atr_max_mult)
            result.status = ATR_BLOCK_HIGH;
        else
            result.status = ATR_ALLOW;

        // --- Minimum SL distance ---
        // Requirements 5.4: max(ATR × multiplier, stop_level_points × point)
        double atr_floor    = result.current_atr * atr_sl_mult;
        double broker_floor = (double)stop_level_pts * point_size;
        result.min_sl_distance = MathMax(atr_floor, broker_floor);

        return result;
    }

    //------------------------------------------------------------------
    // ComputeTrueRange
    // Exposed for unit testing. Computes TR for a single bar given
    // the previous bar's close.
    //------------------------------------------------------------------
    static double ComputeTrueRange(double high, double low,
                                   double close, double prev_close)
    {
        double hl  = high - low;
        double hpc = MathAbs(high - prev_close);
        double lpc = MathAbs(low  - prev_close);
        return MathMax(hl, MathMax(hpc, lpc));
    }
};
//+------------------------------------------------------------------+
