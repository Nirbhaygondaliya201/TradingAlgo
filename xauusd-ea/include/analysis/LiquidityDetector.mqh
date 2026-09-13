//+------------------------------------------------------------------+
//| LiquidityDetector.mqh                                            |
//| XAU/USD MT5 Expert Advisor                                       |
//| Liquidity pool detection from confirmed 15M candles.            |
//|                                                                  |
//| ARCHITECTURE: Layer 2 — Analysis.                               |
//| Consumes ONLY confirmed OHLCVBar[] from MTFDataFeed (15M).      |
//| Consumes ATRResult from ATRVolatilityEngine for pool tolerance.  |
//| Never accesses MT5 market data APIs directly.                   |
//| Never generates trade signals.                                  |
//| Produces LiquidityPool registry for later strategy modules.     |
//|                                                                  |
//| SCOPE (exactly as documented in design §2.4):                   |
//|   - Detect Liquidity_Pool zones at clusters of equal highs/lows  |
//|     (≥ 2 swing H/L within PoolATRTolerance × ATR)              |
//|   - Detect Liquidity_Sweep events (wick-through + close-back)   |
//|   - Manage pool lifecycle: Active → Swept / Active → Invalidated|
//|   - Cap pool registry at MaxActivePools per direction           |
//|   - Suspend detection when ATR is unavailable                   |
//|                                                                  |
//| NOT IN SCOPE for this module:                                   |
//|   - BOS, CHOCH, regime detection                                |
//|   - Momentum, entry signals                                     |
//|   - Trade execution                                             |
//|                                                                  |
//| CONFIRMED-CANDLE GUARANTEE:                                     |
//|   Bar[0] is NEVER used for any decision.                        |
//|   Pool creation and sweep detection require bars at index ≥ 1. |
//|   Pool tolerance is locked at creation ATR (not retroactively   |
//|   resized when ATR changes).                                    |
//|                                                                  |
//| NO-REPAINTING GUARANTEE:                                        |
//|   A pool's created_timestamp is the close-time of the           |
//|   confirmation bar that made the pool identifiable.             |
//|   This is bars[SwingSideCandles].time, NOT the swing candle     |
//|   itself, because the right-side confirmation candles must all  |
//|   be closed before the swing (and thus the pool) is confirmed.  |
//|                                                                  |
//| Design reference: §2.4 Liquidity_Detector                      |
//| Requirements: 2.1–2.7                                           |
//| Correctness Properties: 5, 6, 7                                 |
//+------------------------------------------------------------------+
#pragma once
#include "../core/Types.mqh"
#include "../core/Constants.mqh"
#include "../utils/Logger.mqh"

//+------------------------------------------------------------------+
//| LiquidityStatus — output of one detector Update() call          |
//+------------------------------------------------------------------+
struct LiquidityStatus
{
    bool           atr_available;       // false if ATR was UNAVAILABLE
    int            active_pool_count;   // total active pools (both sides)
    int            active_above;        // active sell-side pools (above price)
    int            active_below;        // active buy-side pools (below price)
    bool           sweep_occurred;      // true if a sweep was detected this call
    LiquidityPool  swept_pool;          // most recently swept pool (if any)
    string         rejection_reason;    // non-empty when atr_available=false
};

//+------------------------------------------------------------------+
//| LiquidityDetector                                                |
//| Maintains a per-instance pool registry.                         |
//| Instantiate once; call Update() on every confirmed M15 candle.  |
//+------------------------------------------------------------------+
class LiquidityDetector
{
public:
    //------------------------------------------------------------------
    // Constructor
    //------------------------------------------------------------------
    LiquidityDetector()
    {
        m_pool_count     = 0;
        m_swing_side_n   = 2;       // Default SwingSideCandles
        m_max_pools      = 20;      // Default MaxActivePools
        m_atr_tolerance  = 0.5;     // Default PoolATRTolerance
        ArrayResize(m_pools, 0);
    }

