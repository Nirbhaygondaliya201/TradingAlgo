//+------------------------------------------------------------------+
//| ConfigManager.mqh                                                |
//| XAU/USD MT5 Expert Advisor                                       |
//| All EA input parameters + validation + Config struct.            |
//|                                                                  |
//| ARCHITECTURE: Cross-cutting service (Layer 0).                  |
//| Called once at OnInit. Result stored in g_Config.               |
//| All modules read from g_Config — they never access MT5 input    |
//| variables directly.                                             |
//|                                                                  |
//| Broker-specific symbol properties (point size, lot step,         |
//| contract size, stop level, margin) are NOT stored here.          |
//| They must be obtained at runtime from SymbolPropertiesReader.    |
//| Requirements 14.4, 14.5 are enforced by that module.            |
//|                                                                  |
//| Design reference: §2.15 Config_Manager                          |
//| Requirements: 14.1, 14.2, 14.3                                   |
//+------------------------------------------------------------------+
#pragma once
#include "../core/Types.mqh"
#include "../core/Constants.mqh"
#include "Logger.mqh"

//+------------------------------------------------------------------+
//| Config struct                                                    |
//| Single validated snapshot of all input parameters.              |
//| Populated by ConfigManager::Validate() at OnInit.              |
//| Immutable after successful initialisation.                      |
//+------------------------------------------------------------------+
struct Config
{
    //--- Market Structure Settings (Req 1.2, 3.1)
    int    SwingSideCandles;        // valid: 1–5,   default: 2
    int    RegimeSwingCount;        // valid: 2–10,  default: 4
    bool   RangingModeEnabled;      // default: false

    //--- Liquidity Settings (Req 2.1, 2.5)
    double PoolATRTolerance;        // valid: 0.1–2.0,  default: 0.5
    int    MaxActivePools;          // valid: 5–50,     default: 20

    //--- ATR/Volatility Settings (Req 5.1–5.5)
    int    ATRPeriod;               // valid: 5–50,   default: 14
    double ATRMinMultiplier;        // valid: 0.1–1.0, default: 0.5
    double ATRMaxMultiplier;        // valid: 1.5–5.0, default: 2.5
    double ATRSLMultiplier;         // valid: 0.5–5.0, default: 1.5
    int    ATRUnavailableTimeoutMin;// valid: 1–60,   default: 5

    //--- Momentum Settings (Req 4.1)
    int    MomentumLookback;        // valid: 2–50,  default: 10

    //--- Session Filter Settings (Req 6.1, 6.4, 6.6)
    bool   LondonEnabled;
    int    LondonStartHour;         // 0–23
    int    LondonStartMin;          // 0–59
    int    LondonEndHour;           // 0–23
    int    LondonEndMin;            // 0–59
    int    LondonUTCOffsetHours;    // valid: -12–+14, default: 0

    bool   NewYorkEnabled;
    int    NewYorkStartHour;
    int    NewYorkStartMin;
    int    NewYorkEndHour;
    int    NewYorkEndMin;
    int    NewYorkUTCOffsetHours;   // valid: -12–+14, default: 0

    bool   LNOverlapEnabled;
    int    LNOverlapStartHour;
    int    LNOverlapStartMin;
    int    LNOverlapEndHour;
    int    LNOverlapEndMin;
    int    LNOverlapUTCOffsetHours; // valid: -12–+14, default: 0

    //--- Spread Filter Settings (Req 7.2)
    int    MaxSpreadPoints;         // valid: 10–200, default: 30

    //--- News Filter Settings (Req 8.1–8.7)
    int    NewsProtectionMode;      // 0=BLOCK, 1=WARN, 2=DISABLED
    int    MinImpactLevel;          // 0=Low, 1=Medium, 2=High
    int    PreEventMinutes;         // valid: 0–120, default: 30
    int    PostEventMinutes;        // valid: 0–120, default: 15
    int    MaxNewsListAgeHours;     // valid: 1–168, default: 24
    bool   StaleFallbackBlock;      // true=BLOCK, false=ALLOW; default: true
    string NewsEventsFile;          // path to CSV news calendar

