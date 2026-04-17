"""End-to-end multi-service workflow tests.

These tests exercise realistic multi-step flows that cross multiple services,
proving services compose correctly when driven through the same DTO/session
API the desktop GUI uses.
"""
from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

import pytest

from backend import audit, config, crypto, db as _db, events
from backend.models import Page, Paged, StudentDTO
from backend.permissions import PermissionDenied, Session
from backend.services.auth import BizError


# ---------------------------------------------------------------------------
# 1. Full student onboarding workflow
# ---------------------------------------------------------------------------

def test_full_student_onboarding_workflow(container, admin_session, tmp_path):
    """Create student -> assign bed -> verify housing_status on_campus
    -> check audit chain -> verify bed appears occupied in list_beds."""
    # Create student with pending status
    student = container.students.create(
        admin_session,
        StudentDTO(student_id="ONB-001", full_name="Alice Onboard",
                   college="Engineering", class_year=2027,
                   email="alice@example.edu", phone="555-1111",
                   housing_status="pending"))
    assert student.id > 0
    assert student.housing_status == "pending"

    # Get a vacant bed
    beds = container.housing.list_beds(admin_session)
    assert len(beds) > 0
    vacant_bed = [b for b in beds if not b.occupied][0]

    # Assign bed
    assignment = container.housing.assign_bed(
        admin_session, student.id, vacant_bed.id,
        effective_date=date(2026, 8, 15), reason="new student onboarding")

    # Verify student housing_status is now on_campus
    updated_student = container.students.get(admin_session, student.id)
    assert updated_student.housing_status == "on_campus"

    # Check audit chain
    result = audit.verify_chain()
    assert result.ok
    assert result.checked > 0

    # Verify bed appears occupied in list_beds
    beds_after = container.housing.list_beds(admin_session)
    assigned_bed = [b for b in beds_after if b.id == vacant_bed.id][0]
    assert assigned_bed.occupied is True


# ---------------------------------------------------------------------------
# 2. Student transfer workflow
# ---------------------------------------------------------------------------

def test_student_transfer_workflow(container, admin_session):
    """Create student -> assign bed A -> transfer to bed B -> verify old bed
    vacated, new bed assigned -> verify assignment_history has both entries."""
    student = container.students.create(
        admin_session,
        StudentDTO(student_id="XFER-001", full_name="Bob Transfer",
                   college="Arts", class_year=2028,
                   email="bob@example.edu", phone="555-2222",
                   housing_status="pending"))

    beds = container.housing.list_beds(admin_session, vacant_only=True)
    assert len(beds) >= 2
    bed_a = beds[0]
    bed_b = beds[1]

    # Assign to bed A
    container.housing.assign_bed(
        admin_session, student.id, bed_a.id,
        effective_date=date(2026, 8, 15), reason="initial placement")

    # Transfer to bed B
    container.housing.transfer(
        admin_session, student.id, bed_b.id,
        effective_date=date(2026, 9, 1), reason="room change")

    # Verify old bed is vacated
    beds_after = container.housing.list_beds(admin_session)
    old_bed = [b for b in beds_after if b.id == bed_a.id][0]
    assert old_bed.occupied is False

    # Verify new bed is occupied
    new_bed = [b for b in beds_after if b.id == bed_b.id][0]
    assert new_bed.occupied is True

    # Verify assignment_history has both entries
    history = container.housing.assignment_history(
        admin_session, student_id=student.id)
    assert len(history) >= 2
    # Most recent first (by effective_date DESC)
    assert history[0].bed_id == bed_b.id
    assert history[1].bed_id == bed_a.id
    assert history[1].end_date is not None  # old assignment ended


# ---------------------------------------------------------------------------
# 3. Full compliance workflow
# ---------------------------------------------------------------------------

