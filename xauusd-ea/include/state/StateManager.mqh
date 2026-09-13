//+------------------------------------------------------------------+
//| StateManager.mqh                                                 |
//| XAU/USD MT5 Expert Advisor                                       |
//| Persistent state management with CRC32 integrity.               |
//|                                                                  |
//| ARCHITECTURE: Cross-cutting service (Layer 0).                  |
//| Provides persistence/recovery infrastructure ONLY.              |
//| Must NOT: detect liquidity, calculate BOS/CHOCH, generate       |
//|           entries, size positions, send/modify/close orders,    |
//|           call strategy logic, or access MT5 market data        |
//|           except for account-identity context validation.        |
//|                                                                  |
//| STATE FILE FORMAT (BLOCKER-4 resolved):                         |
//|   Plain-text UTF-8, one KEY=VALUE per line.                     |
//|   [POOL_REGISTRY] ... [END_POOL_REGISTRY] CSV section.          |
//|   Final line: CHECKSUM=<CRC32 hex of all preceding lines>.      |
//|   See design §2.13 for full specification.                      |
//|                                                                  |
//| SAFE_MODE: entered on any integrity failure.                    |
//|   Blocks new trade entries.                                     |
//|   Logs CRITICAL alert.                                          |
//|   Writes sentinel flag file.                                    |
//|   Requires manual intervention to exit.                         |
//|                                                                  |
//| ATOMIC SAVE: write to .tmp, rename to final path.              |
//|                                                                  |
//| Design reference: §2.13 State_Manager                          |
//| Requirements: 11.1–11.9, 17.2, 17.3, 19.1–19.10               |
//| Correctness Properties: 22, 23, 30                              |
//+------------------------------------------------------------------+
#pragma once
#include "../core/Types.mqh"
#include "../core/Constants.mqh"
#include "../utils/Logger.mqh"

//+------------------------------------------------------------------+
//| StateLoadResult — outcome of a LoadState() call                 |
//+------------------------------------------------------------------+
enum StateLoadResult
{
    LOAD_OK            = 0,  // State loaded and validated successfully
    LOAD_FRESH_START   = 1,  // No state file; EA starting fresh (first run)
    LOAD_SAFE_MODE     = 2,  // State untrusted → SAFE_MODE entered
    LOAD_INIT_FAILED   = 3   // circuit_breaker_triggered=true → INIT_FAILED
};

