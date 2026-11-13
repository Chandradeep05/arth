"""
Regression tests for M-01: Account deletion atomicity fix.

Coverage:
  T1 - Successful deletion: all three mutations execute and transaction commits.
  T2 - Failure on second UPDATE rolls back the first UPDATE (created_by not null).
  T3 - Failure on DELETE rolls back both UPDATE statements.
  T4 - Existing invite redemption semantics preserved (used_at retained, expires_at set).
  T5 - Transaction is entered exactly once, wrapping all three DB mutations.
  T6 - Admin-last-user guard prevents deletion before any DB mutation.
  T7 - HTTPException inside transaction propagates without swallowing (no silent rollback).

These tests use a mock DB that faithfully implements the asyncpg Connection interface
expected by account.py (execute, fetchval, transaction() async context manager).
Transaction rollback semantics are verified by tracking which execute() calls were
applied and verifying the rollback by checking call order vs exception injection point.

NOTE: These are unit/integration-style tests against the real application code with
mock DB objects.  Actual asyncpg transaction semantics require a live Postgres instance
(see NATIVE-REDIS-NOTE below); the mock verifies that the code *enters* a transaction
and executes the three operations in order.  The correctness of the rollback itself is
guaranteed by asyncpg's standard Connection.transaction() context manager.
"""
from __future__ import annotations

import pytest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4, UUID

from fastapi import HTTPException


# ---------------------------------------------------------------------------
# Helpers / shared fixtures
# ---------------------------------------------------------------------------

def _make_user(role: str = "user") -> SimpleNamespace:
    return SimpleNamespace(
        user_id=uuid4(),
        email="user@example.com",
        role=role,
        access_status="active",
        is_active=True,
        is_admin=(role == "admin"),
    )


def _make_settings(is_production: bool = False) -> SimpleNamespace:
    """Minimal settings object that suppresses the Supabase step."""
    return SimpleNamespace(
        supabase_url=None,
        supabase_service_key=None,
        app_env=SimpleNamespace(value="development" if not is_production else "production"),
        is_production=is_production,
    )


class _BaseDB:
    """Base asyncpg-like mock with operation log and transaction support."""

    def __init__(self):
        self.calls: list[tuple[str, tuple]] = []  # (sql_stem, args)
        self.tx_entered: int = 0
        self.tx_committed: int = 0

    @asynccontextmanager
    async def transaction(self):
        self.tx_entered += 1
        try:
            yield
            self.tx_committed += 1
        except Exception:
            # In a real asyncpg connection the exception exits the CM and rolls back.
            # We re-raise so the caller sees the error — this is the asyncpg contract.
            raise

    async def execute(self, sql: str, *args) -> str:
        self.calls.append((sql.strip(), args))
        return "DELETE 1" if sql.strip().upper().startswith("DELETE") else "UPDATE 1"

    async def fetchval(self, sql: str, *args):
        raise NotImplementedError("Override fetchval in subclass")

    async def fetchrow(self, sql: str, *args):
        raise NotImplementedError("Override fetchrow in subclass")


class _SuccessDB(_BaseDB):
    """DB that succeeds on all calls, 2 admins (so self-delete is allowed)."""

    def __init__(self, role: str = "user", admin_count: int = 2):
        super().__init__()
        self._role = role
        self._admin_count = admin_count
        self._fetchval_count = 0

    async def fetchval(self, sql: str, *args):
        self._fetchval_count += 1
        # First fetchval: SELECT role FROM profiles WHERE id = $1
        if self._fetchval_count == 1:
            return self._role
        # Second fetchval: SELECT COUNT(*) FROM profiles WHERE role = $1
        return self._admin_count


class _FailOnSecondUpdateDB(_BaseDB):
    """Raises on the second execute() call (second UPDATE invite_codes)."""

    def __init__(self):
        super().__init__()
        self._call_count = 0
        self._fetchval_count = 0

    async def fetchval(self, sql: str, *args):
        self._fetchval_count += 1
        # First fetchval: SELECT role FROM profiles WHERE id = $1
        if self._fetchval_count == 1:
            return "user"
        # Second fetchval: SELECT COUNT(*) FROM profiles WHERE role = $1
        return 2

    async def execute(self, sql: str, *args) -> str:
        self._call_count += 1
        if self._call_count == 2:
            raise RuntimeError("Simulated DB failure on second UPDATE")
        return await super().execute(sql, *args)