def test_full_compliance_workflow(container, admin_session, tmp_path):
    """Submit employer -> upload evidence -> add sensitive word -> scan
    -> decide approve -> verify employer status approved -> open violation
    -> takedown -> verify hidden from search -> revoke -> verify visible
    again."""
    # Submit employer
    case_id = container.compliance.submit_employer(
        admin_session, name="Compliance Corp",
        ein="11-1111111", contact_email="comp@example.com")

    conn = _db.get_connection()
    emp_id = conn.execute(
        "SELECT employer_id FROM employer_cases WHERE id=?",
        (case_id,)).fetchone()["employer_id"]

    # Upload evidence
    evidence_file = tmp_path / "evidence.pdf"
    evidence_file.write_bytes(b"%PDF-1.4 real evidence document\n")
    container.evidence.upload(admin_session, emp_id, evidence_file,
                              case_id=case_id)

    # Add a sensitive word and scan
    container.sensitive.add(admin_session, "test_forbidden_word",
                            severity="low", category="test")
    hits = container.sensitive.scan("Compliance Corp seems safe")
    assert not any(h["severity"] == "high" for h in hits)

    # Approve
    decided = container.compliance.decide(
        admin_session, case_id, "approve", notes="Looks good")
    assert decided.decision == "approve"

    # Verify employer status approved
    employers = container.compliance.list_employers(admin_session)
    emp = [e for e in employers if e["id"] == emp_id][0]
    assert emp["status"] == "approved"

    # Open violation
    violation_case_id = container.compliance.open_violation(
        admin_session, emp_id, notes="Suspicious activity reported")

    # Takedown
    action_id = container.violations.takedown(
        admin_session, emp_id, reason="Under investigation")

    # Verify hidden from default search
    search_results = container.search.global_search(
        admin_session, "Compliance Corp", include_hidden=False)
    employer_hits = [h for h in search_results if h.entity_type == "employer"
                     and h.entity_id == emp_id]
    assert len(employer_hits) == 0

    # Revoke takedown
    container.violations.revoke(admin_session, action_id, reason="Cleared")

    # Verify visible again
    search_results2 = container.search.global_search(
        admin_session, "Compliance Corp", include_hidden=False)
    employer_hits2 = [h for h in search_results2 if h.entity_type == "employer"
                      and h.entity_id == emp_id]
    assert len(employer_hits2) > 0


# ---------------------------------------------------------------------------
# 4. Resource full lifecycle
# ---------------------------------------------------------------------------

def test_resource_full_lifecycle(container, admin_session):
    """Create resource -> add version -> attach to catalog -> submit for
    review -> approve -> publish with semver bump -> add another version
    -> publish with patch bump -> unpublish -> place on hold -> release
    hold."""
    # Create
    res = container.resources.create_resource(admin_session, "Lifecycle Resource")
    assert res.status == "active"

    # Add version 1
    v1 = container.resources.add_version(
        admin_session, res.id, "First version", "Body of v1")
    assert v1.version_no == 1

    # Attach to catalog
    container.catalog.attach(admin_session, res.id, node_id=None,
                             type_code=None)

    # Submit for review
    container.catalog.submit_for_review(admin_session, res.id)

    # Approve
    container.catalog.review(admin_session, res.id, "approve", "Looks great")

    # Publish with minor (default) bump
    pub_v1 = container.resources.publish_version(admin_session, v1.id,
                                                  semver_level="minor")
    assert pub_v1.status == "published"

    # Check semver was bumped
    cat = container.catalog.get_attachment(res.id)
    assert cat is not None
    first_semver = cat["semver"]

    # Add version 2
    v2 = container.resources.add_version(
        admin_session, res.id, "Second version", "Body of v2")
    assert v2.version_no == 2

    # Need to re-submit and re-approve for the new version
    container.catalog.submit_for_review(admin_session, res.id)
    container.catalog.review(admin_session, res.id, "approve", "v2 ok")

    # Publish with patch bump
    pub_v2 = container.resources.publish_version(admin_session, v2.id,
                                                  semver_level="patch")
    assert pub_v2.status == "published"

    # Verify semver increased
    cat2 = container.catalog.get_attachment(res.id)
    assert cat2["semver"] != first_semver

    # Unpublish
    unpub = container.resources.unpublish_version(admin_session, pub_v2.id)
    assert unpub.status == "unpublished"

    # Place on hold
    held = container.resources.place_on_hold(
        admin_session, res.id, reason="Reviewing content")
    assert held.status == "on_hold"

    # Release hold
    released = container.resources.release_hold(admin_session, res.id)
    assert released.status == "active"


