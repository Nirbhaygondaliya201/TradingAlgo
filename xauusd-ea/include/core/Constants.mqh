//+------------------------------------------------------------------+
//| Constants.mqh                                                    |
//| XAU/USD MT5 Expert Advisor                                       |
//| EA-level compile-time constants.                                 |
//|                                                                  |
//| ARCHITECTURE: Layer 0 (no dependencies except Types.mqh).        |
//| These are compile-time constants, NOT configurable input params. |
//| All user-configurable values live in ConfigManager.mqh.          |
//|                                                                  |
//| Design reference: §MQL5 Project Structure                        |
//| Requirements: 13.7, 14.1                                         |
//+------------------------------------------------------------------+
#pragma once

/// Unique integer identifier for all orders placed by this EA.
/// MUST differ from any other EA running on the same account.
/// Change this value if running multiple instances on separate charts.
#define EA_MAGIC_NUMBER         20260901

/// Human-readable version string — increment on every release.
#define EA_VERSION_STRING       "1.0.0"

/// Integer version used for dependency checks and logging.
#define EA_VERSION_INT          100

/// State file schema version.
/// Increment this whenever the EAState struct layout changes in a
/// backward-incompatible way. The State_Manager uses this to detect
/// stale files and apply migrations (or enter SAFE_MODE if none defined).
/// Requirement 19.5
#define STATE_FILE_VERSION      1

/// Name of the SAFE_MODE sentinel file written alongside the state file.
/// When this file exists on disk the EA will refuse to start without
/// manual deletion by the trader. Requirement 19.4
#define SAFE_MODE_FLAG_FILENAME "xauusd_ea_safemode.flag"

/// Maximum number of consecutive freeze-level skips for a position
/// that is missing its mandatory protective stop-loss before the
/// Order_Executor force-closes the position. Requirements 10.13, 10.14
#define DEFAULT_MAX_FREEZE_SKIPS 5

/// Supported MT5 timeframe identifiers used as array indices and
/// log keys throughout the EA. Mirrors MT5 ENUM_TIMEFRAMES values
/// but aliased for documentation clarity.
#define TF_4H   PERIOD_H4
#define TF_1H   PERIOD_H1
#define TF_15M  PERIOD_M15
#define TF_5M   PERIOD_M5

/// Number of distinct timeframes used by this EA.
#define EA_TIMEFRAME_COUNT  4

/// Minimum number of OHLCV bars required at initialisation before
/// the ATR baseline calculation can proceed. Requirement 5.6
#define ATR_BASELINE_MIN_BARS   14

/// Full 30-day baseline window in 1H bars (30 days × 24 hours).
/// Requirement 5.1
#define ATR_BASELINE_WINDOW_BARS 720
//+------------------------------------------------------------------+