    //--- Risk Settings (Req 9.1–9.8)
    double RiskPerTradePct;         // valid: 0.1–5.0,  default: 1.0
    double MaxLotSize;              // valid: 0.01–10.0, default: 0.5
    int    MaxOpenTrades;           // valid: 1–10,    default: 2
    double DailyMaxDrawdownPct;     // valid: 1.0–20.0, default: 5.0
    double TotalMaxDrawdownPct;     // valid: 5.0–50.0, default: 15.0
    double MinRR;                   // valid: 1.0–10.0, default: 1.5
    double MinFreeMarginPct;        // valid: 110.0–500.0, default: 150.0

    //--- Consecutive Loss / Cooldown (Req 17.6)
    int    MaxConsecutiveLosses;    // valid: 2–20,    default: 5
    int    CooldownHours;           // valid: 1–168,   default: 24

    //--- Execution Settings (Req 10.3, 10.12–10.14)
    int    MaxRetries;              // valid: 1–10,    default: 3
    int    RetryDelayMs;            // valid: 100–5000, default: 500
    int    MaxSignalAgeSeconds;     // valid: 0–60,    default: 0
    int    MaxFreezeSkips;          // valid: 1–20,    default: 5

    //--- Logger Settings (Req 12.5)
    int    MinLogLevel;             // 0=DEBUG … 4=CRITICAL; default: 1 (INFO)

    //--- State Manager Settings (Req 11.4, 19.1)
    string StateFilePath;

    //--- EA Identity
    int    MagicNumber;             // > 0; default: EA_MAGIC_NUMBER
};

//+------------------------------------------------------------------+
//| Input parameter declarations                                     |
//| Grouped by module using input group separators.                  |
//| Requirement 14.3                                                 |
//|                                                                  |
//| NOTE: Broker-specific symbol properties (point, lot_step, etc.) |
//| are deliberately absent — they come from SymbolPropertiesReader  |
//| at runtime and must not be hardcoded. Req 14.4.                  |
//+------------------------------------------------------------------+

//--- EA Identity
input group "=== EA Identity ==="
input int    inp_MagicNumber              = EA_MAGIC_NUMBER; // Magic Number (unique per EA instance)

//--- Market Structure Settings
input group "=== Structure Settings ==="
input int    inp_SwingSideCandles         = 2;     // Candles on each side of swing (1–5)
input int    inp_RegimeSwingCount         = 4;     // Swing points for regime (2–10)
input bool   inp_RangingModeEnabled       = false; // Allow entries in Ranging regime

//--- Liquidity Settings
input group "=== Liquidity Settings ==="
input double inp_PoolATRTolerance         = 0.5;  // Pool tolerance × ATR (0.1–2.0)
input int    inp_MaxActivePools           = 20;   // Max active pools per timeframe (5–50)

//--- ATR / Volatility Settings
input group "=== ATR / Volatility Settings ==="
input int    inp_ATRPeriod                = 14;   // ATR period in 1H candles (5–50)
input double inp_ATRMinMultiplier         = 0.5;  // ATR below baseline×this → block (0.1–1.0)
input double inp_ATRMaxMultiplier         = 2.5;  // ATR above baseline×this → block (1.5–5.0)
input double inp_ATRSLMultiplier          = 1.5;  // Min SL = ATR × this (0.5–5.0)
input int    inp_ATRUnavailableTimeoutMin = 5;    // Block after N min without ATR (1–60)

//--- Momentum Settings
input group "=== Momentum Settings ==="
input int    inp_MomentumLookback         = 10;   // Prior candles for momentum (2–50)