# ---------------------------------------------------------------------------
# 5. BOM full lifecycle
# ---------------------------------------------------------------------------

def test_bom_full_lifecycle(container, admin_session):
    """Create style -> add BOM items -> add routing steps -> verify cost
    calculation -> submit for approval -> first approve (admin) -> create
    second admin user -> final approve (second user) -> verify released
    state -> open change request -> verify BOM copied -> modify new draft
    -> submit -> approve flow again."""
    # Create style
    style = container.bom.create_style(
        admin_session, "STY-001", "Test Style", description="A test style")
    versions = container.bom.list_versions(style.id)
    assert len(versions) == 1
    v1 = versions[0]
    assert v1.state == "draft"

    # Add BOM items
    container.bom.add_bom_item(
        admin_session, v1.id, component_code="FAB-100",
        description="Main fabric", quantity=2.0, unit_cost_usd=10.0)
    container.bom.add_bom_item(
        admin_session, v1.id, component_code="THR-200",
        description="Thread", quantity=1.0, unit_cost_usd=2.0)

    # Add routing steps
    container.bom.add_routing_step(
        admin_session, v1.id, operation="Cut",
        machine="CUT-1", setup_minutes=5, run_minutes=10,
        rate_per_hour_usd=30.0)
    container.bom.add_routing_step(
        admin_session, v1.id, operation="Sew",
        machine="SEW-1", setup_minutes=3, run_minutes=15,
        rate_per_hour_usd=25.0)

    # Verify cost calculation
    cost = container.bom.compute_cost(v1.id)
    # Materials: 2*10 + 1*2 = 22.0
    # Labor: (5+10)/60 * 30 + (3+15)/60 * 25 = 7.5 + 7.5 = 15.0
    assert cost == pytest.approx(37.0, abs=0.01)

    # Submit for approval
    container.bom.submit_for_approval(admin_session, v1.id)
    v1_after = container.bom.get_version(v1.id)
    assert v1_after.state == "submitted"

    # First approve (admin)
    container.bom.first_approve(admin_session, v1.id)
    v1_first = container.bom.get_version(v1.id)
    assert v1_first.state == "first_approved"

    # Create second admin user for final approve
    h, salt = crypto.hash_password("SecondAdmin1!")
    conn = _db.get_connection()
    conn.execute(
        "INSERT INTO users(username, full_name, password_hash, password_salt) "
        "VALUES ('admin2', 'Admin2', ?, ?)", (h, salt))
    uid = conn.execute(
        "SELECT id FROM users WHERE username='admin2'").fetchone()["id"]
    rid = conn.execute(
        "SELECT id FROM roles WHERE code='system_admin'").fetchone()["id"]
    conn.execute("INSERT INTO user_roles(user_id, role_id) VALUES (?, ?)",
                 (uid, rid))
    session2 = container.auth.login("admin2", "SecondAdmin1!")

    # Final approve (different user)
    container.bom.final_approve(session2, v1.id)
    v1_released = container.bom.get_version(v1.id)
    assert v1_released.state == "released"
    assert v1_released.released_at is not None

    # Open change request
    cr_id = container.bom.open_change_request(
        admin_session, style.id, v1.id,
        reason="Customer requested material change")
    crs = container.bom.list_change_requests(style.id)
    assert len(crs) == 1

    # Verify BOM was copied to new draft version
    versions_after = container.bom.list_versions(style.id)
    assert len(versions_after) == 2
    new_draft = [v for v in versions_after if v.state == "draft"][0]
    new_bom = container.bom.list_bom(new_draft.id)
    assert len(new_bom) == 2  # same items as original

    # Modify the new draft (add an item)
    container.bom.add_bom_item(
        admin_session, new_draft.id, component_code="BTN-300",
        description="Buttons", quantity=6.0, unit_cost_usd=0.50)

    # Submit -> approve flow again
    container.bom.submit_for_approval(admin_session, new_draft.id)
    container.bom.first_approve(admin_session, new_draft.id)
    container.bom.final_approve(session2, new_draft.id)
    v2_released = container.bom.get_version(new_draft.id)
    assert v2_released.state == "released"


# ---------------------------------------------------------------------------
# 6. Notification event trigger flow
# ---------------------------------------------------------------------------