//+------------------------------------------------------------------+
//| StateManager                                                     |
//+------------------------------------------------------------------+
class StateManager
{
public:
    //------------------------------------------------------------------
    // LoadState
    // Call once in OnInit(). Implements the 10-step restart recovery
    // sequence from design §2.13.
    //
    // Returns:
    //   LOAD_OK          → state restored; EA may proceed normally
    //   LOAD_FRESH_START → no prior state; EA starts with defaults
    //   LOAD_SAFE_MODE   → integrity/identity failure; block new trades
    //   LOAD_INIT_FAILED → circuit breaker was triggered; INIT_FAILED
    //
    // Populates g_EAState on LOAD_OK / LOAD_FRESH_START.
    // Sets g_EAState.safe_mode_active = true on LOAD_SAFE_MODE.
    //------------------------------------------------------------------
    static StateLoadResult LoadState(const string symbol,
                                     const string state_file_path)
    {
        s_state_file_path = state_file_path;
        s_symbol          = symbol;
        s_account_suffix  = GetAccountSuffix();

        string tmp_path = state_file_path + ".tmp";

        // Step 1: prefer .tmp if it exists and passes CRC32
        if(FileIsExist(tmp_path))
        {
            EAState tmp_state = {};
            LiquidityPool tmp_pools[];
            string tmp_err = "";
            if(ReadAndValidateFile(tmp_path, symbol, s_account_suffix,
                                   tmp_state, tmp_pools, tmp_err))
            {
                Logger::Info("StateManager", "LOAD_FROM_TMP",
                    "tmp_file_valid=true fallback_used=false");
                g_EAState  = tmp_state;
                CopyPools(tmp_pools, g_PoolRegistry);
                // Promote tmp → main (atomic rename)
                if(FileMove(tmp_path, 0, state_file_path, FILE_REWRITE))
                    Logger::Debug("StateManager", "TMP_PROMOTED", "");
                return PostLoadCheck();
            }
            else
            {
                Logger::Warn("StateManager", "TMP_INVALID",
                    "reason=" + tmp_err + " falling_back_to_main=true");
            }
        }

        // Step 2: read main state file
        if(!FileIsExist(state_file_path))
        {
            // No prior state — fresh start
            Logger::Info("StateManager", "FRESH_START",
                "no_prior_state_file path=" + state_file_path);
            InitDefaultState(symbol);
            return LOAD_FRESH_START;
        }

        EAState loaded_state = {};
        LiquidityPool loaded_pools[];
        string err_reason = "";
        bool valid = ReadAndValidateFile(state_file_path, symbol,
                                         s_account_suffix,
                                         loaded_state, loaded_pools,
                                         err_reason);

        if(!valid)
        {
            // Step 3: any validation failure → SAFE_MODE
            return EnterSafeMode("LOAD_VALIDATION_FAILED",
                                  "reason=" + err_reason);
        }

        g_EAState = loaded_state;
        CopyPools(loaded_pools, g_PoolRegistry);

        // Step 4: circuit breaker requires INIT_FAILED
        if(g_EAState.circuit_breaker_triggered)
        {
            Logger::Critical("StateManager", "CIRCUIT_BREAKER_SET",
                "circuit_breaker_triggered=1 action=INIT_FAILED");
            return LOAD_INIT_FAILED;
        }

        // Step 5: safe_mode_active persisted from prior session
        if(g_EAState.safe_mode_active)
        {
            return EnterSafeMode("PRIOR_SAFE_MODE",
                                  "safe_mode_active=1 in_state_file");
        }

        // Step 9: day-change check — reset daily accumulator if new day
        AdjustForDayChange();

        Logger::Info("StateManager", "LOAD_OK",
            StringFormat("symbol=%s daily_dd=%.4f total_ref=%.2f"
                         " consecutive=%d cooldown=%s cb=%d",
                         symbol,
                         g_EAState.daily_drawdown_pct,
                         g_EAState.total_drawdown_ref_equity,
                         g_EAState.consecutive_losses,
                         g_EAState.cooldown_start_utc == 0
                             ? "none"
                             : TimeToISO(g_EAState.cooldown_start_utc),
                         (int)g_EAState.circuit_breaker_triggered));
        return LOAD_OK;
    }

    //------------------------------------------------------------------
    // SaveState
    // Atomically persist the current g_EAState and pool registry.
    // Write to .tmp, validate, rename to final path.
    // On rename failure: log ERROR, retain previous file.
    // Requirements 19.7
    //------------------------------------------------------------------
    static bool SaveState()
    {
        if(s_state_file_path == "")
        {
            Logger::Error("StateManager", "SAVE_NO_PATH",
                "state_file_path not set");
            return false;
        }

        g_EAState.last_update_utc     = TimeGMT();
        g_EAState.state_file_version  = STATE_FILE_VERSION;
        g_EAState.symbol              = s_symbol;
        g_EAState.account_suffix      = s_account_suffix;

        string tmp_path = s_state_file_path + ".tmp";

        if(!WriteStateFile(tmp_path, g_EAState, g_PoolRegistry))
        {
            Logger::Error("StateManager", "SAVE_WRITE_FAILED",
                "tmp_path=" + tmp_path);
            return false;
        }

        // Rename .tmp → final path
        if(!FileMove(tmp_path, 0, s_state_file_path, FILE_REWRITE))
        {
            Logger::Error("StateManager", "SAVE_RENAME_FAILED",
                StringFormat("tmp=%s final=%s err=%d",
                             tmp_path, s_state_file_path, GetLastError()));
            return false;
        }

        Logger::Debug("StateManager", "SAVE_OK",
            StringFormat("path=%s ts=%s",
                         s_state_file_path,
                         TimeToISO(g_EAState.last_update_utc)));
        return true;
    }

