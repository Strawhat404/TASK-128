"""Focused unit tests for backend/app.py (Container boot, provisioning)
and backend/models/__init__.py (dataclass contracts, Paged interface)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend import config, db as _db
from backend.app import Container, STARTUP_PROFILE
from backend.models import (
    Bed, BedAssignment, ChangeLogEntry, EmployerCase, ImportPreview,
    NotificationMessage, Page, Paged, Resource, ResourceVersion,
    SearchHit, Student, StudentDTO, StudentSummary, User,
)
from backend.permissions import Session
from backend.services.auth import BizError


# ===================================================================
# backend/app.py — Container
# ===================================================================


class TestContainerBoot:

    def test_startup_profile_populated(self, container):
        for key in ("db_open_s", "seed_s", "services_s", "total_s"):
            assert key in STARTUP_PROFILE
            assert isinstance(STARTUP_PROFILE[key], float)
            assert STARTUP_PROFILE[key] >= 0

    def test_all_sixteen_services_wired(self, container):
        attrs = [
            "auth", "students", "housing", "resources", "compliance",
            "evidence", "sensitive", "violations", "notifications", "search",
            "reporting", "settings", "catalog", "bom", "checkpoints", "updater",
        ]
        for attr in attrs:
            assert hasattr(container, attr), f"Container missing .{attr}"
            assert getattr(container, attr) is not None

    def test_container_creates_data_dir(self, container):
        assert config.data_dir().is_dir()

    def test_container_runs_migrations(self, container):
        conn = _db.get_connection()
        tables = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "users" in tables
        assert "students" in tables
        assert "roles" in tables
        assert "audit_log" in tables

    def test_container_seeds_roles(self, container):
        conn = _db.get_connection()
        n = conn.execute("SELECT COUNT(*) AS n FROM roles").fetchone()["n"]
        assert n > 0

    def test_container_seeds_permissions(self, container):
        conn = _db.get_connection()
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM permissions").fetchone()["n"]
        assert n > 0

    def test_container_seeds_notification_templates(self, container):
        conn = _db.get_connection()
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM notif_templates").fetchone()["n"]
        assert n > 0


class TestContainerProvisionUpdatePubkey:

    def test_placeholder_key_not_provisioned(self, container, tmp_path,
                                             monkeypatch):
        pk_path = config.update_signing_key_path()
        if pk_path.exists():
            pk_path.unlink()
        placeholder = (config.REPO_ROOT / "installer" / "update_pubkey.pem")
        placeholder.parent.mkdir(parents=True, exist_ok=True)
        placeholder.write_bytes(
            b"-----BEGIN PUBLIC KEY-----\n"
            b"PLACEHOLDER - replace with real key\n"
            b"-----END PUBLIC KEY-----\n")
        try:
            container._provision_update_pubkey()
            assert not pk_path.exists() or b"PLACEHOLDER" not in pk_path.read_bytes()
        finally:
            if placeholder.exists():
                placeholder.unlink()

    def test_provision_skips_if_already_exists(self, container):
        pk_path = config.update_signing_key_path()
        pk_path.parent.mkdir(parents=True, exist_ok=True)
        pk_path.write_bytes(b"existing-key-data")
        container._provision_update_pubkey()
        assert pk_path.read_bytes() == b"existing-key-data"


# ===================================================================
# backend/models/__init__.py — Dataclass contracts
# ===================================================================


class TestPage:

    def test_defaults(self):
        p = Page()
        assert p.limit == 50
        assert p.offset == 0

    def test_custom_values(self):
        p = Page(limit=10, offset=5)
        assert p.limit == 10
        assert p.offset == 5


class TestPaged:

    def test_iter(self):
        p = Paged(items=[1, 2, 3], total=10)
        assert list(p) == [1, 2, 3]

    def test_len(self):
        p = Paged(items=["a", "b"], total=5)
        assert len(p) == 2

    def test_getitem(self):
        p = Paged(items=["x", "y", "z"], total=3)
        assert p[0] == "x"
        assert p[2] == "z"

    def test_bool_true(self):
        assert bool(Paged(items=[1], total=1)) is True

    def test_bool_false(self):
        assert bool(Paged(items=[], total=0)) is False

    def test_total_independent_of_items(self):
        p = Paged(items=[1, 2], total=100)
        assert len(p) == 2
        assert p.total == 100


class TestStudentDTO:

    def test_defaults(self):
        dto = StudentDTO(student_id="S1", full_name="Test")
        assert dto.college is None
        assert dto.class_year is None
        assert dto.email is None
        assert dto.phone is None
        assert dto.ssn_last4 is None
        assert dto.housing_status == "pending"

    def test_all_fields(self):
        dto = StudentDTO(
            student_id="S1", full_name="Full",
            college="Eng", class_year=2027,
            email="a@b.com", phone="555",
            ssn_last4="1234", housing_status="on_campus")
        assert dto.student_id == "S1"
        assert dto.housing_status == "on_campus"


class TestUser:

    def test_defaults(self):
        u = User(id=1, username="admin", full_name="Admin")
        assert u.disabled is False
        assert u.roles == []

    def test_with_roles(self):
        u = User(id=1, username="a", full_name="A", roles=["system_admin"])
        assert "system_admin" in u.roles


class TestStudent:

    def test_all_fields(self):
        s = Student(id=1, student_id="S1", full_name="Name", college="C",
                    class_year=2027, email="e", phone="p", ssn_last4="s",
                    housing_status="pending", created_at="now", updated_at="now")
        assert s.id == 1
        assert s.housing_status == "pending"


class TestSearchHit:

    def test_fields(self):
        h = SearchHit(entity_type="student", entity_id=1, title="T",
                      subtitle="S", score=85.0, open_action="open")
        assert h.score == 85.0
        assert h.open_action == "open"


class TestImportPreview:

    def test_fields(self):
        p = ImportPreview(
            preview_id="abc", accepted=[{"row": 1}],
            rejected=[], columns=["a"], duplicate_strategy="error")
        assert p.preview_id == "abc"
        assert len(p.accepted) == 1


class TestChangeLogEntry:

    def test_fields(self):
        e = ChangeLogEntry(id=1, ts="2026-01-01", actor_id=1,
                           action="create", payload={"key": "val"})
        assert e.action == "create"
        assert e.payload["key"] == "val"


class TestBed:

    def test_fields(self):
        b = Bed(id=1, building="East", room="101", code="A", occupied=False)
        assert b.occupied is False


class TestBedAssignment:

    def test_defaults(self):
        a = BedAssignment(id=1, student_id=1, student_name="S",
                          bed_id=1, bed_label="E 101-A",
                          effective_date="2026-01-01", end_date=None,
                          reason="assign")
        assert a.created_at is None
        assert a.operator_id is None


class TestResource:

    def test_fields(self):
        r = Resource(id=1, title="T", category=None, status="active",
                     latest_version=1, published_version=None)
        assert r.published_version is None


class TestEmployerCase:

    def test_fields(self):
        c = EmployerCase(id=1, employer_id=1, employer_name="Co",
                         kind="onboarding", state="submitted",
                         reviewer_id=None, decision=None,
                         decided_at=None, notes=None)
        assert c.kind == "onboarding"


class TestNotificationMessage:

    def test_fields(self):
        m = NotificationMessage(id=1, template_name="t", subject="S",
                                body="B", status="delivered", attempts=1,
                                scheduled_for=None, created_at="now",
                                read_at=None)
        assert m.status == "delivered"
        assert m.read_at is None
