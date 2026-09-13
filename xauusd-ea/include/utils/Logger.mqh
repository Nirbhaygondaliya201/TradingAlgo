//+------------------------------------------------------------------+
//| Logger.mqh                                                       |
//| XAU/USD MT5 Expert Advisor                                       |
//| Stateless structured logging utility.                            |
//|                                                                  |
//| ARCHITECTURE: Cross-cutting service (Layer 0).                  |
//| Called from all layers. Holds NO references to other modules.   |
//| Has no mutable state — every function is a pure output action.  |
//|                                                                  |
//| Output format per line:                                          |
//|   LEVEL | ISO8601_UTC | MODULE | EVENT_TYPE | field1=val1 | ...  |
//|                                                                  |
//| Design reference: §2.14 Logger                                  |
//| Requirements: 12.1, 12.2, 12.3, 12.5, 12.6, 13.6               |
//| Correctness Properties: 24, 25                                   |
//+------------------------------------------------------------------+
#pragma once
#include "../core/Types.mqh"
#include "../core/Constants.mqh"

//+------------------------------------------------------------------+
//| Log level enumeration                                            |
//| Integer values define the severity order used for filtering.     |
//| Requirement 12.2                                                 |
//+------------------------------------------------------------------+
enum LogLevel
{
    LOG_DEBUG    = 0,
    LOG_INFO     = 1,
    LOG_WARN     = 2,
    LOG_ERROR    = 3,
    LOG_CRITICAL = 4
};

//+------------------------------------------------------------------+
//| Logger                                                           |
//| All methods are static — no instantiation needed.               |
//| Log write failures are silently ignored (must not crash EA).     |
//| Requirement 12.5: entries below g_min_log_level are suppressed. |
//+------------------------------------------------------------------+
class Logger
{
public:
    //--- Minimum log level applied to all subsequent calls.
    //    Default matches Requirement 12.5 default (INFO).
    static LogLevel g_min_log_level;

    //--- Optional file handle for persistent log output.
    //    0 = disabled (Print() only). Set via SetFileHandle().
    static int g_file_handle;

    //------------------------------------------------------------------
    // SetMinLevel
    // Configure the minimum severity threshold.
    // Entries below this level are suppressed.
    // Requirement 12.5
    //------------------------------------------------------------------
    static void SetMinLevel(LogLevel level)
    {
        g_min_log_level = level;
    }

    //------------------------------------------------------------------
    // SetFileHandle
    // Attach an open MT5 file handle for persistent log output.
    // Pass INVALID_HANDLE to disable file output.
    //------------------------------------------------------------------
    static void SetFileHandle(int handle)
    {
        g_file_handle = handle;
    }

    //------------------------------------------------------------------
    // Write
    // Core log function used by all specialised helpers.
    //
    // Parameters:
    //   level       - Severity level of the entry
    //   module      - Name of the calling module (e.g. "RiskManager")
    //   event_type  - Structured event label (e.g. "ORDER_SUBMITTED")
    //   fields      - Pipe-separated key=value pairs appended after
    //                 the mandatory header; may be empty string
    //
    // Format: LEVEL | ISO8601_UTC | MODULE | EVENT_TYPE | fields...
    // Requirement 12.2
    //
    // Log write failures are silently caught — the EA must not crash
    // because logging failed. Requirement 12.5 (failure behavior).
    //------------------------------------------------------------------
    static void Write(
        LogLevel      level,
        const string  module,
        const string  event_type,
        const string  fields = ""
    )
    {
        // Suppress entries below the configured minimum level.
        if(level < g_min_log_level)
            return;

        string level_str = LevelToString(level);
        string ts        = TimeToISO8601(TimeGMT());
        string line;

        if(StringLen(fields) > 0)
            line = StringFormat("%s | %s | %s | %s | %s",
                                level_str, ts, module, event_type, fields);
        else
            line = StringFormat("%s | %s | %s | %s",
                                level_str, ts, module, event_type);

        // Write to MT5 Experts log — failure silently ignored.
        Print(line);

        // Write to file if a handle is attached — failure silently ignored.
        if(g_file_handle != INVALID_HANDLE && g_file_handle > 0)
        {
            FileWriteString(g_file_handle, line + "\n");
        }
    }

    //------------------------------------------------------------------
    // Debug / Info / Warn / Error / Critical convenience wrappers
    //------------------------------------------------------------------
    static void Debug(const string module, const string event_type,
                      const string fields = "")
    { Write(LOG_DEBUG,    module, event_type, fields); }

    static void Info(const string module, const string event_type,
                     const string fields = "")
    { Write(LOG_INFO,     module, event_type, fields); }

    static void Warn(const string module, const string event_type,
                     const string fields = "")
    { Write(LOG_WARN,     module, event_type, fields); }