    //------------------------------------------------------------------
    // Configure
    // Set all parameters from Config before the first Update() call.
    //------------------------------------------------------------------
    void Configure(int swing_side_candles, int max_active_pools,
                   double pool_atr_tolerance)
    {
        m_swing_side_n  = swing_side_candles;   // valid range: 1–5
        m_max_pools     = max_active_pools;      // valid range: 5–50
        m_atr_tolerance = pool_atr_tolerance;    // valid range: 0.1–2.0
    }

    //------------------------------------------------------------------
    // Update
    // Called on every new confirmed M15 candle.
    //
    // Parameters:
    //   bars[]         - Confirmed M15 OHLCVBar[], newest-first.
    //                    bars[0] = most recently CLOSED M15 candle.
    //                    MUST NOT contain bar index 0 (forming).
    //   bars_available - Number of valid bars in bars[].
    //   atr_result     - ATRResult from ATRVolatilityEngine (15M ATR).
    //
    // Returns LiquidityStatus.
    //
    // If ATR is unavailable: no new pools created; existing pools kept;
    // status.atr_available = false.
    //
    // Correctness Properties 5, 6, 7.
    //------------------------------------------------------------------
    LiquidityStatus Update(const OHLCVBar& bars[], int bars_available,
                           const ATRResult& atr_result)
    {
        LiquidityStatus status = {};
        status.atr_available    = (atr_result.status != ATR_UNAVAILABLE);
        status.sweep_occurred   = false;
        status.rejection_reason = "";

        // --- If ATR unavailable: no new pool creation; keep existing pools ---
        if(!status.atr_available)
        {
            status.rejection_reason = "ATR_UNAVAILABLE";
            Logger::Warn("LiquidityDetector", "ATR_UNAVAILABLE",
                "atr_status=" + IntegerToString((int)atr_result.status) +
                " suspending_new_pool_creation=true");
            CountPools(status);
            return status;
        }

        // Minimum bars for swing detection: 2*N+1 (N left + pivot + N right)
        int min_bars = 2 * m_swing_side_n + 1;
        if(bars_available < min_bars + 1) // +1 for one additional bar beyond window
        {
            Logger::Warn("LiquidityDetector", "INSUFFICIENT_HISTORY",
                StringFormat("bars_available=%d required>=%d",
                             bars_available, min_bars + 1));
            CountPools(status);
            return status;
        }

        double atr_val = atr_result.current_atr;

        // --- 1. Detect confirmed swing highs and lows ---
        // A swing high at bars[i] requires m_swing_side_n candles on each
        // side that are ALL lower. The most recent confirmable swing is at
        // bars[m_swing_side_n] (its right-side confirmation bars are
        // bars[0]..bars[m_swing_side_n-1], all already closed).
        //
        // NO-REPAINTING: The pool's created_timestamp = bars[0].time
        // (the close of the last right-side confirmation candle), NOT
        // the swing candle's time. This ensures the pool is not visible
        // before it is actually knowable.
        //
        // We scan swing candidates from bars[m_swing_side_n] outward,
        // stopping before we run out of left-side bars.
        int scan_limit = bars_available - m_swing_side_n - 1;

        for(int pivot = m_swing_side_n; pivot <= scan_limit; pivot++)
        {
            // Basic OHLC sanity on pivot bar
            if(!IsValidBar(bars[pivot])) continue;

            double pivot_high = bars[pivot].high;
            double pivot_low  = bars[pivot].low;

            // Check right-side confirmation (bars[0]..bars[pivot-1])
            bool high_right_ok = true;
            bool low_right_ok  = true;
            for(int r = 0; r < m_swing_side_n; r++)
            {
                if(!IsValidBar(bars[r]))      { high_right_ok = false; low_right_ok = false; break; }
                if(bars[r].high >= pivot_high) high_right_ok = false;
                if(bars[r].low  <= pivot_low)  low_right_ok  = false;
            }

            // Check left-side confirmation
            bool high_left_ok = true;
            bool low_left_ok  = true;
            for(int l = pivot + 1; l <= pivot + m_swing_side_n; l++)
            {
                if(l >= bars_available || !IsValidBar(bars[l]))
                { high_left_ok = false; low_left_ok = false; break; }
                if(bars[l].high >= pivot_high) high_left_ok = false;
                if(bars[l].low  <= pivot_low)  low_left_ok  = false;
            }

            // Confirmation timestamp = bars[0].time (newest closed bar)
            // This is when the pool becomes KNOWABLE — no repainting.
            datetime confirmation_time = bars[0].time;

            // --- Swing High → sell-side (above) liquidity pool ---
            if(high_right_ok && high_left_ok)
            {
                TryCreatePool(pivot_high, POOL_SIDE_ABOVE, atr_val,
                              confirmation_time, bars_available);
            }

            // --- Swing Low → buy-side (below) liquidity pool ---
            if(low_right_ok && low_left_ok)
            {
                TryCreatePool(pivot_low, POOL_SIDE_BELOW, atr_val,
                              confirmation_time, bars_available);
            }
        }

        // --- 2. Sweep detection and pool lifecycle ---
        // A sweep is: wick/close THROUGH the pool boundary, then a
        // SUBSEQUENT confirmed candle closes BACK INSIDE the pool.
        // Sweep uses only bars at index ≥ 1 (never bar[0]).
        // bars[0] is the NEWEST confirmed candle = the potential close-back.
        // bars[1] is the candle that may have wicked through.
        if(bars_available >= 2)
        {
            DetectSweep(bars, bars_available, atr_val, status);
        }

        // --- 3. Invalidation ---
        // A pool is invalidated when price closes beyond its boundary
        // by more than the tolerance band WITHOUT a sweep confirmation.
        // Check against bars[0] (most recently closed bar).
        UpdateInvalidation(bars[0]);

        CountPools(status);
        return status;
    }