def test_notification_event_trigger_flow(container, admin_session):
    """Create student -> verify STUDENT_CREATED event generates queued
    notifications (via trigger rules in seed) -> drain queue -> check
    inbox has message."""
    # First, check if there are trigger rules for STUDENT_CREATED; if not,
    # we rely on BED_ASSIGNED which is seeded.
    student = container.students.create(
        admin_session,
        StudentDTO(student_id="NOTIF-001", full_name="Notify Me",
                   college="Science", class_year=2027,
                   email="notify@example.edu", phone="555-3333",
                   housing_status="pending"))

    beds = container.housing.list_beds(admin_session, vacant_only=True)
    assert len(beds) > 0

    # BED_ASSIGNED has a trigger rule -> notification will be queued
    container.housing.assign_bed(
        admin_session, student.id, beds[0].id,
        effective_date=date(2026, 8, 20), reason="notification test")

    # Check that messages got queued
    conn = _db.get_connection()
    queued = conn.execute(
        "SELECT COUNT(*) AS n FROM notif_messages WHERE status='queued'"
    ).fetchone()["n"]
    assert queued > 0

    # Drain queue
    delivered = container.notifications.drain_queue()
    assert delivered > 0

    # Check inbox for admin
    inbox = container.notifications.inbox(admin_session)
    assert len(inbox) > 0


# ---------------------------------------------------------------------------
# 7. Checkpoint crash recovery flow
# ---------------------------------------------------------------------------

def test_checkpoint_crash_recovery_flow(container, admin_session):
    """Save workspace state -> save draft -> simulate crash (close_and_seal)
    -> reopen -> load_workspace returns saved state -> load_draft returns
    saved draft data."""
    workspace_data = {"open_tabs": ["students", "housing"], "active_tab": 0}
    container.checkpoints.save_workspace(admin_session, workspace_data)

    draft_data = {"form": "new_student", "name": "Draft Student", "college": "CS"}
    container.checkpoints.save_draft(admin_session, "new_student", draft_data)

    # Simulate crash by closing and sealing
    _db.close_and_seal()

    # Reopen (get_connection re-opens from encrypted blob)
    _db.get_connection()

    # Load workspace should return saved state
    loaded_ws = container.checkpoints.load_workspace(admin_session)
    assert loaded_ws is not None
    assert loaded_ws["open_tabs"] == ["students", "housing"]
    assert loaded_ws["active_tab"] == 0

    # Load draft should return saved draft data
    loaded_draft = container.checkpoints.load_draft(admin_session, "new_student")
    assert loaded_draft is not None
    assert loaded_draft["form"] == "new_student"
    assert loaded_draft["name"] == "Draft Student"


# ---------------------------------------------------------------------------
# 8. Audit chain integrity across services
# ---------------------------------------------------------------------------

def test_audit_chain_integrity_across_services(container, admin_session,
                                                tmp_path):
    """Perform operations across multiple services (create student, assign
    bed, submit employer, create resource) -> verify_chain returns ok with
    correct count."""
    initial = audit.verify_chain()
    initial_count = initial.checked

    # Student operation
    student = container.students.create(
        admin_session,
        StudentDTO(student_id="AUDIT-001", full_name="Audit Student",
                   college="Law", class_year=2027,
                   email="audit@example.edu", phone="555-4444",
                   housing_status="pending"))

    # Housing operation
    beds = container.housing.list_beds(admin_session, vacant_only=True)
    container.housing.assign_bed(
        admin_session, student.id, beds[0].id,
        effective_date=date(2026, 8, 15), reason="audit test")

    # Compliance operation
    container.compliance.submit_employer(
        admin_session, name="Audit Employer", ein="22-2222222",
        contact_email="audit_emp@example.com")

    # Resource operation
    container.resources.create_resource(admin_session, "Audit Resource")

    # Verify chain
    result = audit.verify_chain()
    assert result.ok
    assert result.checked > initial_count


# ---------------------------------------------------------------------------
# 9. Search across all entity types
# ---------------------------------------------------------------------------

