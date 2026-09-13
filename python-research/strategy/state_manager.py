"""
state_manager.py — XAU/USD MT5 EA Python Research Environment
==============================================================
Python mirror of ``include/state/StateManager.mqh``.

Implements the same state file format, CRC32 integrity, SAFE_MODE
semantics, and atomic persistence as the MQL5 implementation.

State file format (BLOCKER-4 resolved — native plain-text KEY=VALUE):
    VERSION=1
    SCHEMA=1
    TIMESTAMP_UTC=2026-09-09T07:30:00Z
    SYMBOL=XAUUSD
    ACCOUNT_SUFFIX=1234
    DAILY_DRAWDOWN_PCT=2.14
    DAILY_OPEN_EQUITY=10000.00
    TOTAL_DRAWDOWN_REF_EQUITY=10000.00
    CONSECUTIVE_LOSSES=1
    COOLDOWN_START_UTC=0
    CIRCUIT_BREAKER_TRIGGERED=0
    SAFE_MODE_ACTIVE=0
    [POOL_REGISTRY]
    0,2950.50,12.30,ACTIVE,ABOVE,2026-09-09T06:00:00Z,0
    [END_POOL_REGISTRY]
    CHECKSUM=A3F29C1D

CRC32 is computed over all lines before the CHECKSUM line.
Atomic save: write to .tmp, then rename.
SAFE_MODE is entered on any integrity failure.

Separation of concerns: this module is persistence/recovery only.
It must NOT detect liquidity, calculate BOS/CHOCH, generate entries,
size positions, or send/modify/close orders.

Design reference: §2.13 State_Manager
Requirements: 11.1–11.9, 17.2, 17.3, 19.1–19.10
Correctness Properties: 22, 23, 30
"""

from __future__ import annotations

import os
import struct
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import List, Optional, Tuple

from strategy.types import EAState, LiquidityPool, PoolStatus, PoolSide

# Current schema version — must match MQL5 STATE_FILE_VERSION
STATE_FILE_VERSION = 1

# Safe-mode sentinel file name
SAFE_MODE_FLAG_FILENAME = "xauusd_ea_safemode.flag"


# ---------------------------------------------------------------------------
# StateLoadResult
# ---------------------------------------------------------------------------

class StateLoadResult(Enum):
    OK           = "OK"           # State loaded and validated
    FRESH_START  = "FRESH_START"  # No prior state; first run
    SAFE_MODE    = "SAFE_MODE"    # Untrusted state — block new trades
    INIT_FAILED  = "INIT_FAILED"  # circuit_breaker_triggered=True


# ---------------------------------------------------------------------------
# StateValidationError
# ---------------------------------------------------------------------------

class StateValidationError(ValueError):
    """Raised when a state file fails validation."""
    def __init__(self, reason: str) -> None:
        super().__init__(f"StateValidation failed: {reason}")
        self.reason = reason


# ---------------------------------------------------------------------------
# CRC32
# ---------------------------------------------------------------------------

