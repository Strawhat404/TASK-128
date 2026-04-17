"""API tests for SearchService: global search, saved searches, synonyms."""
from __future__ import annotations

import pytest

from backend.models import StudentDTO
from backend.permissions import PermissionDenied, Session
from backend import db as _db


# ---- Helpers ---------------------------------------------------------------

def _create_student(container, session, sid="S1", name="Alice Smith"):
    return container.students.create(
        session, StudentDTO(student_id=sid, full_name=name,
                            college="Engineering", housing_status="pending"))


def _create_resource(container, session, title="Algebra Notes"):
    return container.resources.create_resource(session, title)


def _create_employer(container, session, name="TestCorp"):
    return container.compliance.submit_employer(
        session, name=name, ein="99-9999999", contact_email="t@e.com")


# ---- Global search ---------------------------------------------------------

class TestGlobalSearch:
    def test_finds_student_by_name(self, container, admin_session):
        _create_student(container, admin_session, "GS1", "Searchable Student")
        hits = container.search.global_search(
            admin_session, "Searchable", types={"student"}, fuzzy=False)
        assert any(h.entity_type == "student" for h in hits)
        assert any("Searchable" in h.title for h in hits)

    def test_finds_resource_by_title(self, container, admin_session):
        _create_resource(container, admin_session, "Quantum Physics Guide")
        hits = container.search.global_search(
            admin_session, "Quantum", types={"resource"}, fuzzy=False)
        assert any(h.entity_type == "resource" for h in hits)

    def test_finds_employer_by_name(self, container, admin_session):
        _create_employer(container, admin_session, "GlobalSearch Corp")
        hits = container.search.global_search(
            admin_session, "GlobalSearch", types={"employer"}, fuzzy=False)
        assert any(h.entity_type == "employer" for h in hits)

    def test_finds_cases(self, container, admin_session):
        _create_employer(container, admin_session, "CaseSearch Inc")
        hits = container.search.global_search(
            admin_session, "CaseSearch", types={"case"}, fuzzy=False)
        assert any(h.entity_type == "case" for h in hits)

    def test_limit_respected(self, container, admin_session):
        for i in range(5):
            _create_student(container, admin_session, f"LIM{i}", f"Limit Test {i}")
        hits = container.search.global_search(
            admin_session, "Limit", limit=2, fuzzy=False)
        assert len(hits) <= 2

    def test_types_filter(self, container, admin_session):
        _create_student(container, admin_session, "TF1", "TypeFilter Student")
        _create_resource(container, admin_session, "TypeFilter Resource")
        hits = container.search.global_search(
            admin_session, "TypeFilter", types={"student"}, fuzzy=False)
        assert all(h.entity_type == "student" for h in hits)

    def test_hidden_employers_excluded(self, container, admin_session):
        _create_employer(container, admin_session, "Visible Corp")
        _create_employer(container, admin_session, "Hidden Corp")
        emps = container.compliance.list_employers(admin_session)
        hid = [e["id"] for e in emps if e["name"] == "Hidden Corp"][0]
        container.violations.throttle(admin_session, hid, "spam")
        hits = container.search.global_search(
            admin_session, "Corp", types={"employer"}, fuzzy=False)
        titles = [h.title for h in hits]
        assert "Visible Corp" in titles
        assert "Hidden Corp" not in titles

    def test_include_hidden(self, container, admin_session):
        _create_employer(container, admin_session, "VisInc Corp")
        _create_employer(container, admin_session, "HidInc Corp")
        emps = container.compliance.list_employers(admin_session)
        hid = [e["id"] for e in emps if e["name"] == "HidInc Corp"][0]
        container.violations.throttle(admin_session, hid, "spam")
        hits = container.search.global_search(
            admin_session, "HidInc", types={"employer"},
            fuzzy=False, include_hidden=True)
        assert any(h.title == "HidInc Corp" for h in hits)

    def test_denied_without_permission(self, container, admin_session):
        bare = Session(user_id=999, username="bare", full_name="Bare")
        with pytest.raises(PermissionDenied):
            container.search.global_search(bare, "test")


# ---- Saved searches --------------------------------------------------------

class TestSavedSearches:
    def test_save_and_list(self, container, admin_session):
        sid = container.search.save_search(
            admin_session, "my search", "global",
            {"text": "algebra"})
        assert sid > 0
        saved = container.search.list_saved(admin_session)
        assert any(s["name"] == "my search" for s in saved)

    def test_pin_search(self, container, admin_session):
        sid = container.search.save_search(
            admin_session, "pinnable", "global", {"text": "test"})
        container.search.pin(admin_session, sid, True)
        saved = container.search.list_saved(admin_session)
        pinned = [s for s in saved if s["name"] == "pinnable"][0]
        assert pinned["pinned"] == 1

    def test_delete_saved(self, container, admin_session):
        sid = container.search.save_search(
            admin_session, "deletable", "global", {"text": "test"})
        container.search.delete_saved(admin_session, sid)
        saved = container.search.list_saved(admin_session)
        assert not any(s["name"] == "deletable" for s in saved)

    def test_saved_search_isolation(self, container, admin_session,
                                    coordinator_session):
        container.search.save_search(
            admin_session, "admin only", "global", {"text": "x"})
        coord_saved = container.search.list_saved(coordinator_session)
        assert not any(s["name"] == "admin only" for s in coord_saved)