def test_search_across_all_entity_types(container, admin_session, tmp_path):
    """Create student, resource, employer -> global_search with broad query
    -> verify results contain all entity types."""
    # Use a unique keyword in all entities
    keyword = "UniversalSearch"

    container.students.create(
        admin_session,
        StudentDTO(student_id="SRCH-001", full_name=f"{keyword} Student",
                   college="Arts", class_year=2027,
                   email="search@example.edu", phone="555-5555",
                   housing_status="pending"))

    container.resources.create_resource(
        admin_session, f"{keyword} Resource")

    container.compliance.submit_employer(
        admin_session, name=f"{keyword} Employer",
        ein="33-3333333", contact_email="emp@example.com")

    # Global search
    results = container.search.global_search(
        admin_session, keyword, fuzzy=False)

    entity_types = {h.entity_type for h in results}
    assert "student" in entity_types
    assert "resource" in entity_types
    assert "employer" in entity_types


# ---------------------------------------------------------------------------
# 10. At-rest encryption round trip
# ---------------------------------------------------------------------------

def test_at_rest_encryption_round_trip(container, admin_session):
    """Create data -> close_and_seal -> verify no plaintext on disk
    -> reopen -> verify all data accessible."""
    if _db.HAVE_SQLCIPHER:
        pytest.skip("SQLCipher handles encryption differently")

    container.students.create(
        admin_session,
        StudentDTO(student_id="ENC-001", full_name="Encrypted Student",
                   college="CompSci", class_year=2026,
                   email="enc@example.edu", phone="555-6666",
                   ssn_last4="1234", housing_status="pending"))

    _db.close_and_seal()

    # Verify the encrypted blob exists and plaintext DB does not contain
    # recognizable plaintext
    enc_path = config.db_path().with_suffix(config.db_path().suffix + ".enc")
    if enc_path.is_file():
        raw = enc_path.read_bytes()
        # The encrypted blob should not contain plaintext student name
        assert b"Encrypted Student" not in raw

    # Reopen and verify data is accessible
    conn = _db.get_connection()
    row = conn.execute(
        "SELECT id FROM students WHERE student_id_ext='ENC-001'"
    ).fetchone()
    assert row is not None

    student = container.students.get(admin_session, row["id"])
    assert student.full_name == "Encrypted Student"


# ---------------------------------------------------------------------------
# 11. Concurrent service operations
# ---------------------------------------------------------------------------

def test_concurrent_service_operations(container, admin_session):
    """Multiple creates across different services -> verify no
    cross-contamination and all data persists."""
    # Create multiple students
    students = []
    for i in range(5):
        s = container.students.create(
            admin_session,
            StudentDTO(student_id=f"CONC-{i:03d}", full_name=f"Concurrent {i}",
                       college="Engineering", class_year=2027,
                       email=f"conc{i}@example.edu", phone=f"555-{7000+i}",
                       housing_status="pending"))
        students.append(s)

    # Create multiple resources
    resources = []
    for i in range(3):
        r = container.resources.create_resource(
            admin_session, f"Concurrent Resource {i}")
        resources.append(r)

    # Create multiple employers
    case_ids = []
    for i in range(3):
        cid = container.compliance.submit_employer(
            admin_session, name=f"Concurrent Employer {i}",
            ein=f"44-{4440000+i}", contact_email=f"emp{i}@example.com")
        case_ids.append(cid)

    # Verify all students persisted
    for s in students:
        fetched = container.students.get(admin_session, s.id)
        assert fetched.full_name == s.full_name

    # Verify all resources persisted
    res_list = container.resources.search(admin_session, text="Concurrent Resource")
    assert len(res_list) >= 3

    # Verify all employers persisted
    emp_list = container.compliance.list_employers(admin_session)
    concurrent_emps = [e for e in emp_list
                       if e["name"].startswith("Concurrent Employer")]
    assert len(concurrent_emps) >= 3


# ---------------------------------------------------------------------------
# 12. Bulk import then search
# ---------------------------------------------------------------------------

