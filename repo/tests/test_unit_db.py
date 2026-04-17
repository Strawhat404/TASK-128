"""Dedicated unit tests for backend/db.py — connection lifecycle,
transaction semantics, at-rest encryption, migration runner, and
failure-mode branches.

These complement the indirect db.py coverage in integration/e2e tests
by directly exercising edge cases and error recovery paths.
"""
from __future__ import annotations

import sqlite3

import pytest

from backend import config, crypto, db as _db
from backend.services.auth import BizError


# ===================================================================
# Connection lifecycle
# ===================================================================


class TestGetConnection:

    def test_returns_sqlite_connection(self, container):
        conn = _db.get_connection()
        assert isinstance(conn, sqlite3.Connection)

    def test_returns_same_connection_on_repeated_calls(self, container):
        c1 = _db.get_connection()
        c2 = _db.get_connection()
        assert c1 is c2

    def test_row_factory_is_row(self, container):
        conn = _db.get_connection()
        assert conn.row_factory is sqlite3.Row

    def test_foreign_keys_enabled(self, container):
        conn = _db.get_connection()
        fk = conn.execute("PRAGMA foreign_keys").fetchone()
        assert fk[0] == 1


class TestResetConnection:

    def test_clears_cached_connection(self, container):
        c1 = _db.get_connection()
        _db.reset_connection()
        c2 = _db.get_connection()
        assert c1 is not c2

    def test_data_survives_reset(self, container, admin_session):
        """Data committed before reset must be readable after reopen."""
        from backend.models import StudentDTO
        container.students.create(
            admin_session,
            StudentDTO(student_id="RST-1", full_name="Reset Survivor",
                       housing_status="pending"))
        _db.reset_connection()
        conn = _db.get_connection()
        row = conn.execute(
            "SELECT id FROM students WHERE student_id_ext='RST-1'"
        ).fetchone()
        assert row is not None

    def test_reset_when_no_connection_is_noop(self):
        """reset_connection must not raise when no connection is open."""
        saved = _db._CONN
        _db._CONN = None
        try:
            _db.reset_connection()  # should not raise
        finally:
            _db._CONN = saved


# ===================================================================
# Transaction semantics
# ===================================================================


class TestTransaction:

    def test_commit_persists_data(self, container):
        with _db.transaction() as conn:
            conn.execute(
                "INSERT INTO settings(key, value) VALUES('txn_test', 'yes')")
        row = _db.get_connection().execute(
            "SELECT value FROM settings WHERE key='txn_test'").fetchone()
        assert row["value"] == "yes"

    def test_rollback_on_exception(self, container):
        """An exception inside a transaction block must roll back
        the partial writes so they are not visible afterward."""
        try:
            with _db.transaction() as conn:
                conn.execute(
                    "INSERT INTO settings(key, value) "
                    "VALUES('txn_rollback', 'should_not_persist')")
                raise RuntimeError("deliberate")
        except RuntimeError:
            pass
        row = _db.get_connection().execute(
            "SELECT value FROM settings WHERE key='txn_rollback'"
        ).fetchone()
        assert row is None

    def test_nested_service_calls_in_transaction(self, container,
                                                 admin_session):
        """Service calls that internally use transaction() must not
        corrupt each other's state."""
        from backend.models import StudentDTO
        s = container.students.create(
            admin_session,
            StudentDTO(student_id="TXN-1", full_name="Txn Student",
                       housing_status="pending"))
        assert s.id > 0
        fetched = container.students.get(admin_session, s.id)
        assert fetched.full_name == "Txn Student"


# ===================================================================
# At-rest encryption (fallback / in-memory mode)
# ===================================================================