    //------------------------------------------------------------------
    // IsInSafeMode
    //------------------------------------------------------------------
    static bool IsInSafeMode()
    {
        return g_EAState.safe_mode_active;
    }

    //------------------------------------------------------------------
    // GetState / SetState helpers
    //------------------------------------------------------------------
    static const EAState* GetState()  { return &g_EAState; }
    static EAState* GetStateMutable() { return &g_EAState; }

    static void SetSafeModeActive(bool val)
    {
        g_EAState.safe_mode_active = val;
        SaveState();
    }
    static void SetCircuitBreakerTriggered(bool val)
    {
        g_EAState.circuit_breaker_triggered = val;
        SaveState();
    }
    static void UpdateDailyDrawdown(double pct)
    {
        g_EAState.daily_drawdown_pct = pct;
        SaveState();
    }
    static void UpdateTotalDrawdownRef(double equity)
    {
        g_EAState.total_drawdown_ref_equity = equity;
        SaveState();
    }
    static void UpdateConsecutiveLosses(int count)
    {
        g_EAState.consecutive_losses = count;
        SaveState();
    }
    static void SetCooldownStart(datetime dt)
    {
        g_EAState.cooldown_start_utc = dt;
        SaveState();
    }

    //------------------------------------------------------------------
    // ComputeCRC32
    // CRC32b over the UTF-8 bytes of the payload string.
    // This is the canonical CRC32 (polynomial 0xEDB88320, reflected).
    // Correctness Property 30.
    //------------------------------------------------------------------
    static uint ComputeCRC32(const string payload)
    {
        uint crc = 0xFFFFFFFF;
        int  len = StringLen(payload);
        for(int i = 0; i < len; i++)
        {
            uchar b = (uchar)(StringGetCharacter(payload, i) & 0xFF);
            crc ^= b;
            for(int j = 0; j < 8; j++)
            {
                if((crc & 1) != 0)
                    crc = (crc >> 1) ^ 0xEDB88320;
                else
                    crc = crc >> 1;
            }
        }
        return crc ^ 0xFFFFFFFF;
    }

    //------------------------------------------------------------------
    // PoolRegistry access
    //------------------------------------------------------------------
    static LiquidityPool g_PoolRegistry[];
    static int           GetPoolCount() { return ArraySize(g_PoolRegistry); }
    static void          ClearPools()   { ArrayResize(g_PoolRegistry, 0); }
    static void          AddPool(const LiquidityPool& pool)
    {
        int n = ArraySize(g_PoolRegistry);
        ArrayResize(g_PoolRegistry, n + 1);
        g_PoolRegistry[n] = pool;
    }

    //------------------------------------------------------------------
    // Global state instance
    //------------------------------------------------------------------
    static EAState g_EAState;

private:
    static string s_state_file_path;
    static string s_symbol;
    static string s_account_suffix;

    //------------------------------------------------------------------
    // GetAccountSuffix — last 4 digits of account number
    // Never logs the full account number (masking rules).
    //------------------------------------------------------------------
    static string GetAccountSuffix()
    {
        long acct = AccountInfoInteger(ACCOUNT_LOGIN);
        string full = (string)acct;
        int len = StringLen(full);
        if(len <= 4) return full;
        return StringSubstr(full, len - 4, 4);
    }