def test_bulk_import_then_search(container, admin_session, tmp_path):
    """Import CSV with multiple students -> search finds them -> export to
    new CSV -> verify round-trip."""
    csv_in = tmp_path / "import.csv"
    rows = [
        ["student_id", "full_name", "college", "class_year", "email",
         "phone", "housing_status"],
        ["IMP-001", "Import Alice", "Engineering", "2027",
         "alice_imp@example.edu", "555-8001", "pending"],
        ["IMP-002", "Import Bob", "Science", "2028",
         "bob_imp@example.edu", "555-8002", "pending"],
        ["IMP-003", "Import Carol", "Arts", "2026",
         "carol_imp@example.edu", "555-8003", "pending"],
    ]
    with open(csv_in, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        for row in rows:
            writer.writerow(row)

    # Preview
    preview = container.students.import_csv(admin_session, csv_in)
    assert len(preview.accepted) == 3
    assert len(preview.rejected) == 0

    # Commit
    result = container.students.commit_import(admin_session, preview.preview_id)
    assert result["created"] == 3

    # Search finds them
    found = container.students.search(admin_session, text="Import")
    assert len(found) >= 3

    # Export to CSV
    csv_out = tmp_path / "export.csv"
    count = container.students.export_csv(admin_session, csv_out)
    assert count >= 3

    # Verify round-trip: exported file has the imported students
    with open(csv_out, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        exported_ids = [r["student_id"] for r in reader]
    assert "IMP-001" in exported_ids
    assert "IMP-002" in exported_ids
    assert "IMP-003" in exported_ids


# ---------------------------------------------------------------------------
# 13. Permission isolation workflow
# ---------------------------------------------------------------------------

def test_permission_isolation_workflow(container, admin_session,
                                       coordinator_session):
    """Admin creates resources and students -> coordinator can only access
    student operations -> coordinator cannot access compliance or resource
    operations."""
    # Admin creates a resource
    res = container.resources.create_resource(admin_session, "Admin Resource")
    assert res.id > 0

    # Admin creates a student
    student = container.students.create(
        admin_session,
        StudentDTO(student_id="PERM-001", full_name="Permission Student",
                   college="Law", class_year=2027,
                   email="perm@example.edu", phone="555-9001",
                   housing_status="pending"))

    # Coordinator CAN access student operations
    found = container.students.search(coordinator_session, text="Permission")
    assert len(found) >= 1

    # Coordinator CANNOT create resources
    with pytest.raises(PermissionDenied):
        container.resources.create_resource(
            coordinator_session, "Coordinator Resource")

    # Coordinator CANNOT access compliance operations
    with pytest.raises(PermissionDenied):
        container.compliance.submit_employer(
            coordinator_session, name="Coord Employer",
            ein="55-5555555", contact_email="c@example.com")


# ---------------------------------------------------------------------------
# 14. Event bus cross-service delivery
# ---------------------------------------------------------------------------

def test_event_bus_cross_service_delivery(container, admin_session):
    """Subscribe to event -> trigger operation that publishes event
    -> verify handler was called with correct payload."""
    received = []

    def handler(payload):
        received.append(payload)

    events.bus.subscribe(events.STUDENT_CREATED, handler)

    try:
        student = container.students.create(
            admin_session,
            StudentDTO(student_id="EVT-001", full_name="Event Student",
                       college="Science", class_year=2027,
                       email="evt@example.edu", phone="555-9100",
                       housing_status="pending"))

        assert len(received) == 1
        assert received[0]["student_id"] == student.id
        assert received[0]["name"] == "Event Student"
    finally:
        # Clean up subscription to avoid leaking into other tests
        events.bus._subs[events.STUDENT_CREATED].remove(handler)


# ---------------------------------------------------------------------------
# 15. Reporting reflects operations
# ---------------------------------------------------------------------------

def test_reporting_reflects_operations(container, admin_session):
    """Create students -> assign beds -> run occupancy report -> verify
    data matches."""
    # Create students and assign beds
    students = []
    for i in range(3):
        s = container.students.create(
            admin_session,
            StudentDTO(student_id=f"RPT-{i:03d}",
                       full_name=f"Report Student {i}",
                       college="Engineering", class_year=2027,
                       email=f"rpt{i}@example.edu", phone=f"555-{9200+i}",
                       housing_status="pending"))
        students.append(s)

    beds = container.housing.list_beds(admin_session, vacant_only=True)
    assigned_count = min(len(students), len(beds))
    for i in range(assigned_count):
        container.housing.assign_bed(
            admin_session, students[i].id, beds[i].id,
            effective_date=date(2026, 8, 15), reason="report test")

    # Run occupancy report
    report = container.reporting.occupancy(admin_session)
    assert report.title == "Occupancy by Dorm"
    assert len(report.columns) == 4
    assert report.summary["total_occupied"] >= assigned_count
    assert report.summary["total_beds"] > 0


# ---------------------------------------------------------------------------
# 16. Student history tracks all changes
# ---------------------------------------------------------------------------

def test_student_history_tracks_all_changes(container, admin_session):
    """Create student -> assign bed -> verify history for student shows
    create event, and assignment audit trail includes assign event."""
    s = container.students.create(
        admin_session,
        StudentDTO(student_id="HIST-001", full_name="History Student",
                   college="Math", class_year=2027,
                   email="hist@example.edu", phone="555-9300",
                   housing_status="pending"))

    # Assign a bed to generate additional audit entries
    beds = container.housing.list_beds(admin_session, vacant_only=True)
    if beds:
        container.housing.assign_bed(
            admin_session, s.id, beds[0].id,
            effective_date=date(2026, 8, 15), reason="history test")

    # Student history shows the create event
    history = container.students.history(admin_session, s.id)
    actions = [h.action for h in history]
    assert "create" in actions

    # The overall audit chain should verify cleanly
    from backend.audit import verify_chain
    result = verify_chain()
    assert result.ok


# ---------------------------------------------------------------------------
# 17. BOM same-approver rejection
# ---------------------------------------------------------------------------

def test_bom_same_approver_rejection(container, admin_session):
    """BOM final approval must fail if same user as first approver."""
    style = container.bom.create_style(
        admin_session, "STY-SAME", "Same Approver Style")
    versions = container.bom.list_versions(style.id)
    v = versions[0]

    # Add BOM item (required for submission)
    container.bom.add_bom_item(
        admin_session, v.id, component_code="FAB-X",
        description="Fabric", quantity=1.0, unit_cost_usd=5.0)

    container.bom.submit_for_approval(admin_session, v.id)
    container.bom.first_approve(admin_session, v.id)

    # Same user tries final approve -> should fail
    with pytest.raises(BizError) as exc_info:
        container.bom.final_approve(admin_session, v.id)
    assert exc_info.value.code == "SAME_APPROVER"


# ---------------------------------------------------------------------------
# 18. Compliance approval requires evidence
# ---------------------------------------------------------------------------

def test_compliance_approval_requires_evidence(container, admin_session):
    """Attempting to approve without evidence raises EVIDENCE_REQUIRED."""
    case_id = container.compliance.submit_employer(
        admin_session, name="No Evidence Corp",
        ein="66-6666666", contact_email="noev@example.com")

    with pytest.raises(BizError) as exc_info:
        container.compliance.decide(admin_session, case_id, "approve",
                                    notes="Looks good")
    assert exc_info.value.code == "EVIDENCE_REQUIRED"


# ---------------------------------------------------------------------------
# 19. Catalog semver bump consistency
# ---------------------------------------------------------------------------

def test_catalog_semver_bump_consistency(container, admin_session):
    """Verify that publish_with_semver correctly bumps the version and
    the semver in the catalog row match."""
    res = container.resources.create_resource(admin_session, "Semver Test")
    container.resources.add_version(admin_session, res.id, "Initial", "body")
    container.catalog.attach(admin_session, res.id, node_id=None,
                             type_code=None)
    container.catalog.submit_for_review(admin_session, res.id)
    container.catalog.review(admin_session, res.id, "approve", "ok")

    v1 = container.catalog.publish_with_semver(
        admin_session, res.id, level="minor")
    # Default initial semver is 0.1.0 -> minor bump -> 0.2.0
    assert v1 == "0.2.0"

    # Second publish with patch bump
    container.resources.add_version(admin_session, res.id, "Patch", "body2")
    container.catalog.submit_for_review(admin_session, res.id)
    container.catalog.review(admin_session, res.id, "approve", "ok2")
    v2 = container.catalog.publish_with_semver(
        admin_session, res.id, level="patch")
    assert v2 == "0.2.1"
