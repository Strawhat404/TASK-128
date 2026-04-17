"""Housing service API tests."""
from __future__ import annotations

from datetime import date

import pytest

from backend.models import StudentDTO, Bed, BedAssignment
from backend.services.auth import BizError
from backend.permissions import PermissionDenied, Session


# ---------- helpers -----------------------------------------------------------

def _create_student(container, session, student_id="HSG-001", full_name="Housing Student"):
    return container.students.create(
        session,
        StudentDTO(
            student_id=student_id,
            full_name=full_name,
            college="Engineering",
            class_year=2027,
            email=f"{student_id.lower()}@example.edu",
            phone="555-0200",
            housing_status="pending",
        ))


def _get_vacant_bed(container, session):
    beds = container.housing.list_beds(session, vacant_only=True)
    assert len(beds) > 0, "Seed data should provide at least one vacant bed"
    return beds[0]


# ---------- list_buildings ----------------------------------------------------

def test_list_buildings(container, admin_session):
    buildings = container.housing.list_buildings(admin_session)
    assert isinstance(buildings, list)
    assert len(buildings) > 0
    b = buildings[0]
    assert "id" in b
    assert "name" in b
    assert "address" in b


# ---------- list_beds ---------------------------------------------------------

def test_list_beds(container, admin_session):
    beds = container.housing.list_beds(admin_session)
    assert isinstance(beds, list)
    assert len(beds) > 0
    assert isinstance(beds[0], Bed)


def test_list_beds_vacant_only(container, admin_session):
    beds = container.housing.list_beds(admin_session, vacant_only=True)
    assert all(not b.occupied for b in beds)


# ---------- assign_bed --------------------------------------------------------

def test_assign_bed(container, admin_session):
    student = _create_student(container, admin_session)
    bed = _get_vacant_bed(container, admin_session)
    assignment = container.housing.assign_bed(
        admin_session, student.id, bed.id, date.today(), reason="initial")
    assert isinstance(assignment, BedAssignment)
    assert assignment.student_id == student.id
    assert assignment.bed_id == bed.id
    # Student status should change to on_campus
    updated = container.students.get(admin_session, student.id)
    assert updated.housing_status == "on_campus"


def test_assign_occupied_bed_fails(container, admin_session):
    s1 = _create_student(container, admin_session, student_id="OCC-1", full_name="First")
    s2 = _create_student(container, admin_session, student_id="OCC-2", full_name="Second")
    bed = _get_vacant_bed(container, admin_session)
    container.housing.assign_bed(admin_session, s1.id, bed.id, date.today())
    with pytest.raises(BizError) as exc_info:
        container.housing.assign_bed(admin_session, s2.id, bed.id, date.today())
    assert exc_info.value.code == "BED_OCCUPIED"


# ---------- vacate_bed --------------------------------------------------------

def test_vacate_bed(container, admin_session):
    student = _create_student(container, admin_session)
    bed = _get_vacant_bed(container, admin_session)
    assignment = container.housing.assign_bed(
        admin_session, student.id, bed.id, date.today())
    vacated = container.housing.vacate_bed(
        admin_session, assignment.id, date.today(), reason="moving out")
    assert isinstance(vacated, BedAssignment)
    assert vacated.end_date is not None
    # Student status should revert to pending
    updated = container.students.get(admin_session, student.id)
    assert updated.housing_status == "pending"


def test_vacate_already_vacated(container, admin_session):
    student = _create_student(container, admin_session)
    bed = _get_vacant_bed(container, admin_session)
    assignment = container.housing.assign_bed(
        admin_session, student.id, bed.id, date.today())
    container.housing.vacate_bed(admin_session, assignment.id, date.today())
    with pytest.raises(BizError) as exc_info:
        container.housing.vacate_bed(admin_session, assignment.id, date.today())
    assert exc_info.value.code == "ALREADY_VACATED"


# ---------- transfer ----------------------------------------------------------

def test_transfer(container, admin_session):
    student = _create_student(container, admin_session)
    beds = container.housing.list_beds(admin_session, vacant_only=True)
    assert len(beds) >= 2, "Need at least 2 vacant beds for transfer test"
    bed_a, bed_b = beds[0], beds[1]
    container.housing.assign_bed(admin_session, student.id, bed_a.id, date.today())
    new_assignment = container.housing.transfer(
        admin_session, student.id, bed_b.id, date.today(), reason="room change")
    assert isinstance(new_assignment, BedAssignment)
    assert new_assignment.bed_id == bed_b.id
    # Student should still be on_campus
    updated = container.students.get(admin_session, student.id)
    assert updated.housing_status == "on_campus"


# ---------- assignment_history ------------------------------------------------

def test_assignment_history_by_student(container, admin_session):
    student = _create_student(container, admin_session)
    bed = _get_vacant_bed(container, admin_session)
    container.housing.assign_bed(admin_session, student.id, bed.id, date.today())
    history = container.housing.assignment_history(
        admin_session, student_id=student.id)
    assert isinstance(history, list)
    assert len(history) >= 1
    assert all(h.student_id == student.id for h in history)


def test_assignment_history_by_bed(container, admin_session):
    student = _create_student(container, admin_session)
    bed = _get_vacant_bed(container, admin_session)
    container.housing.assign_bed(admin_session, student.id, bed.id, date.today())
    history = container.housing.assignment_history(
        admin_session, bed_id=bed.id)
    assert isinstance(history, list)
    assert len(history) >= 1
    assert all(h.bed_id == bed.id for h in history)


# ---------- permission checks -------------------------------------------------

def test_housing_read_denied_without_permission(container):
    # A bare session with no roles/permissions should be denied
    bare = Session(user_id=0, username="nobody", full_name="Nobody",
                   roles=set(), permissions=set())
    with pytest.raises(PermissionDenied):
        container.housing.list_buildings(bare)


def test_housing_write_denied_without_permission(container, admin_session):
    # Create a student first with admin, then try to assign with bare session
    student = _create_student(container, admin_session)
    bed = _get_vacant_bed(container, admin_session)
    bare = Session(user_id=0, username="nobody", full_name="Nobody",
                   roles=set(), permissions=set())
    with pytest.raises(PermissionDenied):
        container.housing.assign_bed(bare, student.id, bed.id, date.today())