    //------------------------------------------------------------------
    // InitDefaultState — populate g_EAState with safe defaults
    //------------------------------------------------------------------
    static void InitDefaultState(const string symbol)
    {
        g_EAState.daily_drawdown_pct        = 0.0;
        g_EAState.daily_open_equity         = 0.0;
        g_EAState.total_drawdown_ref_equity = 0.0;
        g_EAState.consecutive_losses        = 0;
        g_EAState.cooldown_start_utc        = 0;
        g_EAState.circuit_breaker_triggered = false;
        g_EAState.safe_mode_active          = false;
        g_EAState.last_update_utc           = TimeGMT();
        g_EAState.state_file_version        = STATE_FILE_VERSION;
        g_EAState.symbol                    = symbol;
        g_EAState.account_suffix            = s_account_suffix;
        g_EAState.checksum                  = 0;
        ArrayResize(g_PoolRegistry, 0);
    }

    //------------------------------------------------------------------
    // PostLoadCheck — checks after successful validation
    //------------------------------------------------------------------
    static StateLoadResult PostLoadCheck()
    {
        if(g_EAState.circuit_breaker_triggered)
        {
            Logger::Critical("StateManager", "CIRCUIT_BREAKER_SET",
                "circuit_breaker=1 action=INIT_FAILED");
            return LOAD_INIT_FAILED;
        }
        if(g_EAState.safe_mode_active)
            return EnterSafeMode("PRIOR_SAFE_MODE", "safe_mode_active=1");

        AdjustForDayChange();
        Logger::Info("StateManager", "LOAD_OK_FROM_TMP", "");
        return LOAD_OK;
    }

    //------------------------------------------------------------------
    // AdjustForDayChange — reset daily accumulator if new trading day
    //------------------------------------------------------------------
    static void AdjustForDayChange()
    {
        if(g_EAState.last_update_utc == 0) return;
        MqlDateTime last_dt, now_dt;
        TimeToStruct(g_EAState.last_update_utc, last_dt);
        TimeToStruct(TimeGMT(), now_dt);
        // Different calendar day → reset daily accumulator
        if(last_dt.year != now_dt.year ||
           last_dt.mon  != now_dt.mon  ||
           last_dt.day  != now_dt.day)
        {
            Logger::Info("StateManager", "DAY_CHANGE_RESET",
                StringFormat("last=%04d-%02d-%02d now=%04d-%02d-%02d",
                             last_dt.year, last_dt.mon, last_dt.day,
                             now_dt.year,  now_dt.mon,  now_dt.day));
            g_EAState.daily_drawdown_pct = 0.0;
            g_EAState.daily_open_equity  = 0.0;
        }
    }

    //------------------------------------------------------------------
    // EnterSafeMode — centralised SAFE_MODE entry point
    //------------------------------------------------------------------
    static StateLoadResult EnterSafeMode(const string event_type,
                                          const string fields)
    {
        g_EAState.safe_mode_active = true;
        Logger::Critical("StateManager", event_type,
            "safe_mode=ENTERED " + fields);
        // Write sentinel flag file
        int flag = FileOpen(SAFE_MODE_FLAG_FILENAME,
                            FILE_WRITE | FILE_TXT | FILE_ANSI);
        if(flag != INVALID_HANDLE)
        {
            FileWriteString(flag, "safe_mode=1\n");
            FileClose(flag);
        }
        return LOAD_SAFE_MODE;
    }

    //------------------------------------------------------------------
    // TimeToISO — format datetime as ISO 8601 UTC string
    //------------------------------------------------------------------
    static string TimeToISO(datetime dt)
    {
        if(dt == 0) return "0";
        MqlDateTime t;
        TimeToStruct(dt, t);
        return StringFormat("%04d-%02d-%02dT%02d:%02d:%02dZ",
            t.year, t.mon, t.day, t.hour, t.min, t.sec);
    }