def compute_crc32(payload: str) -> int:
    """
    CRC32b over the UTF-8 bytes of payload.
    Matches MQL5 StateManager::ComputeCRC32().
    Returns an unsigned 32-bit integer.
    Correctness Property 30.
    """
    crc = 0xFFFFFFFF
    for ch in payload.encode("utf-8"):
        crc ^= ch
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xEDB88320
            else:
                crc >>= 1
    return (crc ^ 0xFFFFFFFF) & 0xFFFFFFFF


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def _time_to_iso(dt: Optional[datetime]) -> str:
    if dt is None or (isinstance(dt, datetime) and dt == datetime(1970, 1, 1, tzinfo=timezone.utc)):
        return "0"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso_to_time(s: str) -> Optional[datetime]:
    if s == "0" or not s:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
    try:
        # Accept YYYY-MM-DDTHH:MM:SSZ
        s_clean = s.rstrip("Z")
        return datetime.strptime(s_clean, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Payload builder (must be deterministic)
# ---------------------------------------------------------------------------

def build_payload(state: EAState, pools: List[LiquidityPool]) -> str:
    """
    Build the text payload over which CRC32 is computed.
    Every line ends with \\n.
    Order must match MQL5 BuildPayload() exactly.
    """
    lines: List[str] = []
    lines.append(f"VERSION=1")
    lines.append(f"SCHEMA={STATE_FILE_VERSION}")
    lines.append(f"TIMESTAMP_UTC={_time_to_iso(state.last_update_utc)}")
    lines.append(f"SYMBOL={state.symbol}")
    lines.append(f"ACCOUNT_SUFFIX={state.account_suffix}")
    lines.append(f"DAILY_DRAWDOWN_PCT={state.daily_drawdown_pct:.10f}")
    lines.append(f"DAILY_OPEN_EQUITY={state.daily_open_equity:.10f}")
    lines.append(f"TOTAL_DRAWDOWN_REF_EQUITY={state.total_drawdown_ref_equity:.10f}")
    lines.append(f"CONSECUTIVE_LOSSES={state.consecutive_losses}")
    lines.append(f"COOLDOWN_START_UTC={_time_to_iso(state.cooldown_start_utc)}")
    lines.append(f"CIRCUIT_BREAKER_TRIGGERED={'1' if state.circuit_breaker_triggered else '0'}")
    lines.append(f"SAFE_MODE_ACTIVE={'1' if state.safe_mode_active else '0'}")
    lines.append("[POOL_REGISTRY]")
    for i, pool in enumerate(pools):
        status_str = {
            PoolStatus.ACTIVE:      "ACTIVE",
            PoolStatus.SWEPT:       "SWEPT",
            PoolStatus.INVALIDATED: "INVALIDATED",
        }.get(pool.status, "ACTIVE")
        side_str = "ABOVE" if pool.side == PoolSide.ABOVE else "BELOW"
        lines.append(
            f"{i},{pool.price_level:.10f},{pool.tolerance_band:.10f},"
            f"{status_str},{side_str},"
            f"{_time_to_iso(pool.created_timestamp)},"
            f"{_time_to_iso(pool.swept_timestamp)}"
        )
    lines.append("[END_POOL_REGISTRY]")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# StateManager
# ---------------------------------------------------------------------------

class StateManager:
    """
    Persistent state manager for the Python research environment.
    Mirrors MQL5 StateManager semantics exactly.
    """

    def __init__(
        self,
        state_file_path: str | Path,
        symbol: str,
        account_suffix: str = "",
    ) -> None:
        self.state_file_path = Path(state_file_path)
        self.symbol          = symbol
        self.account_suffix  = account_suffix
        self.state           = EAState()
        self.pool_registry:  List[LiquidityPool] = []
        self._safe_mode_reason: str = ""

    # ------------------------------------------------------------------
    # load_state
    # ------------------------------------------------------------------

    def load_state(self) -> StateLoadResult:
        """
        Load and validate state. Returns StateLoadResult.
        Mirrors MQL5 LoadState() 10-step sequence.
        """
        tmp_path = Path(str(self.state_file_path) + ".tmp")

        # Step 1: try .tmp file first
        if tmp_path.exists():
            try:
                st, pools = self._read_and_validate(tmp_path)
                self.state         = st
                self.pool_registry = pools
                # Promote tmp → main
                tmp_path.replace(self.state_file_path)
                return self._post_load_check()
            except StateValidationError as e:
                pass  # Fall through to main file

        # Step 2: try main state file
        if not self.state_file_path.exists():
            self._init_default_state()
            return StateLoadResult.FRESH_START

        try:
            st, pools = self._read_and_validate(self.state_file_path)
        except StateValidationError as e:
            return self._enter_safe_mode(str(e))

        self.state         = st
        self.pool_registry = pools

        # Step 4: circuit breaker
        if self.state.circuit_breaker_triggered:
            return StateLoadResult.INIT_FAILED

        # Step 5: prior safe_mode_active
        if self.state.safe_mode_active:
            return self._enter_safe_mode("PRIOR_SAFE_MODE_ACTIVE")

        # Step 9: day-change
        self._adjust_for_day_change()
        return StateLoadResult.OK

    # ------------------------------------------------------------------
    # save_state
    # ------------------------------------------------------------------

    def save_state(self) -> bool:
        """
        Atomically persist current state.
        Writes to .tmp, then renames to final path.
        Returns True on success.
        """
        now = datetime.now(tz=timezone.utc)
        import dataclasses
        self.state = dataclasses.replace(
            self.state,
            last_update_utc    = now,
            state_file_version = STATE_FILE_VERSION,
            symbol             = self.symbol,
            account_suffix     = self.account_suffix,
        )

        payload  = build_payload(self.state, self.pool_registry)
        crc32    = compute_crc32(payload)
        full_txt = payload + f"CHECKSUM={crc32:08X}\n"

        tmp_path = Path(str(self.state_file_path) + ".tmp")
        try:
            # Write to temp file
            tmp_path.write_text(full_txt, encoding="utf-8")
            # Atomic rename
            tmp_path.replace(self.state_file_path)
            return True
        except OSError:
            return False

    # ------------------------------------------------------------------
    # is_in_safe_mode
    # ------------------------------------------------------------------

    def is_in_safe_mode(self) -> bool:
        return bool(self.state.safe_mode_active)

    def get_safe_mode_reason(self) -> str:
        return self._safe_mode_reason

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _init_default_state(self) -> None:
        """Populate state with safe defaults (first run)."""
        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        self.state = EAState(
            daily_drawdown_pct        = 0.0,
            daily_open_equity         = 0.0,
            total_drawdown_ref_equity = 0.0,
            consecutive_losses        = 0,
            cooldown_start_utc        = epoch,
            circuit_breaker_triggered = False,
            safe_mode_active          = False,
            last_update_utc           = datetime.now(tz=timezone.utc),
            state_file_version        = STATE_FILE_VERSION,
            symbol                    = self.symbol,
            account_suffix            = self.account_suffix,
            checksum                  = 0,
        )
        self.pool_registry = []

    def _post_load_check(self) -> StateLoadResult:
        if self.state.circuit_breaker_triggered:
            return StateLoadResult.INIT_FAILED
        if self.state.safe_mode_active:
            return self._enter_safe_mode("PRIOR_SAFE_MODE_ACTIVE")
        self._adjust_for_day_change()
        return StateLoadResult.OK

    def _adjust_for_day_change(self) -> None:
        """Reset daily drawdown if the state file is from a previous day."""
        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        if self.state.last_update_utc == epoch:
            return
        last = self.state.last_update_utc
        now  = datetime.now(tz=timezone.utc)
        if last.date() != now.date():
            # EAState is frozen — create a new instance with reset values
            import dataclasses
            self.state = dataclasses.replace(
                self.state,
                daily_drawdown_pct = 0.0,
                daily_open_equity  = 0.0,
            )

    def _enter_safe_mode(self, reason: str) -> StateLoadResult:
        """Enter SAFE_MODE: set flag, write sentinel, return SAFE_MODE."""
        self._safe_mode_reason = reason
        import dataclasses
        self.state = dataclasses.replace(self.state, safe_mode_active=True)
        # Write sentinel file
        flag_path = self.state_file_path.parent / SAFE_MODE_FLAG_FILENAME
        try:
            flag_path.write_text("safe_mode=1\n", encoding="utf-8")
        except OSError:
            pass
        return StateLoadResult.SAFE_MODE

    def _read_and_validate(
        self, file_path: Path
    ) -> Tuple[EAState, List[LiquidityPool]]:
        """
        Read, CRC32-verify, and parse a state file.
        Raises StateValidationError on any failure.
        Returns (EAState, List[LiquidityPool]).
        """
        try:
            content = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            raise StateValidationError(f"READ_ERROR: {e}")

        lines = content.splitlines()
        if len(lines) < 14:
            raise StateValidationError(
                f"TRUNCATED: only {len(lines)} lines")

        # Find CHECKSUM line (last occurrence)
        checksum_idx = -1
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].startswith("CHECKSUM="):
                checksum_idx = i
                break

        if checksum_idx < 0:
            raise StateValidationError("MISSING_CHECKSUM")

        # Reconstruct payload for CRC32 verification
        payload = "\n".join(lines[:checksum_idx]) + "\n"
        computed = compute_crc32(payload)
        stored_str = lines[checksum_idx][len("CHECKSUM="):]
        try:
            stored = int(stored_str, 16)
        except ValueError:
            raise StateValidationError(
                f"INVALID_CHECKSUM_FORMAT: {stored_str!r}")

        if computed != stored:
            raise StateValidationError(
                f"CRC32_MISMATCH: computed={computed:08X} stored={stored:08X}")

        # Parse payload
        kv: dict = {}
        pools: List[LiquidityPool] = []
        in_pool_section = False
        pool_idx = 0

        for line in lines[:checksum_idx]:
            if line == "[POOL_REGISTRY]":
                in_pool_section = True
                continue
            if line == "[END_POOL_REGISTRY]":
                in_pool_section = False
                continue

            if in_pool_section:
                fields = line.split(",")
                if len(fields) >= 7:
                    status_map = {
                        "ACTIVE":      PoolStatus.ACTIVE,
                        "SWEPT":       PoolStatus.SWEPT,
                        "INVALIDATED": PoolStatus.INVALIDATED,
                    }
                    status = status_map.get(fields[3], PoolStatus.ACTIVE)
                    side   = PoolSide.ABOVE if fields[4] == "ABOVE" else PoolSide.BELOW
                    pools.append(LiquidityPool(
                        price_level       = float(fields[1]),
                        tolerance_band    = float(fields[2]),
                        status            = status,
                        side              = side,
                        created_timestamp = _iso_to_time(fields[5]) or datetime(1970,1,1,tzinfo=timezone.utc),
                        swept_timestamp   = _iso_to_time(fields[6]) or datetime(1970,1,1,tzinfo=timezone.utc),
                    ))
                continue

            if "=" not in line:
                continue
            key, _, val = line.partition("=")
            kv[key.strip()] = val.strip()

        # Validate required fields
        for req in ("SCHEMA", "SYMBOL", "ACCOUNT_SUFFIX",
                    "DAILY_DRAWDOWN_PCT", "CONSECUTIVE_LOSSES"):
            if req not in kv:
                raise StateValidationError(f"MISSING_FIELD: {req}")

        # Schema check
        schema = int(kv.get("SCHEMA", "0"))
        if schema > STATE_FILE_VERSION:
            raise StateValidationError(
                f"SCHEMA_TOO_NEW: file={schema} current={STATE_FILE_VERSION}")

        # Symbol check
        if kv.get("SYMBOL", "") != self.symbol:
            raise StateValidationError(
                f"SYMBOL_MISMATCH: file={kv.get('SYMBOL')} expected={self.symbol}")

        # Account suffix check
        if self.account_suffix and kv.get("ACCOUNT_SUFFIX", "") != self.account_suffix:
            raise StateValidationError("ACCOUNT_SUFFIX_MISMATCH")

        # Numeric range checks
        dd = float(kv.get("DAILY_DRAWDOWN_PCT", "-1"))
        if not (0.0 <= dd <= 100.0):
            raise StateValidationError(f"INVALID_DAILY_DD: {dd}")

        cl = int(kv.get("CONSECUTIVE_LOSSES", "-1"))
        if not (0 <= cl <= 1000):
            raise StateValidationError(f"INVALID_CONSECUTIVE_LOSSES: {cl}")

        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        st = EAState(
            daily_drawdown_pct        = dd,
            daily_open_equity         = float(kv.get("DAILY_OPEN_EQUITY", "0")),
            total_drawdown_ref_equity = float(kv.get("TOTAL_DRAWDOWN_REF_EQUITY", "0")),
            consecutive_losses        = cl,
            cooldown_start_utc        = _iso_to_time(kv.get("COOLDOWN_START_UTC", "0")) or epoch,
            circuit_breaker_triggered = kv.get("CIRCUIT_BREAKER_TRIGGERED", "0") == "1",
            safe_mode_active          = kv.get("SAFE_MODE_ACTIVE", "0") == "1",
            last_update_utc           = _iso_to_time(kv.get("TIMESTAMP_UTC", "0")) or epoch,
            state_file_version        = schema,
            symbol                    = kv.get("SYMBOL", ""),
            account_suffix            = kv.get("ACCOUNT_SUFFIX", ""),
            checksum                  = stored,
        )
        return st, pools