//--- Session Filter Settings
input group "=== Session Settings ==="
input bool   inp_LondonEnabled            = true;
input int    inp_LondonStartHour          = 7;    // London start hour UTC (0–23)
input int    inp_LondonStartMin           = 0;    // London start minute (0–59)
input int    inp_LondonEndHour            = 12;   // London end hour UTC (0–23)
input int    inp_LondonEndMin             = 0;    // London end minute (0–59)
input int    inp_LondonUTCOffsetHours     = 0;    // DST offset hours (-12–+14)

input bool   inp_NewYorkEnabled           = true;
input int    inp_NewYorkStartHour         = 13;
input int    inp_NewYorkStartMin          = 0;
input int    inp_NewYorkEndHour           = 17;
input int    inp_NewYorkEndMin            = 0;
input int    inp_NewYorkUTCOffsetHours    = 0;

input bool   inp_LNOverlapEnabled         = true;
input int    inp_LNOverlapStartHour       = 13;
input int    inp_LNOverlapStartMin        = 0;
input int    inp_LNOverlapEndHour         = 15;
input int    inp_LNOverlapEndMin          = 0;
input int    inp_LNOverlapUTCOffsetHours  = 0;

//--- Spread Filter Settings
input group "=== Spread Settings ==="
input int    inp_MaxSpreadPoints          = 30;   // Max spread in points (10–200)

//--- News Filter Settings
input group "=== News Filter Settings ==="
// NewsProtectionMode: 0=BLOCK, 1=WARN, 2=DISABLED
input int    inp_NewsProtectionMode       = 0;
// MinImpactLevel: 0=Low, 1=Medium, 2=High
input int    inp_MinImpactLevel           = 2;
input int    inp_PreEventMinutes          = 30;   // Block before event (0–120)
input int    inp_PostEventMinutes         = 15;   // Block after event (0–120)
input int    inp_MaxNewsListAgeHours      = 24;   // Stale threshold (1–168)
input bool   inp_StaleFallbackBlock       = true; // true=BLOCK, false=ALLOW
input string inp_NewsEventsFile           = "config/news_events.csv";

//--- Risk Settings
input group "=== Risk Settings ==="
input double inp_RiskPerTradePct          = 1.0;  // Risk % per trade (0.1–5.0)
input double inp_MaxLotSize               = 0.5;  // Max lot size cap (0.01–10.0)
input int    inp_MaxOpenTrades            = 2;    // Max simultaneous trades (1–10)
input double inp_DailyMaxDrawdownPct      = 5.0;  // Daily DD limit % (1.0–20.0)
input double inp_TotalMaxDrawdownPct      = 15.0; // Total DD circuit breaker % (5.0–50.0)
input double inp_MinRR                    = 1.5;  // Minimum R:R (1.0–10.0)
input double inp_MinFreeMarginPct         = 150.0;// Min free margin % (110.0–500.0)

//--- Consecutive Loss / Cooldown
input group "=== Cooldown Settings ==="
input int    inp_MaxConsecutiveLosses     = 5;    // Losses before cooldown (2–20)
input int    inp_CooldownHours            = 24;   // Cooldown duration hours (1–168)

//--- Execution Settings
input group "=== Execution Settings ==="
input int    inp_MaxRetries               = 3;    // Non-fatal order retries (1–10)
input int    inp_RetryDelayMs             = 500;  // Delay between retries ms (100–5000)
input int    inp_MaxSignalAgeSeconds      = 0;    // Max signal age before re-read (0–60)
input int    inp_MaxFreezeSkips           = DEFAULT_MAX_FREEZE_SKIPS; // (1–20)

//--- Logging Settings
input group "=== Logging Settings ==="
// MinLogLevel: 0=DEBUG, 1=INFO, 2=WARN, 3=ERROR, 4=CRITICAL
input int    inp_MinLogLevel              = 1;    // INFO default

//--- State Manager Settings
input group "=== State Manager Settings ==="
input string inp_StateFilePath            = "xauusd_ea_state.txt";