class TestAtRestEncryption:

    def _skip_sqlcipher(self):
        if getattr(_db, "HAVE_SQLCIPHER", False):
            pytest.skip("SQLCipher mode — fallback paths not exercised")

    def test_enc_path_helper(self):
        from pathlib import Path
        assert _db._enc_path(Path("/data/crhgc.db")) == Path("/data/crhgc.db.enc")

    def test_no_plaintext_on_disk_after_transaction(self, container,
                                                    admin_session):
        self._skip_sqlcipher()
        container.compliance.submit_employer(
            admin_session, "DiskCheck Co", "77-7777777", "d@e.com")
        db_path = config.db_path()
        enc = db_path.with_suffix(db_path.suffix + ".enc")
        assert enc.is_file()
        assert not db_path.exists()

    def test_close_and_seal_produces_only_enc_blob(self, container,
                                                   admin_session):
        self._skip_sqlcipher()
        container.settings.set(admin_session, "seal_test", "value")
        _db.close_and_seal()
        db_path = config.db_path()
        enc = db_path.with_suffix(db_path.suffix + ".enc")
        assert enc.is_file()
        assert not db_path.exists()
        # Reopen and confirm data survives
        conn = _db.get_connection()
        row = conn.execute(
            "SELECT value FROM settings WHERE key='seal_test'").fetchone()
        assert row["value"] == "value"

    def test_close_and_seal_idempotent(self, container, admin_session):
        self._skip_sqlcipher()
        _db.close_and_seal()
        _db.close_and_seal()  # second call is no-op, must not raise

    def test_periodic_reseal_no_op_without_connection(self):
        saved = _db._CONN
        _db._CONN = None
        try:
            _db.periodic_reseal()  # must not raise
        finally:
            _db._CONN = saved

    def test_periodic_reseal_refreshes_blob(self, container, admin_session):
        self._skip_sqlcipher()
        container.settings.set(admin_session, "reseal_k", "reseal_v")
        _db.periodic_reseal()
        db_path = config.db_path()
        enc = db_path.with_suffix(db_path.suffix + ".enc")
        assert enc.is_file()

    def test_abrupt_kill_recovery(self, container, admin_session):
        """Simulate SIGKILL: drop _CONN without close_and_seal.
        Per-commit persist must keep enc blob current."""
        self._skip_sqlcipher()
        container.settings.set(admin_session, "kill_k", "kill_v")
        # Simulate abrupt kill — discard connection without sealing
        _db._CONN = None
        conn = _db.get_connection()
        row = conn.execute(
            "SELECT value FROM settings WHERE key='kill_k'").fetchone()
        assert row is not None
        assert row["value"] == "kill_v"

    def test_corrupt_blob_graceful_degradation(self, container, admin_session):
        """Corrupted enc blob must not crash; app falls back to empty DB."""
        self._skip_sqlcipher()
        try:
            import cryptography  # noqa: F401
        except ImportError:
            pytest.skip("cryptography not installed")
        container.settings.set(admin_session, "corrupt_k", "val")
        _db.close_and_seal()
        enc = config.db_path().with_suffix(config.db_path().suffix + ".enc")
        # Mangle the ciphertext
        raw = bytearray(enc.read_bytes())
        for i in range(20, min(80, len(raw))):
            raw[i] ^= 0xFF
        enc.write_bytes(bytes(raw))
        # Reopen must not raise
        conn = _db.get_connection()
        # Data is lost (corrupt), but app survived
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM settings WHERE key='corrupt_k'"
        ).fetchone()["n"]
        assert n == 0


# ===================================================================
# Migration runner
# ===================================================================


class TestMigrations:

    def test_schema_version_table_exists(self, container):
        conn = _db.get_connection()
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM schema_version").fetchone()
        assert row["n"] > 0

    def test_all_migrations_applied(self, container):
        conn = _db.get_connection()
        applied = {r["version"] for r in conn.execute(
            "SELECT version FROM schema_version")}
        files = sorted(config.MIGRATIONS_DIR.glob("*.sql"))
        expected = set()
        for f in files:
            try:
                expected.add(int(f.name.split("_", 1)[0]))
            except ValueError:
                continue
        assert expected.issubset(applied)

    def test_re_running_migrations_is_safe(self, container):
        """Calling _ensure_migrations on an already-migrated DB must be
        idempotent — no errors, no duplicate rows."""
        conn = _db.get_connection()
        before = conn.execute(
            "SELECT COUNT(*) AS n FROM schema_version").fetchone()["n"]
        _db._ensure_migrations(conn)
        after = conn.execute(
            "SELECT COUNT(*) AS n FROM schema_version").fetchone()["n"]
        assert after == before

    def test_core_tables_present(self, container):
        conn = _db.get_connection()
        tables = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        expected = {
            "users", "roles", "permissions", "user_roles",
            "role_permissions", "students", "buildings", "rooms", "beds",
            "bed_assignments", "resources", "resource_versions",
            "resource_categories", "employers", "employer_cases",
            "audit_log", "notif_templates", "notif_rules",
            "notif_messages", "settings", "saved_searches",
            "workspace_state", "draft_checkpoints", "update_packages",
        }
        missing = expected - tables
        assert not missing, f"Missing tables: {missing}"


# ===================================================================
# Seed
# ===================================================================


class TestSeed:

    def test_seed_if_empty_is_idempotent(self, container):
        roles_before = _db.get_connection().execute(
            "SELECT COUNT(*) AS n FROM roles").fetchone()["n"]
        _db.seed_if_empty()
        roles_after = _db.get_connection().execute(
            "SELECT COUNT(*) AS n FROM roles").fetchone()["n"]
        assert roles_after == roles_before

    def test_seed_populates_roles(self, container):
        roles = [r["code"] for r in _db.get_connection().execute(
            "SELECT code FROM roles")]
        assert "system_admin" in roles
        assert "housing_coordinator" in roles

    def test_seed_populates_buildings(self, container):
        n = _db.get_connection().execute(
            "SELECT COUNT(*) AS n FROM buildings").fetchone()["n"]
        assert n > 0

    def test_seed_populates_notification_templates(self, container):
        n = _db.get_connection().execute(
            "SELECT COUNT(*) AS n FROM notif_templates").fetchone()["n"]
        assert n > 0
