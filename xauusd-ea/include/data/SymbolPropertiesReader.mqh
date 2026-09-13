//+------------------------------------------------------------------+
//| SymbolPropertiesReader.mqh                                       |
//| XAU/USD MT5 Expert Advisor                                       |
//| Runtime broker/symbol property retrieval.                        |
//|                                                                  |
//| ARCHITECTURE: Layer 1 — Data Acquisition.                        |
//| Called ONCE at OnInit. All values are read from MT5 at runtime. |
//| NO broker value is hardcoded.                                   |
//| After successful initialisation the module is immutable.        |
//| All downstream modules consume the g_SymProps global instance.  |
//|                                                                  |
//| Mandatory properties (any failure → INIT_FAILED):               |
//|   SYMBOL_POINT, SYMBOL_VOLUME_STEP, SYMBOL_TRADE_CONTRACT_SIZE, |
//|   SYMBOL_TRADE_STOPS_LEVEL, SYMBOL_MARGIN_INITIAL               |
//|                                                                  |
//| Additional required properties:                                  |
//|   SYMBOL_VOLUME_MIN, SYMBOL_VOLUME_MAX, SYMBOL_TRADE_FREEZE_LEVEL|
//|   SYMBOL_TRADE_TICK_SIZE, SYMBOL_TRADE_TICK_VALUE, SYMBOL_DIGITS |
//|                                                                  |
//| Special rules:                                                   |
//|   - Stops level = 0 is valid (some brokers allow any distance)   |
//|   - Freeze level = 0 is valid                                    |
//|   - Contract size and tick value must be > 0                     |
//|   - Min lot > 0, Max lot > min lot, Lot step > 0                 |
//|   - Point > 0, Digits >= 0                                      |
//|                                                                  |
//| Design reference: §2.1 Symbol_Properties_Reader                 |
//| Requirements: 14.4, 14.5                                         |
//+------------------------------------------------------------------+
#pragma once
#include "../core/Types.mqh"
#include "../core/Constants.mqh"
#include "../utils/Logger.mqh"

//+------------------------------------------------------------------+
//| Global SymbolProperties instance                                 |
//| Populated once by SymbolPropertiesReader::Read().               |
//| All modules that need broker values read from this global.      |
//+------------------------------------------------------------------+
SymbolProperties g_SymProps;

//+------------------------------------------------------------------+
//| SymbolPropertiesReader                                           |
//+------------------------------------------------------------------+
class SymbolPropertiesReader
{
public:
    //------------------------------------------------------------------
    // Read
    // Read all broker/symbol properties from MT5 for the given symbol.
    // Populates g_SymProps.
    // Returns true on success; false if any mandatory property fails.
    // Caller maps false → INIT_FAILED. Requirements 14.4, 14.5.
    //------------------------------------------------------------------
    static bool Read(const string symbol)
    {
        // Defensive reset
        SymbolProperties sp = {};
        sp.is_valid = false;

        // ---- 1. SYMBOL_DIGITS ----------------------------------------
        int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
        // Digits = 0 is valid for integer-priced instruments (rare but legal)
        sp.digits = digits;

        // ---- 2. SYMBOL_POINT -----------------------------------------
        // Mandatory. Must be > 0.
        double pt = SymbolInfoDouble(symbol, SYMBOL_POINT);
        if(pt <= 0.0)
        {
            Logger::Error("SymbolPropertiesReader", "INIT_FAILED",
                "param=SYMBOL_POINT value=" + DoubleToString(pt, 10) +
                " constraint=[must be > 0]");
            return false;
        }
        sp.point = pt;

        // ---- 3. SYMBOL_TRADE_TICK_SIZE --------------------------------
        double tick_sz = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
        if(tick_sz <= 0.0)
        {
            Logger::Error("SymbolPropertiesReader", "INIT_FAILED",
                "param=SYMBOL_TRADE_TICK_SIZE value=" + DoubleToString(tick_sz, 10) +
                " constraint=[must be > 0]");
            return false;
        }
        sp.tick_size = tick_sz;

        // ---- 4. SYMBOL_TRADE_TICK_VALUE --------------------------------
        // Mandatory. Must be > 0. Used in position sizing.
        double tick_val = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE);
        if(tick_val <= 0.0)
        {
            Logger::Error("SymbolPropertiesReader", "INIT_FAILED",
                "param=SYMBOL_TRADE_TICK_VALUE value=" + DoubleToString(tick_val, 10) +
                " constraint=[must be > 0]");
            return false;
        }
        sp.tick_value = tick_val;

        // ---- 5. SYMBOL_TRADE_CONTRACT_SIZE ----------------------------
        // Mandatory. Must be > 0.
        double cs = SymbolInfoDouble(symbol, SYMBOL_TRADE_CONTRACT_SIZE);
        if(cs <= 0.0)
        {
            Logger::Error("SymbolPropertiesReader", "INIT_FAILED",
                "param=SYMBOL_TRADE_CONTRACT_SIZE value=" + DoubleToString(cs, 10) +
                " constraint=[must be > 0]");
            return false;
        }
        sp.contract_size = cs;

        // ---- 6. SYMBOL_VOLUME_STEP ------------------------------------
        // Mandatory. Must be > 0.
        double lot_step = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
        if(lot_step <= 0.0)
        {
            Logger::Error("SymbolPropertiesReader", "INIT_FAILED",
                "param=SYMBOL_VOLUME_STEP value=" + DoubleToString(lot_step, 10) +
                " constraint=[must be > 0]");
            return false;
        }
        sp.lot_step = lot_step;