//+------------------------------------------------------------------+
//| Global validated config instance                                 |
//| Populated once by ConfigManager::Validate() in OnInit.          |
//+------------------------------------------------------------------+
Config g_Config;

//+------------------------------------------------------------------+
//| ConfigManager                                                    |
//| Validates all input parameters and populates g_Config.          |
//| On first validation failure: logs error + returns false         |
//| (caller maps false to INIT_FAILED).                             |
//| Requirement 14.2                                                |
//+------------------------------------------------------------------+
class ConfigManager
{
public:
    //------------------------------------------------------------------
    // Validate
    // Call once in OnInit(). Returns true on success, false on failure.
    // On failure a structured error is logged identifying the parameter
    // name, submitted value, and valid range. Requirement 14.2.
    //------------------------------------------------------------------
    static bool Validate()
    {
        // ---- EA Identity ----
        if(!CheckInt("MagicNumber", inp_MagicNumber, 1, 2147483647))      return false;

        // ---- Market Structure ----
        if(!CheckInt("SwingSideCandles",   inp_SwingSideCandles,   1, 5))  return false;
        if(!CheckInt("RegimeSwingCount",   inp_RegimeSwingCount,   2, 10)) return false;

        // ---- Liquidity ----
        if(!CheckDouble("PoolATRTolerance", inp_PoolATRTolerance,  0.1, 2.0)) return false;
        if(!CheckInt("MaxActivePools",      inp_MaxActivePools,    5,   50))  return false;

        // ---- ATR / Volatility ----
        if(!CheckInt("ATRPeriod",               inp_ATRPeriod,               5,   50))  return false;
        if(!CheckDouble("ATRMinMultiplier",      inp_ATRMinMultiplier,        0.1, 1.0)) return false;
        if(!CheckDouble("ATRMaxMultiplier",      inp_ATRMaxMultiplier,        1.5, 5.0)) return false;
        if(!CheckDouble("ATRSLMultiplier",       inp_ATRSLMultiplier,         0.5, 5.0)) return false;
        if(!CheckInt("ATRUnavailableTimeoutMin", inp_ATRUnavailableTimeoutMin, 1,  60))  return false;

        // ---- Momentum ----
        if(!CheckInt("MomentumLookback", inp_MomentumLookback, 2, 50)) return false;

        // ---- Session ----
        if(!CheckHour("LondonStartHour",    inp_LondonStartHour))   return false;
        if(!CheckMin ("LondonStartMin",     inp_LondonStartMin))    return false;
        if(!CheckHour("LondonEndHour",      inp_LondonEndHour))     return false;
        if(!CheckMin ("LondonEndMin",       inp_LondonEndMin))      return false;
        if(!CheckInt ("LondonUTCOffset",    inp_LondonUTCOffsetHours, -12, 14)) return false;
        // start < end required when session is enabled
        if(inp_LondonEnabled)
        {
            int ls = inp_LondonStartHour * 60 + inp_LondonStartMin;
            int le = inp_LondonEndHour   * 60 + inp_LondonEndMin;
            if(ls >= le)
            {
                LogValidationError("LondonSession",
                    StringFormat("%02d:%02d–%02d:%02d",
                        inp_LondonStartHour, inp_LondonStartMin,
                        inp_LondonEndHour,   inp_LondonEndMin),
                    "start time must be < end time");
                return false;
            }
        }

        if(!CheckHour("NewYorkStartHour",   inp_NewYorkStartHour))  return false;
        if(!CheckMin ("NewYorkStartMin",    inp_NewYorkStartMin))   return false;
        if(!CheckHour("NewYorkEndHour",     inp_NewYorkEndHour))    return false;
        if(!CheckMin ("NewYorkEndMin",      inp_NewYorkEndMin))     return false;
        if(!CheckInt ("NewYorkUTCOffset",   inp_NewYorkUTCOffsetHours, -12, 14)) return false;
        if(inp_NewYorkEnabled)
        {
            int ns = inp_NewYorkStartHour * 60 + inp_NewYorkStartMin;
            int ne = inp_NewYorkEndHour   * 60 + inp_NewYorkEndMin;
            if(ns >= ne)
            {
                LogValidationError("NewYorkSession",
                    StringFormat("%02d:%02d–%02d:%02d",
                        inp_NewYorkStartHour, inp_NewYorkStartMin,
                        inp_NewYorkEndHour,   inp_NewYorkEndMin),
                    "start time must be < end time");
                return false;
            }
        }

        if(!CheckHour("LNOverlapStartHour", inp_LNOverlapStartHour)) return false;
        if(!CheckMin ("LNOverlapStartMin",  inp_LNOverlapStartMin))  return false;
        if(!CheckHour("LNOverlapEndHour",   inp_LNOverlapEndHour))   return false;
        if(!CheckMin ("LNOverlapEndMin",    inp_LNOverlapEndMin))    return false;
        if(!CheckInt ("LNOverlapUTCOffset", inp_LNOverlapUTCOffsetHours, -12, 14)) return false;
        if(inp_LNOverlapEnabled)
        {
            int os = inp_LNOverlapStartHour * 60 + inp_LNOverlapStartMin;
            int oe = inp_LNOverlapEndHour   * 60 + inp_LNOverlapEndMin;
            if(os >= oe)
            {
                LogValidationError("LNOverlapSession",
                    StringFormat("%02d:%02d–%02d:%02d",
                        inp_LNOverlapStartHour, inp_LNOverlapStartMin,
                        inp_LNOverlapEndHour,   inp_LNOverlapEndMin),
                    "start time must be < end time");
                return false;
            }
        }

        // ---- Spread ----
        if(!CheckInt("MaxSpreadPoints", inp_MaxSpreadPoints, 10, 200)) return false;

        // ---- News ----
        if(!CheckInt("NewsProtectionMode", inp_NewsProtectionMode, 0, 2))   return false;
        if(!CheckInt("MinImpactLevel",     inp_MinImpactLevel,     0, 2))   return false;
        if(!CheckInt("PreEventMinutes",    inp_PreEventMinutes,    0, 120)) return false;
        if(!CheckInt("PostEventMinutes",   inp_PostEventMinutes,   0, 120)) return false;
        if(!CheckInt("MaxNewsListAgeHours",inp_MaxNewsListAgeHours,1, 168)) return false;
        if(StringLen(inp_NewsEventsFile) == 0)
        {
            LogValidationError("NewsEventsFile", "", "must not be empty");
            return false;
        }

        // ---- Risk ----
        if(!CheckDouble("RiskPerTradePct",    inp_RiskPerTradePct,    0.1,  5.0))   return false;
        if(!CheckDouble("MaxLotSize",         inp_MaxLotSize,         0.01, 10.0))  return false;
        if(!CheckInt   ("MaxOpenTrades",      inp_MaxOpenTrades,      1,    10))    return false;
        if(!CheckDouble("DailyMaxDrawdownPct",inp_DailyMaxDrawdownPct,1.0,  20.0))  return false;
        if(!CheckDouble("TotalMaxDrawdownPct",inp_TotalMaxDrawdownPct,5.0,  50.0))  return false;
        if(!CheckDouble("MinRR",              inp_MinRR,              1.0,  10.0))  return false;
        if(!CheckDouble("MinFreeMarginPct",   inp_MinFreeMarginPct,   110.0,500.0)) return false;

        // Safety: DailyMaxDrawdownPct must be < TotalMaxDrawdownPct
        // (not explicitly stated but required to prevent incoherent circuit breakers)
        if(inp_DailyMaxDrawdownPct >= inp_TotalMaxDrawdownPct)
        {
            LogValidationError("DailyMaxDrawdownPct/TotalMaxDrawdownPct",
                StringFormat("daily=%.1f total=%.1f",
                    inp_DailyMaxDrawdownPct, inp_TotalMaxDrawdownPct),
                "DailyMaxDrawdownPct must be < TotalMaxDrawdownPct");
            return false;
        }

        // ---- Cooldown ----
        if(!CheckInt("MaxConsecutiveLosses", inp_MaxConsecutiveLosses, 2,  20))  return false;
        if(!CheckInt("CooldownHours",        inp_CooldownHours,        1,  168)) return false;

        // ---- Execution ----
        if(!CheckInt("MaxRetries",          inp_MaxRetries,          1,  10))   return false;
        if(!CheckInt("RetryDelayMs",        inp_RetryDelayMs,        100,5000)) return false;
        if(!CheckInt("MaxSignalAgeSeconds", inp_MaxSignalAgeSeconds,  0,  60))  return false;
        if(!CheckInt("MaxFreezeSkips",      inp_MaxFreezeSkips,       1,  20))  return false;

        // ---- Logger ----
        if(!CheckInt("MinLogLevel", inp_MinLogLevel, 0, 4)) return false;

        // ---- State Manager ----
        if(StringLen(inp_StateFilePath) == 0)
        {
            LogValidationError("StateFilePath", "", "must not be empty");
            return false;
        }

        // ---- All valid — populate g_Config ----
        g_Config.MagicNumber              = inp_MagicNumber;
        g_Config.SwingSideCandles         = inp_SwingSideCandles;
        g_Config.RegimeSwingCount         = inp_RegimeSwingCount;
        g_Config.RangingModeEnabled       = inp_RangingModeEnabled;
        g_Config.PoolATRTolerance         = inp_PoolATRTolerance;
        g_Config.MaxActivePools           = inp_MaxActivePools;
        g_Config.ATRPeriod                = inp_ATRPeriod;
        g_Config.ATRMinMultiplier         = inp_ATRMinMultiplier;
        g_Config.ATRMaxMultiplier         = inp_ATRMaxMultiplier;
        g_Config.ATRSLMultiplier          = inp_ATRSLMultiplier;
        g_Config.ATRUnavailableTimeoutMin = inp_ATRUnavailableTimeoutMin;
        g_Config.MomentumLookback         = inp_MomentumLookback;
        g_Config.LondonEnabled            = inp_LondonEnabled;
        g_Config.LondonStartHour          = inp_LondonStartHour;
        g_Config.LondonStartMin           = inp_LondonStartMin;
        g_Config.LondonEndHour            = inp_LondonEndHour;
        g_Config.LondonEndMin             = inp_LondonEndMin;
        g_Config.LondonUTCOffsetHours     = inp_LondonUTCOffsetHours;
        g_Config.NewYorkEnabled           = inp_NewYorkEnabled;
        g_Config.NewYorkStartHour         = inp_NewYorkStartHour;
        g_Config.NewYorkStartMin          = inp_NewYorkStartMin;
        g_Config.NewYorkEndHour           = inp_NewYorkEndHour;
        g_Config.NewYorkEndMin            = inp_NewYorkEndMin;
        g_Config.NewYorkUTCOffsetHours    = inp_NewYorkUTCOffsetHours;
        g_Config.LNOverlapEnabled         = inp_LNOverlapEnabled;
        g_Config.LNOverlapStartHour       = inp_LNOverlapStartHour;
        g_Config.LNOverlapStartMin        = inp_LNOverlapStartMin;
        g_Config.LNOverlapEndHour         = inp_LNOverlapEndHour;
        g_Config.LNOverlapEndMin          = inp_LNOverlapEndMin;
        g_Config.LNOverlapUTCOffsetHours  = inp_LNOverlapUTCOffsetHours;
        g_Config.MaxSpreadPoints          = inp_MaxSpreadPoints;
        g_Config.NewsProtectionMode       = inp_NewsProtectionMode;
        g_Config.MinImpactLevel           = inp_MinImpactLevel;
        g_Config.PreEventMinutes          = inp_PreEventMinutes;
        g_Config.PostEventMinutes         = inp_PostEventMinutes;
        g_Config.MaxNewsListAgeHours      = inp_MaxNewsListAgeHours;
        g_Config.StaleFallbackBlock       = inp_StaleFallbackBlock;
        g_Config.NewsEventsFile           = inp_NewsEventsFile;
        g_Config.RiskPerTradePct          = inp_RiskPerTradePct;
        g_Config.MaxLotSize               = inp_MaxLotSize;
        g_Config.MaxOpenTrades            = inp_MaxOpenTrades;
        g_Config.DailyMaxDrawdownPct      = inp_DailyMaxDrawdownPct;
        g_Config.TotalMaxDrawdownPct      = inp_TotalMaxDrawdownPct;
        g_Config.MinRR                    = inp_MinRR;
        g_Config.MinFreeMarginPct         = inp_MinFreeMarginPct;
        g_Config.MaxConsecutiveLosses     = inp_MaxConsecutiveLosses;
        g_Config.CooldownHours            = inp_CooldownHours;
        g_Config.MaxRetries               = inp_MaxRetries;
        g_Config.RetryDelayMs             = inp_RetryDelayMs;
        g_Config.MaxSignalAgeSeconds      = inp_MaxSignalAgeSeconds;
        g_Config.MaxFreezeSkips           = inp_MaxFreezeSkips;
        g_Config.MinLogLevel              = inp_MinLogLevel;
        g_Config.StateFilePath            = inp_StateFilePath;

        // Apply validated log level to Logger immediately
        Logger::SetMinLevel((LogLevel)g_Config.MinLogLevel);

        Logger::Info("ConfigManager", "INIT_OK",
            StringFormat("magic=%d riskPct=%.2f maxDD=%.1f",
                g_Config.MagicNumber,
                g_Config.RiskPerTradePct,
                g_Config.TotalMaxDrawdownPct));

        return true;
    }

private:
    //------------------------------------------------------------------
    // CheckInt — validates an integer parameter is within [min_val, max_val]
    //------------------------------------------------------------------
    static bool CheckInt(const string name, int value, int min_val, int max_val)
    {
        if(value >= min_val && value <= max_val) return true;
        LogValidationError(name,
            (string)value,
            StringFormat("valid range: %d–%d", min_val, max_val));
        return false;
    }

