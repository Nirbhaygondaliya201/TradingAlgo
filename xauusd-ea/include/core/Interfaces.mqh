//+------------------------------------------------------------------+
//| Interfaces.mqh                                                   |
//| XAU/USD MT5 Expert Advisor                                       |
//| Abstract interface contracts for each module.                    |
//|                                                                  |
//| ARCHITECTURE: Layer 0 (depends only on Types.mqh).               |
//| Modules communicate only through these interfaces and the        |
//| data structures defined in Types.mqh. No module may reference    |
//| the concrete implementation of another module directly.          |
//|                                                                  |
//| MQL5 does not have Java/C#-style interfaces with enforced        |
//| compile-time contracts, so these are documented as abstract      |
//| base classes with pure virtual methods. Concrete modules inherit |
//| from the appropriate interface.                                  |
//|                                                                  |
//| Design reference: §Module Boundary Definitions, §2.x sections   |
//| Requirements: 13.1, 13.2, 13.3, 13.4, 13.5                      |
//+------------------------------------------------------------------+
#pragma once
#include "Types.mqh"

//+------------------------------------------------------------------+
//| IAnalysisModule                                                  |
//| Contract for all analysis engines that feed the                  |
//| Entry_Confirmation_Engine via AnalysisStatus objects.            |
//| Covers: Market_Structure_Analyzer, Liquidity_Detector,           |
//|          ATR_Volatility_Engine, Momentum_Engine.                 |
//| Requirements: 13.2                                               |
//+------------------------------------------------------------------+
class IAnalysisModule
{
public:
    /// Update internal state from confirmed-candle data.
    /// Implementations must only read from bar index >= 1 (never bar 0).
    /// Correctness Property 1.
    virtual void      Update()                              = 0;

    /// Return the latest AnalysisStatus for consumption by the
    /// Entry_Confirmation_Engine. Must be deterministic given the same input.
    virtual AnalysisStatus GetStatus()                      = 0;

    /// Returns true if the module has sufficient data to produce a valid result.
    /// When false, callers treat the output as SIGNAL_UNKNOWN.
    virtual bool      IsReady()                 const       = 0;

    virtual           ~IAnalysisModule()                    {}
};

//+------------------------------------------------------------------+
//| IFilterModule                                                    |
//| Contract for all gate filters that return ALLOWED, BLOCKED,      |
//| or WARN status to the Entry_Confirmation_Engine.                 |
//| Covers: Session_Filter, Spread_Filter, News_Filter.             |
//| Requirements: 13.2                                               |
//+------------------------------------------------------------------+
class IFilterModule
{
public:
    /// Evaluate current conditions and return ALLOWED, BLOCKED, or WARN.
    /// Must not cache state across calls for time-sensitive filters
    /// (e.g., Spread_Filter re-reads symbol info on every call).
    virtual AnalysisStatus Evaluate()                       = 0;

    virtual               ~IFilterModule()                  {}
};

//+------------------------------------------------------------------+
//| IRiskManager                                                     |
//| Contract for the Risk_Manager.                                   |
//| Receives a TradeSignal; returns either an approved TradeOrder    |
//| or a RejectionResult. Has no knowledge of order submission.      |
//| Requirements: 13.4, 9.9                                          |
//+------------------------------------------------------------------+
class IRiskManager
{
public:
    /// Validate signal, calculate position size, enforce all limits.
    /// Returns true and populates order on approval.
    /// Returns false and populates rejection on any validation failure.
    virtual bool Evaluate(
        const TradeSignal& signal,
        TradeOrder&        order_out,
        RejectionResult&   rejection_out
    )                                                       = 0;

    virtual      ~IRiskManager()                            {}
};

//+------------------------------------------------------------------+
//| IOrderExecutor                                                   |
//| Contract for the Order_Executor — the only module permitted to  |
//| call OrderSend, OrderModify, OrderClose.                         |
//| Requirements: 13.5, 10.1                                         |
//+------------------------------------------------------------------+
class IOrderExecutor
{
public:
    /// Submit a validated TradeOrder to the broker.
    /// Performs spread check, pre-submission validation,
    /// post-fill verification, and retry on non-fatal errors.
    virtual ExecutionResult Submit(const TradeOrder& order) = 0;

    /// Monitor all open EA-managed positions.
    /// Re-attaches missing SLs; force-closes on re-attach failure;
    /// applies freeze-level skip logic per Requirements 10.13, 10.14.
    virtual void            MonitorPositions()              = 0;

    virtual                 ~IOrderExecutor()               {}
};

//+------------------------------------------------------------------+
//| IStateManager                                                    |
//| Contract for the State_Manager.                                  |
//| Provides persistent state across terminal restarts.              |
//| Requirements: 11.1, 11.4, 11.6, 19.1                            |
//+------------------------------------------------------------------+
class IStateManager
{
public:
    /// Load and validate state from disk on EA initialisation.
    /// Returns false and enters SAFE_MODE on any integrity failure.
    virtual bool  LoadState(EAState& state_out)             = 0;

    /// Persist the current state to disk atomically.
    /// Writes to .tmp then renames. Requirements 19.7
    virtual bool  SaveState(const EAState& state)           = 0;

    /// Returns true if the EA is currently in SAFE_MODE.
    virtual bool  IsInSafeMode()                const       = 0;

    virtual       ~IStateManager()                          {}
};
//+------------------------------------------------------------------+