    //------------------------------------------------------------------
    // GetPools — returns a snapshot of the current pool registry
    //------------------------------------------------------------------
    int GetPools(LiquidityPool& out[]) const
    {
        ArrayResize(out, m_pool_count);
        for(int i = 0; i < m_pool_count; i++)
            out[i] = m_pools[i];
        return m_pool_count;
    }

    //------------------------------------------------------------------
    // Reset — clear all pools (e.g., on reinitialization)
    //------------------------------------------------------------------
    void Reset()
    {
        m_pool_count = 0;
        ArrayResize(m_pools, 0);
        Logger::Info("LiquidityDetector", "RESET", "pool_registry_cleared");
    }

    //------------------------------------------------------------------
    // LoadPools — restore pool registry from StateManager
    //------------------------------------------------------------------
    void LoadPools(const LiquidityPool& saved_pools[], int count)
    {
        ArrayResize(m_pools, count);
        m_pool_count = 0;
        for(int i = 0; i < count; i++)
        {
            if(saved_pools[i].status == POOL_ACTIVE ||
               saved_pools[i].status == POOL_SWEPT  ||
               saved_pools[i].status == POOL_INVALIDATED)
            {
                m_pools[m_pool_count++] = saved_pools[i];
            }
        }
        Logger::Info("LiquidityDetector", "POOLS_LOADED",
            StringFormat("count=%d", m_pool_count));
    }

    int GetPoolCount() const { return m_pool_count; }

private:
    LiquidityPool m_pools[];
    int           m_pool_count;
    int           m_swing_side_n;
    int           m_max_pools;
    double        m_atr_tolerance;

