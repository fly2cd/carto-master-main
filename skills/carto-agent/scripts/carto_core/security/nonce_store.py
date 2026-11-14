"""Persistent nonce ledger for replay protection.

Every nonce is consumed exactly once across all runs. The ledger stores the
execution intent *before* the operation, so a crash during execution can be
safely recovered without consuming a second nonce.

Schema (SQLite, single-table)::

    nonce_ledger (
        nonce        TEXT PRIMARY KEY,
        receipt_id   TEXT NOT NULL,
        run_id       TEXT NOT NULL,
        intent_digest TEXT NOT NULL,
        state        TEXT NOT NULL,   -- 'reserved' | 'consumed'
        consumed_at  TEXT,
        created_at   TEXT NOT NULL
    )

Lifecycle::

    reserve(nonce, intent)   → state='reserved'   (before execution)
    execute operation …
    consume(nonce)           → state='consumed'   (after success)
    ── crash between reserve and consume ──
    recover(nonce, intent)   → ok if intent matches, REJECT otherwise
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

from ..errors import SecurityError


class NonceStore:
    """SQLite-backed nonce ledger with intent-bound reservation.

    Thread-safe: all public methods acquire the instance lock.
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._lock = threading.Lock()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def close(self) -> None:
        """Close any lingering connections so the database file can be deleted.

        On Windows, WAL-mode SQLite databases keep extra files (*-wal, *-shm)
        that block directory removal.  Call this before tearing down a work
        directory that contains the nonce ledger.
        """
        # Force a connection open/close cycle to flush WAL and release handles.
        with self._lock:
            try:
                conn = sqlite3.connect(str(self._db_path))
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                conn.execute("PRAGMA optimize")
                conn.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    def reserve(self, nonce: str, receipt_id: str, run_id: str, intent_digest: str) -> None:
        """Atomically reserve *nonce* for *intent_digest*.

        Raises:
            SecurityError('APPROVAL_NONCE_REPLAY'): nonce already consumed.
            SecurityError('APPROVAL_NONCE_CONFLICT'): nonce reserved by a different intent.
        """
        now = _utc_now()
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT state, intent_digest FROM nonce_ledger WHERE nonce = ?", (nonce,)
                ).fetchone()
                if row is None:
                    conn.execute(
                        "INSERT INTO nonce_ledger (nonce, receipt_id, run_id, intent_digest, state, created_at) "
                        "VALUES (?, ?, ?, ?, 'reserved', ?)",
                        (nonce, receipt_id, run_id, intent_digest, now),
                    )
                    conn.commit()
                    return
                state, existing_intent = row
                if state == "consumed":
                    raise SecurityError(
                        "APPROVAL_NONCE_REPLAY",
                        f"Nonce '{nonce}' has already been consumed",
                    )
                if existing_intent != intent_digest:
                    raise SecurityError(
                        "APPROVAL_NONCE_CONFLICT",
                        f"Nonce '{nonce}' is reserved for a different intent",
                    )
                # Same intent, same nonce → idempotent, nothing to do

    # ------------------------------------------------------------------
    def consume(self, nonce: str) -> None:
        """Mark a previously reserved nonce as consumed.

        Raises:
            SecurityError('APPROVAL_NONCE_NOT_FOUND'): nonce was never reserved.
            SecurityError('APPROVAL_NONCE_ALREADY_CONSUMED'): nonce already consumed.
        """
        now = _utc_now()
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT state FROM nonce_ledger WHERE nonce = ?", (nonce,)
                ).fetchone()
                if row is None:
                    raise SecurityError(
                        "APPROVAL_NONCE_NOT_FOUND",
                        f"Nonce '{nonce}' was never reserved",
                    )
                if row[0] == "consumed":
                    raise SecurityError(
                        "APPROVAL_NONCE_ALREADY_CONSUMED",
                        f"Nonce '{nonce}' has already been consumed",
                    )
                conn.execute(
                    "UPDATE nonce_ledger SET state = 'consumed', consumed_at = ? WHERE nonce = ?",
                    (now, nonce),
                )
                conn.commit()

    # ------------------------------------------------------------------
    def verify_and_consume(
        self, nonce: str, receipt_id: str, run_id: str, intent_digest: str
    ) -> None:
        """Reserve, execute-intent barrier, then consume — all in one call.

        This is the canonical entry point for gate verification:
        1. reserve (or recover)
        2. (caller performs the actual gate operation between reserve and consume)
        3. consume

        Handles idempotent replay: if the nonce is already consumed with the
        same intent_digest, the call is silently accepted (re-verification of
        a previously executed gate). A consumed nonce with a different intent
        is still rejected as a replay attack.
        """
        now = _utc_now()
        with self._lock:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT receipt_id, run_id, intent_digest FROM nonce_ledger WHERE nonce = ?", (nonce,)
                ).fetchone()
                expected = (receipt_id, run_id, intent_digest)
                if row is not None and tuple(row) != expected:
                    raise SecurityError("APPROVAL_NONCE_REPLAY", "Nonce belongs to another approval transaction")
                if row is None:
                    conn.execute(
                        "INSERT INTO nonce_ledger (nonce, receipt_id, run_id, intent_digest, state, created_at, consumed_at) "
                        "VALUES (?, ?, ?, ?, 'consumed', ?, ?)",
                        (nonce, receipt_id, run_id, intent_digest, now, now))
                else:
                    conn.execute("UPDATE nonce_ledger SET state = 'consumed', consumed_at = COALESCE(consumed_at, ?) "
                                 "WHERE nonce = ?", (now, nonce))
                conn.commit()

    # ------------------------------------------------------------------
    def is_consumed(self, nonce: str) -> bool:
        """Return True if *nonce* exists and is in 'consumed' state."""
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT state FROM nonce_ledger WHERE nonce = ?", (nonce,)
                ).fetchone()
                return row is not None and row[0] == "consumed"

    # ------------------------------------------------------------------
    def check_recovery(self, nonce: str, intent_digest: str) -> bool:
        """Check if *nonce* can be safely recovered.

        Returns True when the nonce is reserved with a matching intent —
        the caller may re-execute the operation.
        Returns False when the nonce does not exist or is already consumed.

        Raises:
            SecurityError('APPROVAL_RECOVERY_CONFLICT'): nonce is reserved with
                a *different* intent — recovery is not allowed.
        """
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT state, intent_digest FROM nonce_ledger WHERE nonce = ?", (nonce,)
                ).fetchone()
                if row is None:
                    return False
                state, existing_intent = row
                if state == "consumed":
                    return False
                if existing_intent != intent_digest:
                    raise SecurityError(
                        "APPROVAL_RECOVERY_CONFLICT",
                        f"Nonce '{nonce}' is reserved for a different intent — recovery denied",
                    )
                return True

    # ------------------------------------------------------------------
    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self._db_path))
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            yield conn
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _init_db(self) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """CREATE TABLE IF NOT EXISTS nonce_ledger (
                        nonce         TEXT PRIMARY KEY,
                        receipt_id    TEXT NOT NULL,
                        run_id        TEXT NOT NULL,
                        intent_digest TEXT NOT NULL,
                        state         TEXT NOT NULL CHECK(state IN ('reserved','consumed')),
                        consumed_at   TEXT,
                        created_at    TEXT NOT NULL
                    )"""
                )
                conn.commit()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()