    static void Error(const string module, const string event_type,
                      const string fields = "")
    { Write(LOG_ERROR,    module, event_type, fields); }

    static void Critical(const string module, const string event_type,
                         const string fields = "")
    { Write(LOG_CRITICAL, module, event_type, fields); }

    //------------------------------------------------------------------
    // WriteTradeEvent
    // Logs a trade-related event with mandatory financial context.
    // Requirement 12.3: signal generated/approved/rejected, order
    // submitted/filled/rejected/modified/closed MUST include equity,
    // balance, and open drawdown percentage.
    //------------------------------------------------------------------
    static void WriteTradeEvent(
        LogLevel      level,
        const string  module,
        const string  event_type,
        double        equity,
        double        balance,
        double        drawdown_pct,
        const string  extra_fields = ""
    )
    {
        string financial = StringFormat(
            "equity=%.2f | balance=%.2f | drawdown_pct=%.4f",
            equity, balance, drawdown_pct);

        string all_fields = (StringLen(extra_fields) > 0)
            ? financial + " | " + extra_fields
            : financial;

        Write(level, module, event_type, all_fields);
    }

    //------------------------------------------------------------------
    // MaskAccountNumber
    // Replaces all but the last 4 digits of an account number string
    // with '*'. Non-digit characters are preserved in position.
    //
    // Examples:
    //   "12345678"    → "****5678"
    //   "1234"        → "1234"   (exactly 4 digits — nothing masked)
    //   "123"         → "123"    (fewer than 4 digits — no masking)
    //
    // Requirement 12.6, Correctness Property 24.
    //------------------------------------------------------------------
    static string MaskAccountNumber(const string account_str)
    {
        int len = StringLen(account_str);
        if(len <= 4)
            return account_str;  // Nothing to mask

        string result = "";
        for(int i = 0; i < len - 4; i++)
        {
            ushort ch = StringGetCharacter(account_str, i);
            // Only mask digit characters (ASCII 48–57)
            if(ch >= 48 && ch <= 57)
                result += "*";
            else
                result += ShortToString(ch);
        }
        // Append the last 4 characters unchanged
        result += StringSubstr(account_str, len - 4, 4);
        return result;
    }

    //------------------------------------------------------------------
    // BuildFields
    // Convenience helper: builds a pipe-separated key=value string
    // from up to 8 key/value pairs. Pass "" for unused slots.
    // Callers should not include the field separator in values.
    //------------------------------------------------------------------
    static string BuildFields(
        const string k1 = "", const string v1 = "",
        const string k2 = "", const string v2 = "",
        const string k3 = "", const string v3 = "",
        const string k4 = "", const string v4 = "",
        const string k5 = "", const string v5 = "",
        const string k6 = "", const string v6 = "",
        const string k7 = "", const string v7 = "",
        const string k8 = "", const string v8 = ""
    )
    {
        string result = "";
        string keys[8]  = {k1, k2, k3, k4, k5, k6, k7, k8};
        string vals[8]  = {v1, v2, v3, v4, v5, v6, v7, v8};

        for(int i = 0; i < 8; i++)
        {
            if(StringLen(keys[i]) == 0) continue;
            if(StringLen(result) > 0) result += " | ";
            result += keys[i] + "=" + vals[i];
        }
        return result;
    }

    //------------------------------------------------------------------
    // LevelToString
    // Convert a LogLevel enum value to its string representation.
    //------------------------------------------------------------------
    static string LevelToString(LogLevel level)
    {
        switch(level)
        {
            case LOG_DEBUG:    return "DEBUG";
            case LOG_INFO:     return "INFO";
            case LOG_WARN:     return "WARN";
            case LOG_ERROR:    return "ERROR";
            case LOG_CRITICAL: return "CRITICAL";
            default:           return "UNKNOWN";
        }
    }

    //------------------------------------------------------------------
    // TimeToISO8601
    // Format a datetime value as ISO 8601 UTC string.
    // e.g. 2026-09-09T07:30:00Z
    // Requirement 12.2
    //------------------------------------------------------------------
    static string TimeToISO8601(datetime dt)
    {
        MqlDateTime t;
        TimeToStruct(dt, t);
        return StringFormat("%04d-%02d-%02dT%02d:%02d:%02dZ",
            t.year, t.mon, t.day, t.hour, t.min, t.sec);
    }
};

//+------------------------------------------------------------------+
//| Static member definitions                                        |
//| Default log level = INFO per Requirement 12.5                   |
//+------------------------------------------------------------------+
LogLevel Logger::g_min_log_level = LOG_INFO;
int      Logger::g_file_handle   = INVALID_HANDLE;
//+------------------------------------------------------------------+