    //------------------------------------------------------------------
    // ISOToTime — parse ISO 8601 UTC string to datetime
    // Returns 0 for the literal string "0" or on parse failure.
    //------------------------------------------------------------------
    static datetime ISOToTime(const string s)
    {
        if(s == "0" || StringLen(s) == 0) return 0;
        // Format: YYYY-MM-DDTHH:MM:SSZ (20 chars)
        if(StringLen(s) < 19) return 0;
        MqlDateTime dt = {};
        string cleaned = s;
        StringReplace(cleaned, "T", "-");
        StringReplace(cleaned, ":", "-");
        StringReplace(cleaned, "Z", "");
        string parts[];
        if(StringSplit(cleaned, '-', parts) < 6) return 0;
        dt.year  = (int)parts[0];
        dt.mon   = (int)parts[1];
        dt.day   = (int)parts[2];
        dt.hour  = (int)parts[3];
        dt.min   = (int)parts[4];
        dt.sec   = (int)parts[5];
        if(dt.year < 1970 || dt.mon < 1 || dt.mon > 12 ||
           dt.day  < 1    || dt.day  > 31)
            return 0;
        return StructToTime(dt);
    }

    //------------------------------------------------------------------
    // BuildPayload
    // Constructs the text payload that the CRC32 is computed over.
    // All lines from VERSION= up to (not including) CHECKSUM=.
    //------------------------------------------------------------------
    static string BuildPayload(const EAState& st,
                                const LiquidityPool& pools[])
    {
        string p = "";
        p += "VERSION="                + (string)EA_VERSION_INT         + "\n";
        p += "SCHEMA="                 + (string)st.state_file_version   + "\n";
        p += "TIMESTAMP_UTC="          + TimeToISO(st.last_update_utc)   + "\n";
        p += "SYMBOL="                 + st.symbol                       + "\n";
        p += "ACCOUNT_SUFFIX="         + st.account_suffix               + "\n";
        p += "DAILY_DRAWDOWN_PCT="     + DoubleToString(st.daily_drawdown_pct, 10)       + "\n";
        p += "DAILY_OPEN_EQUITY="      + DoubleToString(st.daily_open_equity, 10)        + "\n";
        p += "TOTAL_DRAWDOWN_REF_EQUITY=" + DoubleToString(st.total_drawdown_ref_equity, 10) + "\n";
        p += "CONSECUTIVE_LOSSES="     + (string)st.consecutive_losses   + "\n";
        p += "COOLDOWN_START_UTC="     + TimeToISO(st.cooldown_start_utc) + "\n";
        p += "CIRCUIT_BREAKER_TRIGGERED=" + (st.circuit_breaker_triggered ? "1" : "0") + "\n";
        p += "SAFE_MODE_ACTIVE="       + (st.safe_mode_active ? "1" : "0") + "\n";

        // Pool registry section
        p += "[POOL_REGISTRY]\n";
        int n = ArraySize(pools);
        for(int i = 0; i < n; i++)
        {
            string status_str;
            switch(pools[i].status)
            {
                case POOL_ACTIVE:      status_str = "ACTIVE";      break;
                case POOL_SWEPT:       status_str = "SWEPT";       break;
                case POOL_INVALIDATED: status_str = "INVALIDATED"; break;
                default:               status_str = "ACTIVE";      break;
            }
            string side_str = (pools[i].side == POOL_SIDE_ABOVE) ? "ABOVE" : "BELOW";
            p += StringFormat("%d,%.10f,%.10f,%s,%s,%s,%s\n",
                i,
                pools[i].price_level,
                pools[i].tolerance_band,
                status_str,
                side_str,
                TimeToISO(pools[i].created_timestamp),
                TimeToISO(pools[i].swept_timestamp));
        }
        p += "[END_POOL_REGISTRY]\n";
        return p;
    }