class _FailOnDeleteDB(_BaseDB):
    """Raises on the DELETE FROM profiles call."""

    def __init__(self):
        super().__init__()
        self._fetchval_count = 0

    async def fetchval(self, sql: str, *args):
        self._fetchval_count += 1
        if self._fetchval_count == 1:
            return "user"
        return 2

    async def execute(self, sql: str, *args) -> str:
        if sql.strip().upper().startswith("DELETE"):
            raise RuntimeError("Simulated DB failure on DELETE FROM profiles")
        return await super().execute(sql, *args)


# ---------------------------------------------------------------------------
# Import the endpoint under test
# ---------------------------------------------------------------------------

from app.api.v1 import account


def _make_request(db) -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(db=db))


# ---------------------------------------------------------------------------
# T1 — Successful deletion: all three mutations execute, transaction commits
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t1_successful_deletion_all_mutations_execute():
    """
    T1: Happy path.  Given a valid user with no last-admin restriction and no
    Supabase configured (dev mode), delete_account must:
    - Enter exactly one transaction.
    - Execute the three DB mutations in order:
        1. UPDATE invite_codes SET created_by = NULL WHERE created_by = $1
        2. UPDATE invite_codes SET used_by = NULL, expires_at = now() WHERE used_by = $1
        3. DELETE FROM profiles WHERE id = $1
    - Commit (not raise).
    - Return {"success": True, ...}.
    """
    db = _SuccessDB(role="user")
    user = _make_user(role="user")
    req = _make_request(db)

    with __import__("unittest.mock", fromlist=["patch"]).patch(
        "app.api.v1.account.get_settings", return_value=_make_settings()
    ):
        result = await account.delete_account(req, user)

    assert result["success"] is True

    # Transaction entered exactly once
    assert db.tx_entered == 1, f"Expected tx_entered=1, got {db.tx_entered}"
    assert db.tx_committed == 1, f"Expected tx_committed=1, got {db.tx_committed}"

    # Verify the three mutations are present and in correct order
    sqls = [c[0] for c in db.calls]
    assert any("SET created_by = NULL" in s for s in sqls), "Missing created_by NULL update"
    assert any("SET used_by = NULL" in s for s in sqls), "Missing used_by NULL update"
    assert any(s.upper().startswith("DELETE FROM PROFILES") for s in sqls), "Missing DELETE FROM profiles"

    # Order: created_by update BEFORE used_by update BEFORE DELETE
    idx_created_by = next(i for i, s in enumerate(sqls) if "SET created_by = NULL" in s)
    idx_used_by = next(i for i, s in enumerate(sqls) if "SET used_by = NULL" in s)
    idx_delete = next(i for i, s in enumerate(sqls) if s.upper().startswith("DELETE FROM PROFILES"))
    assert idx_created_by < idx_used_by < idx_delete, (
        f"Wrong mutation order: created_by={idx_created_by}, used_by={idx_used_by}, delete={idx_delete}"
    )

    # Each mutation receives the correct user_id
    for sql, args in db.calls:
        if "SET created_by = NULL" in sql or "SET used_by = NULL" in sql or sql.upper().startswith("DELETE"):
            assert args[0] == user.user_id, f"Wrong user_id argument in: {sql}"