        // ---- 7. SYMBOL_VOLUME_MIN ------------------------------------
        double min_lot = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
        if(min_lot <= 0.0)
        {
            Logger::Error("SymbolPropertiesReader", "INIT_FAILED",
                "param=SYMBOL_VOLUME_MIN value=" + DoubleToString(min_lot, 10) +
                " constraint=[must be > 0]");
            return false;
        }
        sp.min_lot = min_lot;

        // ---- 8. SYMBOL_VOLUME_MAX ------------------------------------
        double max_lot = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
        if(max_lot <= 0.0 || max_lot < min_lot)
        {
            Logger::Error("SymbolPropertiesReader", "INIT_FAILED",
                StringFormat("param=SYMBOL_VOLUME_MAX value=%.5f min_lot=%.5f"
                             " constraint=[must be > 0 and >= SYMBOL_VOLUME_MIN]",
                             max_lot, min_lot));
            return false;
        }
        sp.max_lot = max_lot;

        // ---- 9. SYMBOL_TRADE_STOPS_LEVEL ------------------------------
        // Mandatory. 0 is valid (means no minimum stop distance enforced by broker).
        int stop_lvl = (int)SymbolInfoInteger(symbol, SYMBOL_TRADE_STOPS_LEVEL);
        if(stop_lvl < 0)
        {
            Logger::Error("SymbolPropertiesReader", "INIT_FAILED",
                "param=SYMBOL_TRADE_STOPS_LEVEL value=" + (string)stop_lvl +
                " constraint=[must be >= 0]");
            return false;
        }
        sp.stop_level_points = stop_lvl;

        // ---- 10. SYMBOL_TRADE_FREEZE_LEVEL ----------------------------
        // 0 is valid.
        int freeze_lvl = (int)SymbolInfoInteger(symbol, SYMBOL_TRADE_FREEZE_LEVEL);
        if(freeze_lvl < 0)
        {
            Logger::Error("SymbolPropertiesReader", "INIT_FAILED",
                "param=SYMBOL_TRADE_FREEZE_LEVEL value=" + (string)freeze_lvl +
                " constraint=[must be >= 0]");
            return false;
        }
        sp.freeze_level_points = freeze_lvl;

        // ---- 11. SYMBOL_MARGIN_INITIAL --------------------------------
        // Mandatory. >= 0 (0 means broker computes dynamically — valid).
        double margin = SymbolInfoDouble(symbol, SYMBOL_MARGIN_INITIAL);
        if(margin < 0.0)
        {
            Logger::Error("SymbolPropertiesReader", "INIT_FAILED",
                "param=SYMBOL_MARGIN_INITIAL value=" + DoubleToString(margin, 2) +
                " constraint=[must be >= 0]");
            return false;
        }
        sp.margin_initial = margin;

        // ---- Internal consistency: point vs digits --------------------
        // Point should be approximately 10^(-digits). Allow for floating-point
        // imprecision. Warn if obviously inconsistent but do not fail.
        if(sp.digits > 0)
        {
            double expected_pt = MathPow(10.0, -(double)sp.digits);
            if(MathAbs(sp.point - expected_pt) > expected_pt * 0.1)
            {
                Logger::Warn("SymbolPropertiesReader", "POINT_DIGITS_MISMATCH",
                    StringFormat("point=%.10f digits=%d expected_point=%.10f",
                                 sp.point, sp.digits, expected_pt));
                // Not a fatal error — some brokers have non-standard point sizes
            }
        }

        // ---- Internal consistency: tick_size vs point -----------------
        // Tick size should be a multiple of point. Warn if not.
        if(sp.point > 0.0)
        {
            double ratio = sp.tick_size / sp.point;
            double rounded = MathRound(ratio);
            if(MathAbs(ratio - rounded) > 0.001)
            {
                Logger::Warn("SymbolPropertiesReader", "TICKSIZE_POINT_MISMATCH",
                    StringFormat("tick_size=%.10f point=%.10f ratio=%.6f",
                                 sp.tick_size, sp.point, ratio));
            }
        }

        // ---- All checks passed: mark valid and publish ----------------
        sp.is_valid = true;
        g_SymProps  = sp;

        Logger::Info("SymbolPropertiesReader", "INIT_OK",
            StringFormat("symbol=%s digits=%d point=%.10f tick_sz=%.10f"
                         " tick_val=%.5f contract=%.2f lot_step=%.5f"
                         " min_lot=%.5f max_lot=%.2f stop_lvl=%d freeze_lvl=%d"
                         " margin=%.2f",
                         symbol, sp.digits, sp.point, sp.tick_size,
                         sp.tick_value, sp.contract_size, sp.lot_step,
                         sp.min_lot, sp.max_lot, sp.stop_level_points,
                         sp.freeze_level_points, sp.margin_initial));
        return true;
    }

    //------------------------------------------------------------------
    // IsValid
    // Returns true if g_SymProps was successfully populated.
    // All consuming modules must call this before using any property.
    //------------------------------------------------------------------
    static bool IsValid()
    {
        return g_SymProps.is_valid;
    }

    //------------------------------------------------------------------
    // GetProps
    // Returns a const reference to the populated SymbolProperties.
    // Consumers should call IsValid() first.
    //------------------------------------------------------------------
    static const SymbolProperties* GetProps()
    {
        return &g_SymProps;
    }
};
//+------------------------------------------------------------------+