    //------------------------------------------------------------------
    // WriteStateFile — writes payload + CHECKSUM to file_path
    //------------------------------------------------------------------
    static bool WriteStateFile(const string file_path,
                                const EAState& st,
                                const LiquidityPool& pools[])
    {
        string payload  = BuildPayload(st, pools);
        uint   crc32    = ComputeCRC32(payload);
        string full_content = payload +
            "CHECKSUM=" + StringFormat("%08X", crc32) + "\n";

        int handle = FileOpen(file_path,
                              FILE_WRITE | FILE_TXT | FILE_ANSI);
        if(handle == INVALID_HANDLE)
        {
            Logger::Error("StateManager", "FILE_OPEN_FAILED",
                "path=" + file_path + " err=" + (string)GetLastError());
            return false;
        }
        FileWriteString(handle, full_content);
        FileFlush(handle);
        FileClose(handle);
        return true;
    }

    //------------------------------------------------------------------
    // ReadAndValidateFile
    // Reads file, verifies CRC32, schema, symbol, account suffix.
    // Populates state_out and pools_out on success.
    // Returns false and sets err_out on any validation failure.
    //------------------------------------------------------------------
    static bool ReadAndValidateFile(const string file_path,
                                     const string symbol,
                                     const string acct_suffix,
                                     EAState& state_out,
                                     LiquidityPool& pools_out[],
                                     string& err_out)
    {
        err_out = "";
        if(!FileIsExist(file_path))
        {
            err_out = "FILE_NOT_FOUND path=" + file_path;
            return false;
        }

        int handle = FileOpen(file_path, FILE_READ | FILE_TXT | FILE_ANSI);
        if(handle == INVALID_HANDLE)
        {
            err_out = "FILE_OPEN_FAILED err=" + (string)GetLastError();
            return false;
        }

        // Read all lines
        string lines[];
        int line_count = 0;
        while(!FileIsEnding(handle))
        {
            string line = FileReadString(handle);
            if(StringLen(line) == 0 && FileIsEnding(handle)) break;
            ArrayResize(lines, line_count + 1);
            lines[line_count++] = line;
        }
        FileClose(handle);

        if(line_count < 14)  // minimum required lines
        {
            err_out = "TRUNCATED line_count=" + (string)line_count;
            return false;
        }

        // Find CHECKSUM line (must be last non-empty line)
        int checksum_idx = -1;
        for(int i = line_count - 1; i >= 0; i--)
        {
            if(StringFind(lines[i], "CHECKSUM=") == 0)
            {
                checksum_idx = i;
                break;
            }
        }
        if(checksum_idx < 0)
        {
            err_out = "MISSING_CHECKSUM";
            return false;
        }

        // Reconstruct payload: all lines before CHECKSUM
        string payload = "";
        for(int i = 0; i < checksum_idx; i++)
            payload += lines[i] + "\n";

        // Verify CRC32
        uint computed_crc = ComputeCRC32(payload);
        string stored_crc_str = StringSubstr(lines[checksum_idx],
                                              StringLen("CHECKSUM="));
        uint stored_crc = (uint)StringToInteger("0x" + stored_crc_str);

        if(computed_crc != stored_crc)
        {
            err_out = StringFormat("CRC32_MISMATCH computed=%08X stored=%08X",
                                   computed_crc, stored_crc);
            return false;
        }

        // Parse key-value pairs from payload lines
        EAState st = {};
        ArrayResize(pools_out, 0);
        bool in_pool_section = false;
        int  pool_idx = 0;

        for(int i = 0; i < checksum_idx; i++)
        {
            string line = lines[i];

            if(line == "[POOL_REGISTRY]")   { in_pool_section = true;  continue; }
            if(line == "[END_POOL_REGISTRY]"){ in_pool_section = false; continue; }

            if(in_pool_section)
            {
                string fields[];
                if(StringSplit(line, ',', fields) >= 7)
                {
                    LiquidityPool pool = {};
                    pool.price_level      = StringToDouble(fields[1]);
                    pool.tolerance_band   = StringToDouble(fields[2]);
                    string status_s = fields[3];
                    if(status_s == "ACTIVE")      pool.status = POOL_ACTIVE;
                    else if(status_s == "SWEPT")  pool.status = POOL_SWEPT;
                    else                          pool.status = POOL_INVALIDATED;
                    pool.side             = (fields[4] == "ABOVE")
                                               ? POOL_SIDE_ABOVE
                                               : POOL_SIDE_BELOW;
                    pool.created_timestamp = ISOToTime(fields[5]);
                    pool.swept_timestamp   = ISOToTime(fields[6]);
                    ArrayResize(pools_out, pool_idx + 1);
                    pools_out[pool_idx++] = pool;
                }
                continue;
            }

            // Parse KEY=VALUE
            int eq = StringFind(line, "=");
            if(eq < 1) continue;
            string key = StringSubstr(line, 0, eq);
            string val = StringSubstr(line, eq + 1);

            if(key == "VERSION")        { /* informational only */ }
            else if(key == "SCHEMA")
            {
                int schema = (int)StringToInteger(val);
                if(schema > STATE_FILE_VERSION)
                {
                    err_out = "SCHEMA_TOO_NEW file=" + (string)schema +
                              " current=" + (string)STATE_FILE_VERSION;
                    return false;
                }
                st.state_file_version = schema;
            }
            else if(key == "TIMESTAMP_UTC")
                st.last_update_utc = ISOToTime(val);
            else if(key == "SYMBOL")
            {
                if(val != symbol)
                {
                    err_out = "SYMBOL_MISMATCH file=" + val +
                              " expected=" + symbol;
                    return false;
                }
                st.symbol = val;
            }
            else if(key == "ACCOUNT_SUFFIX")
            {
                if(acct_suffix != "" && val != acct_suffix)
                {
                    err_out = "ACCOUNT_SUFFIX_MISMATCH";
                    return false;
                }
                st.account_suffix = val;
            }
            else if(key == "DAILY_DRAWDOWN_PCT")
            {
                double v = StringToDouble(val);
                if(v < 0.0 || v > 100.0)
                {
                    err_out = "INVALID_DAILY_DD val=" + val;
                    return false;
                }
                st.daily_drawdown_pct = v;
            }
            else if(key == "DAILY_OPEN_EQUITY")
                st.daily_open_equity = StringToDouble(val);
            else if(key == "TOTAL_DRAWDOWN_REF_EQUITY")
                st.total_drawdown_ref_equity = StringToDouble(val);
            else if(key == "CONSECUTIVE_LOSSES")
            {
                int v = (int)StringToInteger(val);
                if(v < 0 || v > 1000)
                {
                    err_out = "INVALID_CONSECUTIVE_LOSSES val=" + val;
                    return false;
                }
                st.consecutive_losses = v;
            }
            else if(key == "COOLDOWN_START_UTC")
                st.cooldown_start_utc = ISOToTime(val);
            else if(key == "CIRCUIT_BREAKER_TRIGGERED")
                st.circuit_breaker_triggered = (val == "1");
            else if(key == "SAFE_MODE_ACTIVE")
                st.safe_mode_active = (val == "1");
        }

        // Re-derive stored checksum into struct
        st.checksum = stored_crc;

        state_out = st;
        return true;
    }

    //------------------------------------------------------------------
    // CopyPools helper
    //------------------------------------------------------------------
    static void CopyPools(const LiquidityPool& src[], LiquidityPool& dst[])
    {
        int n = ArraySize(src);
        ArrayResize(dst, n);
        for(int i = 0; i < n; i++) dst[i] = src[i];
    }
};

//+------------------------------------------------------------------+
//| Static member definitions                                        |
//+------------------------------------------------------------------+
EAState       StateManager::g_EAState       = {};
LiquidityPool StateManager::g_PoolRegistry[];
string        StateManager::s_state_file_path = "";
string        StateManager::s_symbol           = "";
string        StateManager::s_account_suffix   = "";
//+------------------------------------------------------------------+
