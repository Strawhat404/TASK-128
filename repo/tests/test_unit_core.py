"""Unit tests for backend/events.py, backend/permissions.py, backend/config.py."""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest


# ===========================================================================
# EventBus (backend/events.py)
# ===========================================================================

class TestEventBus:
    def _make_bus(self):
        from backend.events import EventBus
        return EventBus()

    def test_event_bus_publish_delivers_to_subscriber(self):
        bus = self._make_bus()
        received = []
        bus.subscribe("EVT_A", lambda p: received.append(p))
        bus.publish("EVT_A", {"key": "value"})
        assert len(received) == 1
        assert received[0] == {"key": "value"}

    def test_event_bus_multiple_subscribers(self):
        bus = self._make_bus()
        calls_a = []
        calls_b = []
        bus.subscribe("EVT_X", lambda p: calls_a.append(p))
        bus.subscribe("EVT_X", lambda p: calls_b.append(p))
        bus.publish("EVT_X", {"n": 1})
        assert len(calls_a) == 1
        assert len(calls_b) == 1

    def test_event_bus_wrong_event_not_called(self):
        bus = self._make_bus()
        called = []
        bus.subscribe("EVT_A", lambda p: called.append(p))
        bus.publish("EVT_B", {"n": 1})
        assert called == []

    def test_event_bus_handler_exception_does_not_break_others(self):
        bus = self._make_bus()
        results = []

        def bad_handler(payload):
            raise RuntimeError("boom")

        def good_handler(payload):
            results.append(payload)

        bus.subscribe("EVT_C", bad_handler)
        bus.subscribe("EVT_C", good_handler)
        bus.publish("EVT_C", {"ok": True})
        assert len(results) == 1
        assert results[0] == {"ok": True}

    def test_event_bus_no_subscribers_no_error(self):
        bus = self._make_bus()
        # Should not raise
        bus.publish("UNKNOWN_EVENT", {"x": 1})


# ===========================================================================
# Permissions (backend/permissions.py)
# ===========================================================================

class TestSession:
    def _make_session(self, perms=None, mask_unlock_until=None):
        from backend.permissions import Session
        return Session(
            user_id=1,
            username="tester",
            full_name="Test User",
            roles={"test_role"},
            permissions=set(perms or []),
            mask_unlock_until=mask_unlock_until,
        )

    def test_session_has_permission(self):
        s = self._make_session(perms=["student.write", "student.read"])
        assert s.has("student.write") is True

    def test_session_lacks_permission(self):
        s = self._make_session(perms=["student.read"])
        assert s.has("student.write") is False

    def test_session_has_any_one_match(self):
        s = self._make_session(perms=["housing.read"])
        assert s.has_any(["student.write", "housing.read"]) is True

    def test_session_has_any_no_match(self):
        s = self._make_session(perms=["housing.read"])
        assert s.has_any(["student.write", "admin.all"]) is False

    def test_session_mask_unlocked_when_future(self):
        future = datetime.utcnow() + timedelta(minutes=5)
        s = self._make_session(mask_unlock_until=future)
        assert s.mask_unlocked() is True

    def test_session_mask_unlocked_when_past(self):
        past = datetime.utcnow() - timedelta(minutes=5)
        s = self._make_session(mask_unlock_until=past)
        assert s.mask_unlocked() is False

    def test_session_mask_unlocked_when_none(self):
        s = self._make_session(mask_unlock_until=None)
        assert s.mask_unlocked() is False


class TestPermissionDenied:
    def test_permission_denied_exception(self):
        from backend.permissions import PermissionDenied

        exc = PermissionDenied("student.write")
        assert exc.code == "student.write"
        assert "student.write" in str(exc)


class TestRequiresDecorator:
    def test_requires_decorator_allows_authorized(self):
        from backend.permissions import requires, Session

        class _Dummy:
            @requires("test.perm")
            def action(self, session, value):
                return value * 2

        session = Session(
            user_id=1,
            username="ok",
            full_name="OK User",
            permissions={"test.perm"},
        )
        assert _Dummy().action(session, 21) == 42

    def test_requires_decorator_blocks_unauthorized(self):
        from backend.permissions import requires, Session, PermissionDenied

        class _Dummy:
            @requires("test.perm")
            def action(self, session, value):
                return value

        session = Session(
            user_id=1,
            username="nope",
            full_name="No Perms",
            permissions=set(),
        )
        with pytest.raises(PermissionDenied) as exc_info:
            _Dummy().action(session, 1)
        assert exc_info.value.code == "test.perm"


# ===========================================================================
# Config (backend/config.py)
# ===========================================================================

class TestConfig:
    @pytest.fixture(autouse=True)
    def _isolate_config(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        # Remove CRHGC_DB override so default logic is exercised unless
        # a specific test sets it.
        monkeypatch.delenv("CRHGC_DB", raising=False)

    def test_data_dir_creates_directory(self, tmp_path):
        from backend.config import data_dir

        d = data_dir()
        assert isinstance(d, Path)
        assert d.is_dir()

    def test_db_path_default(self):
        from backend.config import db_path, data_dir

        p = db_path()
        assert str(data_dir()) in str(p)

    def test_db_path_override(self, monkeypatch, tmp_path):
        from backend.config import db_path

        custom = str(tmp_path / "custom.db")
        monkeypatch.setenv("CRHGC_DB", custom)
        assert str(db_path()) == custom

    def test_key_path(self):
        from backend.config import key_path, data_dir

        p = key_path()
        assert str(data_dir()) in str(p)
        assert "key.bin" in str(p)

    def test_evidence_dir_creates(self):
        from backend.config import evidence_dir

        d = evidence_dir()
        assert d.is_dir()
        assert "evidence" in str(d)

    def test_snapshot_dir_creates(self):
        from backend.config import snapshot_dir

        d = snapshot_dir()
        assert d.is_dir()
        assert "snapshots" in str(d)

    def test_config_constants(self):
        from backend import config

        assert isinstance(config.PBKDF2_ITERATIONS, int)
        assert config.PBKDF2_ITERATIONS > 0
        assert isinstance(config.TEMPLATE_VARIABLES, set)
        assert len(config.TEMPLATE_VARIABLES) > 0
        assert "StudentName" in config.TEMPLATE_VARIABLES