# ---------------------------------------------------------------------------
# T2 — Failure on second UPDATE rolls back the first UPDATE
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t2_failure_on_second_update_rolls_back_first():
    """
    T2: If the second UPDATE invite_codes (used_by) raises, the transaction
    must NOT commit.  In real asyncpg the first UPDATE is rolled back.
    In the mock we verify:
    - tx_committed == 0 (no commit).
    - The exception propagates out of delete_account.
    - Only 1 execute() call succeeded before the error.
    """
    db = _FailOnSecondUpdateDB()
    user = _make_user(role="user")
    req = _make_request(db)

    with __import__("unittest.mock", fromlist=["patch"]).patch(
        "app.api.v1.account.get_settings", return_value=_make_settings()
    ):
        with pytest.raises(RuntimeError, match="Simulated DB failure on second UPDATE"):
            await account.delete_account(req, user)

    # Transaction was entered but NOT committed
    assert db.tx_entered == 1, f"Expected tx_entered=1, got {db.tx_entered}"
    assert db.tx_committed == 0, f"Expected tx_committed=0 (rollback), got {db.tx_committed}"

    # Only the first mutation ran (created_by = NULL); the DELETE did NOT execute
    sqls = [c[0] for c in db.calls]
    assert any("SET created_by = NULL" in s for s in sqls), "First mutation should have been attempted"
    assert not any(s.upper().startswith("DELETE FROM PROFILES") for s in sqls), (
        "DELETE FROM profiles must NOT have executed; it should be rolled back"
    )


# ---------------------------------------------------------------------------
# T3 — Failure on DELETE rolls back both UPDATE statements
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t3_failure_on_delete_rolls_back_both_updates():
    """
    T3: If DELETE FROM profiles raises, the transaction must NOT commit.
    In real asyncpg both preceding UPDATEs are rolled back.
    In the mock we verify:
    - tx_committed == 0.
    - Both UPDATEs ran (they were submitted) but the transaction did not commit.
    - The exception propagates.
    """
    db = _FailOnDeleteDB()
    user = _make_user(role="user")
    req = _make_request(db)

    with __import__("unittest.mock", fromlist=["patch"]).patch(
        "app.api.v1.account.get_settings", return_value=_make_settings()
    ):
        with pytest.raises(RuntimeError, match="Simulated DB failure on DELETE FROM profiles"):
            await account.delete_account(req, user)

    assert db.tx_entered == 1
    assert db.tx_committed == 0, (
        f"Transaction must NOT commit on DELETE failure. tx_committed={db.tx_committed}"
    )

    # Both UPDATEs were submitted inside the (now-rolled-back) transaction
    sqls = [c[0] for c in db.calls]
    assert any("SET created_by = NULL" in s for s in sqls), "created_by UPDATE should have run"
    assert any("SET used_by = NULL" in s for s in sqls), "used_by UPDATE should have run"


# ---------------------------------------------------------------------------
# T4 — Invite semantics: used_by=NULL, expires_at=now(), used_at preserved
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t4_invite_expiration_semantics_preserved():
    """
    T4: The DELETE step uses 'expires_at = now()' and sets 'used_by = NULL'
    but does NOT clear 'used_at'.  Verify the SQL text uses these exact semantics.
    """
    db = _SuccessDB(role="user")
    user = _make_user(role="user")
    req = _make_request(db)

    with __import__("unittest.mock", fromlist=["patch"]).patch(
        "app.api.v1.account.get_settings", return_value=_make_settings()
    ):
        await account.delete_account(req, user)

    # Find the used_by UPDATE
    used_by_sqls = [s for s, _ in db.calls if "SET used_by = NULL" in s]
    assert len(used_by_sqls) == 1, f"Expected exactly one used_by UPDATE, got {len(used_by_sqls)}"
    sql = used_by_sqls[0]

    # Must set expires_at = now() to prevent reuse
    assert "expires_at = now()" in sql, (
        f"used_by UPDATE must include 'expires_at = now()' to retire the code. SQL: {sql}"
    )
    # Must NOT clear used_at (audit trail preserved)
    assert "used_at" not in sql or "used_at = NULL" not in sql, (
        "used_at must NOT be cleared — it is the audit trail. SQL: {sql}"
    )
    # Must filter WHERE used_by = $1
    assert "WHERE used_by = $1" in sql, f"WHERE clause must filter by used_by. SQL: {sql}"


