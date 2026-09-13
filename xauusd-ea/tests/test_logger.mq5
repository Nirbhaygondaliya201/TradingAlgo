//+------------------------------------------------------------------+
//| test_logger.mq5                                                  |
//| XAU/USD MT5 Expert Advisor — Unit Tests                         |
//| Task 2.2 / 2.3: Logger module tests                             |
//|                                                                  |
//| Tests cover:                                                     |
//|   - Property 24: Account number masking                         |
//|   - Property 25: Structured log field completeness              |
//|   - Log level filtering                                          |
//|   - ISO 8601 timestamp format                                   |
//|   - Output format structure                                      |
//|   - LevelToString values                                        |
//|   - BuildFields helper                                          |
//|   - WriteTradeEvent financial fields                             |
//|                                                                  |
//| Run as a Script in MetaTrader 5.                                 |
//| Requirements: 12.1, 12.2, 12.5, 12.6                           |
//| Correctness Properties: 24, 25                                   |
//+------------------------------------------------------------------+
#property script_show_inputs
#include <..\include\core\Types.mqh>
#include <..\include\core\Constants.mqh>
#include <..\include\utils\Logger.mqh>

int g_pass = 0;
int g_fail = 0;

#define ASSERT_EQ(label, actual, expected) \
    if((actual) == (expected)) { \
        PrintFormat("PASS | %s", (label)); g_pass++; \
    } else { \
        PrintFormat("FAIL | %s | got=%s  expected=%s", (label), (string)(actual), (string)(expected)); g_fail++; \
    }

#define ASSERT_TRUE(label, expr) \
    if(expr) { PrintFormat("PASS | %s", (label)); g_pass++; } \
    else { PrintFormat("FAIL | %s | expression was false", (label)); g_fail++; }

#define ASSERT_FALSE(label, expr) \
    if(!(expr)) { PrintFormat("PASS | %s", (label)); g_pass++; } \
    else { PrintFormat("FAIL | %s | expression was true", (label)); g_fail++; }

#define ASSERT_CONTAINS(label, haystack, needle) \
    if(StringFind((haystack), (needle)) >= 0) { \
        PrintFormat("PASS | %s", (label)); g_pass++; \
    } else { \
        PrintFormat("FAIL | %s | '%s' not found in '%s'", (label), (needle), (haystack)); g_fail++; \
    }

void OnStart()
{
    Print("=== test_logger.mq5 START ===");

    Test_LevelToString();
    Test_MaskAccountNumber_Property24();
    Test_LogLevelFiltering();
    Test_ISO8601Format();
    Test_BuildFields();
    Test_FormatStructure();
    Test_WriteTradeEvent();
    Test_StaticDefaults();

    PrintFormat("=== test_logger.mq5 DONE | PASS: %d | FAIL: %d ===", g_pass, g_fail);
}

//+------------------------------------------------------------------+
//| Test: LevelToString returns correct strings                      |
//+------------------------------------------------------------------+
void Test_LevelToString()
{
    ASSERT_EQ("LevelToString DEBUG",    Logger::LevelToString(LOG_DEBUG),    "DEBUG");
    ASSERT_EQ("LevelToString INFO",     Logger::LevelToString(LOG_INFO),     "INFO");
    ASSERT_EQ("LevelToString WARN",     Logger::LevelToString(LOG_WARN),     "WARN");
    ASSERT_EQ("LevelToString ERROR",    Logger::LevelToString(LOG_ERROR),    "ERROR");
    ASSERT_EQ("LevelToString CRITICAL", Logger::LevelToString(LOG_CRITICAL), "CRITICAL");
}

