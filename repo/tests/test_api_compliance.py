"""API tests for EmployerComplianceService, EvidenceService,
SensitiveWordService, and ViolationActionService."""
from __future__ import annotations

import pytest

from backend import db as _db
from backend.services.auth import BizError
from backend.permissions import PermissionDenied, Session


# ---- Helpers ---------------------------------------------------------------

def _submit_employer(container, session, name="Acme Co"):
    return container.compliance.submit_employer(
        session, name=name, ein="11-1111111",
        contact_email="ops@acme.example")


def _get_employer_id(case_id):
    return _db.get_connection().execute(
        "SELECT employer_id FROM employer_cases WHERE id=?",
        (case_id,)).fetchone()["employer_id"]


def _upload_evidence(container, session, employer_id, tmp_path, name="doc.pdf"):
    f = tmp_path / name
    f.write_bytes(b"%PDF-1.4 fake verification document content")
    return container.evidence.upload(session, employer_id, f)


# ---- EmployerComplianceService ---------------------------------------------

class TestSubmitEmployer:
    def test_creates_employer_and_case(self, container, admin_session):
        case_id = _submit_employer(container, admin_session)
        assert case_id > 0
        emps = container.compliance.list_employers(admin_session)
        assert any(e["name"] == "Acme Co" for e in emps)

    def test_list_employers(self, container, admin_session):
        _submit_employer(container, admin_session, "Alpha")
        _submit_employer(container, admin_session, "Beta")
        emps = container.compliance.list_employers(admin_session)
        names = [e["name"] for e in emps]
        assert "Alpha" in names
        assert "Beta" in names


class TestListCases:
    def test_by_state(self, container, admin_session):
        _submit_employer(container, admin_session)
        cases = container.compliance.list_cases(admin_session, state="submitted")
        assert len(cases) >= 1
        assert all(c.state == "submitted" for c in cases)

    def test_by_kind(self, container, admin_session):
        _submit_employer(container, admin_session)
        cases = container.compliance.list_cases(admin_session, kind="onboarding")
        assert len(cases) >= 1
        assert all(c.kind == "onboarding" for c in cases)


class TestAssignReviewer:
    def test_sets_reviewer(self, container, admin_session):
        case_id = _submit_employer(container, admin_session)
        container.compliance.assign_reviewer(
            admin_session, case_id, admin_session.user_id)
        cases = container.compliance.list_cases(admin_session)
        case = [c for c in cases if c.id == case_id][0]
        assert case.state == "under_review"
        assert case.reviewer_id == admin_session.user_id


class TestDecide:
    def test_approve_with_evidence(self, container, admin_session, tmp_path):
        case_id = _submit_employer(container, admin_session)
        emp_id = _get_employer_id(case_id)
        _upload_evidence(container, admin_session, emp_id, tmp_path)
        decided = container.compliance.decide(
            admin_session, case_id, "approve", notes="all clear")
        assert decided.decision == "approve"
        assert decided.state == "approved"

    def test_approve_without_evidence_fails(self, container, admin_session):
        case_id = _submit_employer(container, admin_session)
        with pytest.raises(BizError) as ei:
            container.compliance.decide(
                admin_session, case_id, "approve", notes="ok")
        assert ei.value.code == "EVIDENCE_REQUIRED"

    def test_reject_without_evidence_ok(self, container, admin_session):
        case_id = _submit_employer(container, admin_session)
        decided = container.compliance.decide(
            admin_session, case_id, "reject", notes="nope")
        assert decided.decision == "reject"
        assert decided.state == "rejected"

    def test_bad_decision(self, container, admin_session, tmp_path):
        case_id = _submit_employer(container, admin_session)
        with pytest.raises(BizError) as ei:
            container.compliance.decide(
                admin_session, case_id, "maybe", notes="")
        assert ei.value.code == "BAD_DECISION"


class TestViolations:
    def test_open_violation(self, container, admin_session):
        case_id = _submit_employer(container, admin_session)
        emp_id = _get_employer_id(case_id)
        viol_id = container.compliance.open_violation(
            admin_session, emp_id, "policy breach")
        assert viol_id > 0

    def test_resolve_violation(self, container, admin_session):
        case_id = _submit_employer(container, admin_session)
        emp_id = _get_employer_id(case_id)
        viol_id = container.compliance.open_violation(
            admin_session, emp_id, "policy breach")
        container.compliance.resolve_violation(
            admin_session, viol_id, "corrected")
        cases = container.compliance.list_cases(admin_session, kind="violation")
        resolved = [c for c in cases if c.id == viol_id]
        assert len(resolved) == 1
        assert resolved[0].state == "resolved"


# ---- EvidenceService -------------------------------------------------------

class TestEvidence:
    def test_upload_returns_evidence_file(self, container, admin_session, tmp_path):
        case_id = _submit_employer(container, admin_session)
        emp_id = _get_employer_id(case_id)
        ev = _upload_evidence(container, admin_session, emp_id, tmp_path)
        assert ev.id > 0
        assert ev.employer_id == emp_id
        assert len(ev.sha256) == 64
        assert ev.size_bytes > 0

    def test_verify_integrity(self, container, admin_session, tmp_path):
        case_id = _submit_employer(container, admin_session)
        emp_id = _get_employer_id(case_id)
        ev = _upload_evidence(container, admin_session, emp_id, tmp_path)
        assert container.evidence.verify(ev.id, session=admin_session) is True

    def test_list_for_employer(self, container, admin_session, tmp_path):
        case_id = _submit_employer(container, admin_session)
        emp_id = _get_employer_id(case_id)
        _upload_evidence(container, admin_session, emp_id, tmp_path, "a.pdf")
        _upload_evidence(container, admin_session, emp_id, tmp_path, "b.pdf")
        files = container.evidence.list_for_employer(
            emp_id, session=admin_session)
        assert len(files) == 2

    def test_list_requires_session(self, container, admin_session, tmp_path):
        case_id = _submit_employer(container, admin_session)
        emp_id = _get_employer_id(case_id)
        with pytest.raises(PermissionDenied):
            container.evidence.list_for_employer(emp_id)

    def test_upload_missing_file(self, container, admin_session, tmp_path):
        case_id = _submit_employer(container, admin_session)
        emp_id = _get_employer_id(case_id)
        with pytest.raises(BizError) as ei:
            container.evidence.upload(
                admin_session, emp_id, tmp_path / "nonexistent.pdf")
        assert ei.value.code == "FILE_MISSING"