# ---------------------------------------------------------------------------
# T5 — Transaction wraps all three mutations (not just some)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t5_transaction_entered_exactly_once_wrapping_all_three():
    """
    T5: Exactly one db.transaction() call must wrap all three DB mutations.
    Before the transaction there must be no mutations (only SELECTs from the
    admin-guard fetchval calls).
    """
    class _TrackingDB(_SuccessDB):
        def __init__(self):
            super().__init__(role="user")
            self.calls_outside_tx: list[str] = []
            self.calls_inside_tx: list[str] = []
            self._inside_tx = False

        @asynccontextmanager
        async def transaction(self):
            self.tx_entered += 1
            self._inside_tx = True
            try:
                yield
                self.tx_committed += 1
            except Exception:
                raise
            finally:
                self._inside_tx = False

        async def execute(self, sql: str, *args) -> str:
            if self._inside_tx:
                self.calls_inside_tx.append(sql.strip())
            else:
                self.calls_outside_tx.append(sql.strip())
            return await super().execute(sql, *args)

    db = _TrackingDB()
    user = _make_user(role="user")
    req = _make_request(db)

    with __import__("unittest.mock", fromlist=["patch"]).patch(
        "app.api.v1.account.get_settings", return_value=_make_settings()
    ):
        await account.delete_account(req, user)

    assert db.tx_entered == 1
    assert db.tx_committed == 1

    # No DML execute() calls outside the transaction
    assert db.calls_outside_tx == [], (
        f"execute() calls found OUTSIDE transaction (must all be inside): {db.calls_outside_tx}"
    )

    # All three mutations are inside the transaction
    assert len(db.calls_inside_tx) == 3, (
        f"Expected exactly 3 execute() calls inside transaction, got {len(db.calls_inside_tx)}: {db.calls_inside_tx}"
    )
    assert any("SET created_by = NULL" in s for s in db.calls_inside_tx)
    assert any("SET used_by = NULL" in s for s in db.calls_inside_tx)
    assert any(s.upper().startswith("DELETE FROM PROFILES") for s in db.calls_inside_tx)


# ---------------------------------------------------------------------------
# T6 — Last-admin guard fires BEFORE any transaction or DB mutation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t6_last_admin_guard_fires_before_any_mutation():
    """
    T6: When the user is the last admin, delete_account must raise 409 without
    entering a transaction or executing any mutation.
    """
    db = _SuccessDB(role="admin", admin_count=1)
    user = _make_user(role="admin")
    req = _make_request(db)

    with __import__("unittest.mock", fromlist=["patch"]).patch(
        "app.api.v1.account.get_settings", return_value=_make_settings()
    ):
        with pytest.raises(HTTPException) as exc:
            await account.delete_account(req, user)

    assert exc.value.status_code == 409
    assert "last admin" in exc.value.detail.lower()

    # No transaction entered
    assert db.tx_entered == 0, f"Transaction must NOT have been entered. tx_entered={db.tx_entered}"

    # No DML calls
    mutation_sqls = [
        s for s, _ in db.calls
        if any(kw in s for kw in ("SET created_by", "SET used_by", "DELETE FROM PROFILES"))
    ]
    assert mutation_sqls == [], f"No DML should execute before 409 guard: {mutation_sqls}"


# ---------------------------------------------------------------------------
# T7 — HTTPException from inside transaction propagates without swallowing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t7_http_exception_inside_transaction_propagates():
    """
    T7: If a mutation raises an HTTPException (e.g. a future guard added inside
    the transaction block), it must propagate to the caller, not be swallowed.
    The transaction must not commit.
    """
    class _HTTPExceptionOnDeleteDB(_BaseDB):
        def __init__(self):
            super().__init__()
            self._fetchval_count = 0

        async def fetchval(self, sql: str, *args):
            self._fetchval_count += 1
            if self._fetchval_count == 1:
                return "user"
            return 2

        async def execute(self, sql: str, *args) -> str:
            if sql.strip().upper().startswith("DELETE"):
                raise HTTPException(status_code=500, detail="Simulated internal error on DELETE")
            return await super().execute(sql, *args)

    db = _HTTPExceptionOnDeleteDB()
    user = _make_user(role="user")
    req = _make_request(db)

    with __import__("unittest.mock", fromlist=["patch"]).patch(
        "app.api.v1.account.get_settings", return_value=_make_settings()
    ):
        with pytest.raises(HTTPException) as exc:
            await account.delete_account(req, user)

    assert exc.value.status_code == 500
    assert db.tx_committed == 0, "Transaction must not commit on HTTPException"