    //------------------------------------------------------------------
    // CheckDouble — validates a double parameter is within [min_val, max_val]
    //------------------------------------------------------------------
    static bool CheckDouble(const string name, double value,
                            double min_val, double max_val)
    {
        if(value >= min_val && value <= max_val) return true;
        LogValidationError(name,
            StringFormat("%.4f", value),
            StringFormat("valid range: %.4f–%.4f", min_val, max_val));
        return false;
    }

    //------------------------------------------------------------------
    // CheckHour — validates 0 ≤ value ≤ 23
    //------------------------------------------------------------------
    static bool CheckHour(const string name, int value)
    {
        return CheckInt(name, value, 0, 23);
    }

    //------------------------------------------------------------------
    // CheckMin — validates 0 ≤ value ≤ 59
    //------------------------------------------------------------------
    static bool CheckMin(const string name, int value)
    {
        return CheckInt(name, value, 0, 59);
    }

    //------------------------------------------------------------------
    // LogValidationError
    // Logs a structured ERROR entry with parameter name, submitted value,
    // and valid range. Requirement 14.2.
    //------------------------------------------------------------------
    static void LogValidationError(const string name,
                                   const string value,
                                   const string range_desc)
    {
        Logger::Error("ConfigManager", "PARAM_INVALID",
            StringFormat("param=%s value=%s constraint=[%s]",
                         name, value, range_desc));
    }
};
//+------------------------------------------------------------------+