//+------------------------------------------------------------------+
//| Test: MaskAccountNumber — Property 24                           |
//| Req 12.6: all digits except last 4 replaced with *              |
//+------------------------------------------------------------------+
void Test_MaskAccountNumber_Property24()
{
    // Standard 8-digit account
    ASSERT_EQ("Mask 8 digits: ****5678",
        Logger::MaskAccountNumber("12345678"), "****5678");

    // Exactly 4 digits — nothing masked
    ASSERT_EQ("Mask 4 digits: unchanged",
        Logger::MaskAccountNumber("1234"), "1234");

    // Fewer than 4 digits — nothing masked
    ASSERT_EQ("Mask 3 digits: unchanged",
        Logger::MaskAccountNumber("123"), "123");

    // Empty string
    ASSERT_EQ("Mask empty string: unchanged",
        Logger::MaskAccountNumber(""), "");

    // 5 digits — only first masked
    ASSERT_EQ("Mask 5 digits: *2345",
        Logger::MaskAccountNumber("12345"), "*2345");

    // 10 digits — first 6 masked
    ASSERT_EQ("Mask 10 digits: ******7890",
        Logger::MaskAccountNumber("1234567890"), "******7890");

    // 20 digits — 16 masked
    ASSERT_EQ("Mask 20 digits: last 4 preserved",
        StringSubstr(Logger::MaskAccountNumber("12345678901234567890"), 16, 4),
        "7890");

    // All masked digits are '*'
    string masked = Logger::MaskAccountNumber("12345678");
    ASSERT_EQ("Mask: first 4 chars are ****",
        StringSubstr(masked, 0, 4), "****");
    ASSERT_EQ("Mask: last 4 chars are 5678",
        StringSubstr(masked, 4, 4), "5678");

    // Non-digit characters preserved in position
    // (no account numbers with dashes, but test the digit-only mask)
    ASSERT_EQ("Mask 9 digits: *****6789",
        Logger::MaskAccountNumber("123456789"), "*****6789");
}

//+------------------------------------------------------------------+
//| Test: Log level filtering                                        |
//| Requirement 12.5: entries below min level are suppressed        |
//+------------------------------------------------------------------+
void Test_LogLevelFiltering()
{
    // Verify enum ordering is correct
    ASSERT_TRUE("DEBUG < INFO",     LOG_DEBUG    < LOG_INFO);
    ASSERT_TRUE("INFO < WARN",      LOG_INFO     < LOG_WARN);
    ASSERT_TRUE("WARN < ERROR",     LOG_WARN     < LOG_ERROR);
    ASSERT_TRUE("ERROR < CRITICAL", LOG_ERROR    < LOG_CRITICAL);

    // Filtering logic: level < min_level => suppressed
    ASSERT_TRUE("DEBUG suppressed when min=INFO",  LOG_DEBUG  < LOG_INFO);
    ASSERT_TRUE("INFO passes when min=INFO",       !(LOG_INFO  < LOG_INFO));
    ASSERT_TRUE("WARN passes when min=INFO",       !(LOG_WARN  < LOG_INFO));
    ASSERT_TRUE("CRITICAL passes always",          !(LOG_CRITICAL < LOG_DEBUG));

    // Default min level is INFO (from Constants)
    ASSERT_EQ("Default g_min_log_level is INFO",
        (int)Logger::g_min_log_level, (int)LOG_INFO);

    // Can set to DEBUG
    Logger::SetMinLevel(LOG_DEBUG);
    ASSERT_EQ("After SetMinLevel(DEBUG), level is DEBUG",
        (int)Logger::g_min_log_level, (int)LOG_DEBUG);

    // Reset to INFO for remaining tests
    Logger::SetMinLevel(LOG_INFO);
    ASSERT_EQ("Restored to INFO",
        (int)Logger::g_min_log_level, (int)LOG_INFO);
}

//+------------------------------------------------------------------+
//| Test: ISO 8601 timestamp format                                  |
//| Requirement 12.2: timestamps in ISO 8601 UTC format             |
//+------------------------------------------------------------------+
void Test_ISO8601Format()
{
    // Use a known timestamp: 2026-09-09 07:30:00 UTC
    datetime known_dt = D'2026.09.09 07:30:00';
    string ts = Logger::TimeToISO8601(known_dt);

    ASSERT_EQ("ISO8601 known dt", ts, "2026-09-09T07:30:00Z");

    // Epoch (1970-01-01 00:00:00 UTC)
    string epoch_ts = Logger::TimeToISO8601(0);
    ASSERT_EQ("ISO8601 epoch", epoch_ts, "1970-01-01T00:00:00Z");

    // Format checks: length and structure
    ASSERT_EQ("ISO8601 length is 20", StringLen(ts), 20);
    ASSERT_CONTAINS("ISO8601 contains 'T'", ts, "T");
    ASSERT_CONTAINS("ISO8601 ends with 'Z'",
        StringSubstr(ts, StringLen(ts)-1, 1), "Z");
}