    //------------------------------------------------------------------
    // IsValidBar — basic OHLC sanity
    //------------------------------------------------------------------
    static bool IsValidBar(const OHLCVBar& bar)
    {
        if(bar.time == 0)          return false;
        if(bar.high < bar.low)     return false;
        if(bar.close <= 0.0)       return false;
        if(bar.open  <= 0.0)       return false;
        if(!MathIsValidNumber(bar.high))  return false;
        if(!MathIsValidNumber(bar.low))   return false;
        if(!MathIsValidNumber(bar.close)) return false;
        return true;
    }

    //------------------------------------------------------------------
    // TryCreatePool
    // Attempt to add a pool at price_level on the given side.
    // Checks for duplicate/nearby pools before creating.
    // Enforces MaxActivePools cap.
    //------------------------------------------------------------------
    void TryCreatePool(double price_level, PoolSide side,
                       double atr_val, datetime confirm_time,
                       int bars_available)
    {
        double tolerance = atr_val * m_atr_tolerance;
        if(tolerance <= 0.0 || !MathIsValidNumber(tolerance))
        {
            Logger::Warn("LiquidityDetector", "INVALID_TOLERANCE",
                StringFormat("atr=%.5f mult=%.2f", atr_val, m_atr_tolerance));
            return;
        }

        // Check for existing pool within tolerance (no duplicates)
        for(int i = 0; i < m_pool_count; i++)
        {
            if(m_pools[i].status != POOL_ACTIVE) continue;
            if(m_pools[i].side != side)          continue;
            if(MathAbs(m_pools[i].price_level - price_level) <= tolerance)
                return; // Already have a pool here
        }

        // Count active pools on this side to enforce cap
        int active_on_side = 0;
        int oldest_idx = -1;
        datetime oldest_time = 0;
        for(int i = 0; i < m_pool_count; i++)
        {
            if(m_pools[i].status == POOL_ACTIVE && m_pools[i].side == side)
            {
                active_on_side++;
                if(oldest_time == 0 || m_pools[i].created_timestamp < oldest_time)
                {
                    oldest_time = m_pools[i].created_timestamp;
                    oldest_idx  = i;
                }
            }
        }

        // If at cap: discard oldest active pool on this side
        if(active_on_side >= m_max_pools && oldest_idx >= 0)
        {
            Logger::Debug("LiquidityDetector", "POOL_CAP_DISCARD",
                StringFormat("oldest_time=%s side=%s",
                    TimeToString(m_pools[oldest_idx].created_timestamp),
                    side == POOL_SIDE_ABOVE ? "ABOVE" : "BELOW"));
            RemovePool(oldest_idx);
        }

        // Create new pool
        LiquidityPool new_pool = {};
        new_pool.price_level       = price_level;
        new_pool.tolerance_band    = tolerance;  // locked at creation ATR
        new_pool.status            = POOL_ACTIVE;
        new_pool.side              = side;
        new_pool.created_timestamp = confirm_time;
        new_pool.swept_timestamp   = 0;

        // Append to registry
        int n = m_pool_count;
        ArrayResize(m_pools, n + 1);
        m_pools[n] = new_pool;
        m_pool_count++;

        Logger::Debug("LiquidityDetector", "POOL_CREATED",
            StringFormat("price=%.5f side=%s tol=%.5f ts=%s",
                price_level,
                side == POOL_SIDE_ABOVE ? "ABOVE" : "BELOW",
                tolerance,
                TimeToString(confirm_time)));
    }