# ---- SensitiveWordService --------------------------------------------------

class TestSensitiveWords:
    def test_add_and_scan(self, container, admin_session):
        container.sensitive.add(admin_session, "badword", "high", "test")
        hits = container.sensitive.scan("This contains badword in text")
        assert len(hits) >= 1
        assert any(h["word"] == "badword" for h in hits)
        assert any(h["severity"] == "high" for h in hits)

    def test_scan_empty_text(self, container, admin_session):
        assert container.sensitive.scan("") == []

    def test_scan_no_matches(self, container, admin_session):
        hits = container.sensitive.scan("perfectly clean text")
        high_hits = [h for h in hits if h["severity"] == "high"]
        # may have seeded words, but clean text shouldn't match custom high ones
        assert not any(h["word"] == "nonexistent_word_xyz" for h in hits)

    def test_bad_severity(self, container, admin_session):
        with pytest.raises(BizError) as ei:
            container.sensitive.add(admin_session, "word", "extreme")
        assert ei.value.code == "BAD_SEVERITY"

    def test_list_words(self, container, admin_session):
        container.sensitive.add(admin_session, "testword", "medium")
        words = container.sensitive.list()
        assert any(w["word"] == "testword" for w in words)

    def test_remove_word(self, container, admin_session):
        container.sensitive.add(admin_session, "removeword", "low")
        words = container.sensitive.list()
        wid = [w["id"] for w in words if w["word"] == "removeword"][0]
        container.sensitive.remove(admin_session, wid)
        words2 = container.sensitive.list()
        assert not any(w["word"] == "removeword" for w in words2)


# ---- ViolationActionService ------------------------------------------------

class TestViolationActions:
    def _make_employer(self, container, session, tmp_path, name="TestCo"):
        case_id = _submit_employer(container, session, name)
        emp_id = _get_employer_id(case_id)
        _upload_evidence(container, session, emp_id, tmp_path)
        container.compliance.decide(session, case_id, "approve", notes="ok")
        return emp_id

    def test_takedown(self, container, admin_session, tmp_path):
        emp_id = self._make_employer(container, admin_session, tmp_path, "TD Co")
        action_id = container.violations.takedown(
            admin_session, emp_id, "policy violation")
        assert action_id > 0
        emp = _db.get_connection().execute(
            "SELECT status FROM employers WHERE id=?", (emp_id,)).fetchone()
        assert emp["status"] == "taken_down"

    def test_suspend_valid_days(self, container, admin_session, tmp_path):
        emp_id = self._make_employer(container, admin_session, tmp_path, "Sus Co")
        action_id = container.violations.suspend(
            admin_session, emp_id, 30, "temp issue")
        assert action_id > 0

    def test_suspend_invalid_days(self, container, admin_session, tmp_path):
        emp_id = self._make_employer(container, admin_session, tmp_path, "Bad Co")
        with pytest.raises(BizError) as ei:
            container.violations.suspend(
                admin_session, emp_id, 45, "invalid")
        assert ei.value.code == "BAD_DURATION"

    def test_throttle(self, container, admin_session, tmp_path):
        emp_id = self._make_employer(
            container, admin_session, tmp_path, "Thr Co")
        container.violations.throttle(admin_session, emp_id, "spam")
        emp = _db.get_connection().execute(
            "SELECT status FROM employers WHERE id=?", (emp_id,)).fetchone()
        assert emp["status"] == "throttled"

    def test_revoke_restores_status(self, container, admin_session, tmp_path):
        emp_id = self._make_employer(
            container, admin_session, tmp_path, "Rev Co")
        action_id = container.violations.takedown(
            admin_session, emp_id, "temp issue")
        container.violations.revoke(admin_session, action_id, "resolved")
        emp = _db.get_connection().execute(
            "SELECT status FROM employers WHERE id=?", (emp_id,)).fetchone()
        assert emp["status"] == "approved"

    def test_is_hidden_from_default_search(self, container, admin_session,
                                           tmp_path):
        emp_id = self._make_employer(
            container, admin_session, tmp_path, "Hide Co")
        assert not container.violations.is_hidden_from_default_search(emp_id)
        container.violations.throttle(admin_session, emp_id, "hide")
        assert container.violations.is_hidden_from_default_search(emp_id)

    def test_list_for_employer(self, container, admin_session, tmp_path):
        emp_id = self._make_employer(
            container, admin_session, tmp_path, "List Co")
        container.violations.takedown(admin_session, emp_id, "reason")
        actions = container.violations.list_for_employer(
            emp_id, session=admin_session)
        assert len(actions) >= 1

    def test_list_requires_session(self, container, admin_session, tmp_path):
        emp_id = self._make_employer(
            container, admin_session, tmp_path, "Auth Co")
        with pytest.raises(PermissionDenied):
            container.violations.list_for_employer(emp_id)