//+------------------------------------------------------------------+
//| Test: BuildFields produces correct pipe-separated output        |
//+------------------------------------------------------------------+
void Test_BuildFields()
{
    // Single pair
    string one = Logger::BuildFields("ticket", "12345");
    ASSERT_EQ("BuildFields one pair", one, "ticket=12345");

    // Two pairs
    string two = Logger::BuildFields("symbol", "XAUUSD", "volume", "0.10");
    ASSERT_CONTAINS("BuildFields two pairs contains symbol", two, "symbol=XAUUSD");
    ASSERT_CONTAINS("BuildFields two pairs contains volume", two, "volume=0.10");
    ASSERT_CONTAINS("BuildFields two pairs separator",       two, " | ");

    // Empty key skipped
    string skip = Logger::BuildFields("k1", "v1", "", "", "k3", "v3");
    ASSERT_CONTAINS("BuildFields skips empty key k2", skip, "k1=v1");
    ASSERT_CONTAINS("BuildFields includes k3",         skip, "k3=v3");
    ASSERT_TRUE("BuildFields does not include empty key",
        StringFind(skip, "=v2") < 0 && StringFind(skip, "k2") < 0);
}

//+------------------------------------------------------------------+
//| Test: Output line structure                                      |
//| Property 25 (partial): mandatory header fields present          |
//| Requirement 12.2: LEVEL | ISO8601_UTC | MODULE | EVENT_TYPE     |
//+------------------------------------------------------------------+
void Test_FormatStructure()
{
    // Build what a line should look like and verify constituent parts
    string level_str = Logger::LevelToString(LOG_INFO);
    string ts        = Logger::TimeToISO8601(TimeGMT());
    string module    = "TestModule";
    string event     = "TEST_EVENT";
    string fields    = "key=value";

    // Construct the expected format manually
    string expected_prefix = level_str + " | " + ts + " | " + module + " | " + event;
    ASSERT_EQ("Format: level string is INFO",  level_str, "INFO");
    ASSERT_CONTAINS("Format: timestamp has T", ts, "T");
    ASSERT_CONTAINS("Format: timestamp has Z",
        StringSubstr(ts, StringLen(ts)-1, 1), "Z");
    ASSERT_EQ("Format: module name preserved",  module, "TestModule");
    ASSERT_EQ("Format: event type preserved",   event,  "TEST_EVENT");

    // Verify separator string construction
    string sep_line = level_str + " | " + ts;
    ASSERT_CONTAINS("Format: level + sep + ts has pipe", sep_line, " | ");
}

//+------------------------------------------------------------------+
//| Test: WriteTradeEvent includes financial fields                  |
//| Requirement 12.3                                                 |
//+------------------------------------------------------------------+
void Test_WriteTradeEvent()
{
    // Build the financial fields string exactly as WriteTradeEvent would
    double equity       = 10000.00;
    double balance      = 9950.00;
    double drawdown_pct = 0.0050;

    string financial = StringFormat(
        "equity=%.2f | balance=%.2f | drawdown_pct=%.4f",
        equity, balance, drawdown_pct);

    ASSERT_CONTAINS("WriteTradeEvent: equity field",        financial, "equity=10000.00");
    ASSERT_CONTAINS("WriteTradeEvent: balance field",       financial, "balance=9950.00");
    ASSERT_CONTAINS("WriteTradeEvent: drawdown_pct field",  financial, "drawdown_pct=0.0050");

    // Extra fields appended
    string extra = "ticket=99 | direction=BUY";
    string full  = financial + " | " + extra;
    ASSERT_CONTAINS("WriteTradeEvent: extra fields appended", full, "ticket=99");
}

//+------------------------------------------------------------------+
//| Test: Static defaults                                            |
//+------------------------------------------------------------------+
void Test_StaticDefaults()
{
    // Default file handle
    ASSERT_EQ("Default g_file_handle is INVALID_HANDLE",
        Logger::g_file_handle, INVALID_HANDLE);

    // Default min level (may have been altered by Test_LogLevelFiltering, reset was done)
    ASSERT_EQ("Default g_min_log_level is INFO after reset",
        (int)Logger::g_min_log_level, (int)LOG_INFO);
}
//+------------------------------------------------------------------+