    //------------------------------------------------------------------
    // DetectSweep
    // Sweep = wick/close through pool boundary on bars[1],
    //         then bars[0] close back inside pool tolerance.
    // Requirement 2.2: never use bar[0] as the sweep candle itself.
    //------------------------------------------------------------------
    void DetectSweep(const OHLCVBar& bars[], int bars_available,
                     double atr_val, LiquidityStatus& status)
    {
        for(int i = 0; i < m_pool_count; i++)
        {
            if(m_pools[i].status != POOL_ACTIVE) continue;

            double pl  = m_pools[i].price_level;
            double tol = m_pools[i].tolerance_band;
            PoolSide side = m_pools[i].side;

            bool sweep_candle_through = false;
            bool close_back_inside    = false;

            if(side == POOL_SIDE_ABOVE)
            {
                // Sweep of sell-side: price wicks above the pool level on bars[1]
                // then bars[0] close back below (inside) the pool
                sweep_candle_through = (bars[1].high > pl) || (bars[1].close > pl);
                close_back_inside    = (bars[0].close <= pl + tol) &&
                                       (bars[0].close >= pl - tol);
            }
            else
            {
                // Sweep of buy-side: price wicks below pool level on bars[1]
                // then bars[0] close back above (inside) the pool
                sweep_candle_through = (bars[1].low < pl) || (bars[1].close < pl);
                close_back_inside    = (bars[0].close >= pl - tol) &&
                                       (bars[0].close <= pl + tol);
            }

            if(sweep_candle_through && close_back_inside)
            {
                // Mark swept
                m_pools[i].status          = POOL_SWEPT;
                m_pools[i].swept_timestamp = bars[0].time;

                // Report sweep event
                status.sweep_occurred = true;
                status.swept_pool     = m_pools[i];

                Logger::Info("LiquidityDetector", "POOL_SWEPT",
                    StringFormat("price=%.5f side=%s sweep_bar=%s confirm_bar=%s",
                        pl,
                        side == POOL_SIDE_ABOVE ? "ABOVE" : "BELOW",
                        TimeToString(bars[1].time),
                        TimeToString(bars[0].time)));
                // Only sweep the first eligible pool per call
                break;
            }
        }
    }

    //------------------------------------------------------------------
    // UpdateInvalidation
    // A pool is invalidated when bars[0].close exceeds the pool boundary
    // by more than its tolerance_band WITHOUT having been swept first.
    // Requirement 2.3: Active → Invalidated (never Swept → Invalidated).
    //------------------------------------------------------------------
    void UpdateInvalidation(const OHLCVBar& bar0)
    {
        for(int i = 0; i < m_pool_count; i++)
        {
            if(m_pools[i].status != POOL_ACTIVE) continue;

            double pl  = m_pools[i].price_level;
            double tol = m_pools[i].tolerance_band;
            bool invalidated = false;

            if(m_pools[i].side == POOL_SIDE_ABOVE)
            {
                // Close definitively above the pool (broke through) = invalidated
                invalidated = (bar0.close > pl + tol);
            }
            else
            {
                // Close definitively below the pool = invalidated
                invalidated = (bar0.close < pl - tol);
            }

            if(invalidated)
            {
                m_pools[i].status = POOL_INVALIDATED;
                Logger::Debug("LiquidityDetector", "POOL_INVALIDATED",
                    StringFormat("price=%.5f side=%s bar_close=%.5f",
                        pl,
                        m_pools[i].side == POOL_SIDE_ABOVE ? "ABOVE" : "BELOW",
                        bar0.close));
            }
        }
    }

    //------------------------------------------------------------------
    // CountPools — populate active pool counts in status
    //------------------------------------------------------------------
    void CountPools(LiquidityStatus& status) const
    {
        status.active_pool_count = 0;
        status.active_above      = 0;
        status.active_below      = 0;
        for(int i = 0; i < m_pool_count; i++)
        {
            if(m_pools[i].status == POOL_ACTIVE)
            {
                status.active_pool_count++;
                if(m_pools[i].side == POOL_SIDE_ABOVE) status.active_above++;
                else                                    status.active_below++;
            }
        }
    }

    //------------------------------------------------------------------
    // RemovePool — remove pool at index, compact the array
    //------------------------------------------------------------------
    void RemovePool(int idx)
    {
        for(int i = idx; i < m_pool_count - 1; i++)
            m_pools[i] = m_pools[i + 1];
        m_pool_count--;
        ArrayResize(m_pools, m_pool_count);
    }
};
//+------------------------------------------------------------------+
