"""Student service API tests."""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

from backend.models import StudentDTO, ImportPreview
from backend.services.auth import BizError
from backend.permissions import PermissionDenied, Session


# ---------- helpers -----------------------------------------------------------

def _make_dto(**overrides) -> StudentDTO:
    defaults = dict(
        student_id="STU-001",
        full_name="Jane Doe",
        college="Engineering",
        class_year=2027,
        email="jane@example.edu",
        phone="555-0100",
        housing_status="pending",
    )
    defaults.update(overrides)
    return StudentDTO(**defaults)


def _write_csv(path: Path, rows: list[dict], columns: list[str] | None = None) -> Path:
    if columns is None:
        columns = ["student_id", "full_name", "college", "class_year",
                    "email", "phone", "housing_status"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


# ---------- create ------------------------------------------------------------

def test_create_student(container, admin_session):
    s = container.students.create(admin_session, _make_dto())
    assert s.id > 0
    assert s.student_id == "STU-001"
    assert s.full_name == "Jane Doe"
    assert s.college == "Engineering"
    assert s.housing_status == "pending"


def test_create_duplicate_student_id(container, admin_session):
    container.students.create(admin_session, _make_dto())
    with pytest.raises(BizError) as exc_info:
        container.students.create(admin_session, _make_dto(full_name="Other"))
    assert exc_info.value.code == "STUDENT_DUPLICATE_ID"


def test_create_missing_fields(container, admin_session):
    with pytest.raises(BizError) as exc_info:
        container.students.create(
            admin_session,
            StudentDTO(student_id="", full_name="No ID", housing_status="pending"))
    assert exc_info.value.code == "MISSING_FIELD"


def test_create_bad_status(container, admin_session):
    with pytest.raises(BizError) as exc_info:
        container.students.create(admin_session, _make_dto(housing_status="invalid"))
    assert exc_info.value.code == "BAD_STATUS"


# ---------- get ---------------------------------------------------------------

def test_get_student(container, admin_session):
    created = container.students.create(admin_session, _make_dto())
    fetched = container.students.get(admin_session, created.id)
    assert fetched.id == created.id
    assert fetched.full_name == "Jane Doe"
    assert fetched.student_id == "STU-001"


def test_get_student_not_found(container, admin_session):
    with pytest.raises(BizError) as exc_info:
        container.students.get(admin_session, 999999)
    assert exc_info.value.code == "STUDENT_NOT_FOUND"


# ---------- search ------------------------------------------------------------

def test_search_by_text(container, admin_session):
    container.students.create(admin_session, _make_dto(student_id="S-1", full_name="Alice Smith"))
    container.students.create(admin_session, _make_dto(student_id="S-2", full_name="Bob Jones"))
    results = container.students.search(admin_session, text="Alice")
    assert any(r.full_name == "Alice Smith" for r in results.items)
    assert not any(r.full_name == "Bob Jones" for r in results.items)


def test_search_by_college(container, admin_session):
    container.students.create(admin_session, _make_dto(student_id="S-1", college="Arts"))
    container.students.create(admin_session, _make_dto(student_id="S-2", college="Science"))
    results = container.students.search(admin_session, college="Arts")
    assert all(r.college == "Arts" for r in results.items)


def test_search_by_housing_status(container, admin_session):
    container.students.create(admin_session, _make_dto(student_id="S-1", housing_status="on_campus"))
    container.students.create(admin_session, _make_dto(student_id="S-2", housing_status="off_campus"))
    results = container.students.search(admin_session, housing_status="on_campus")
    assert all(r.housing_status == "on_campus" for r in results.items)


def test_search_pagination(container, admin_session):
    for i in range(5):
        container.students.create(
            admin_session,
            _make_dto(student_id=f"PAG-{i}", full_name=f"Student {i}"))
    page1 = container.students.search(admin_session, limit=2, offset=0)
    page2 = container.students.search(admin_session, limit=2, offset=2)
    assert len(page1.items) == 2
    assert len(page2.items) == 2
    assert page1.total == 5
    # Pages should not overlap
    ids1 = {r.id for r in page1.items}
    ids2 = {r.id for r in page2.items}
    assert ids1.isdisjoint(ids2)


# ---------- update ------------------------------------------------------------

def test_update_student(container, admin_session):
    created = container.students.create(admin_session, _make_dto())
    updated = container.students.update(
        admin_session, created.id,
        _make_dto(full_name="Jane Updated", college="Science"))
    assert updated.full_name == "Jane Updated"
    assert updated.college == "Science"


# ---------- PII masking -------------------------------------------------------

def test_student_pii_masked_by_default(container, admin_session):
    container.students.create(admin_session, _make_dto(
        email="secret@example.edu", phone="555-1234"))
    # Without unlock, PII is masked
    s = container.students.get(admin_session, 1)
    # Masked values should contain *** or similar masking indicators
    assert "***" in (s.email or "")


def test_student_pii_revealed_after_unlock(container, admin_session):
    container.students.create(admin_session, _make_dto(
        email="secret@example.edu", phone="555-1234"))
    container.auth.unlock_masked_fields(admin_session, "TestPassw0rd!")
    s = container.students.get(admin_session, 1)
    # After unlock, if the session has pii.read permission, values are revealed
    if admin_session.has("student.pii.read"):
        assert s.email == "secret@example.edu"
        assert s.phone == "555-1234"
    else:
        # If permission is absent, still masked even after unlock
        assert "***" in (s.email or "")


# ---------- history -----------------------------------------------------------

def test_history_returns_entries(container, admin_session):
    created = container.students.create(admin_session, _make_dto())
    container.students.update(
        admin_session, created.id,
        _make_dto(full_name="Jane Updated"))
    hist = container.students.history(admin_session, created.id)
    assert len(hist) >= 2  # at least create + update
    actions = [e.action for e in hist]
    assert "create" in actions
    assert "update" in actions


# ---------- CSV import/export -------------------------------------------------

def test_csv_import_preview(container, admin_session, tmp_path):
    csv_file = _write_csv(tmp_path / "import.csv", [
        {"student_id": "IMP-1", "full_name": "Imported One",
         "college": "Eng", "class_year": "2027",
         "email": "imp1@example.edu", "phone": "555-0001",
         "housing_status": "pending"},
    ])
    preview = container.students.import_file(admin_session, csv_file)
    assert isinstance(preview, ImportPreview)
    assert len(preview.accepted) == 1
    assert len(preview.rejected) == 0


def test_csv_import_commit(container, admin_session, tmp_path):
    csv_file = _write_csv(tmp_path / "import.csv", [
        {"student_id": "IMP-1", "full_name": "Imported One",
         "college": "Eng", "class_year": "2027",
         "email": "imp1@example.edu", "phone": "555-0001",
         "housing_status": "pending"},
    ])
    preview = container.students.import_file(admin_session, csv_file)
    result = container.students.commit_import(admin_session, preview.preview_id)
    assert result["created"] == 1
    # The record should now be findable
    found = container.students.search(admin_session, text="Imported One")
    assert len(found.items) == 1


def test_csv_import_bad_header(container, admin_session, tmp_path):
    # CSV with missing required columns
    bad_csv = tmp_path / "bad.csv"
    with open(bad_csv, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["student_id", "full_name"])  # missing college, etc.
        writer.writerow(["X-1", "Bad Row"])
    with pytest.raises(BizError) as exc_info:
        container.students.import_file(admin_session, bad_csv)
    assert exc_info.value.code == "BAD_HEADER"


def test_csv_import_duplicate_strategy_skip(container, admin_session, tmp_path):
    # Create an existing student
    container.students.create(admin_session, _make_dto(student_id="DUP-1"))
    csv_file = _write_csv(tmp_path / "dup.csv", [
        {"student_id": "DUP-1", "full_name": "Duplicate",
         "college": "Eng", "class_year": "2027",
         "email": "dup@example.edu", "phone": "555-0002",
         "housing_status": "pending"},
        {"student_id": "NEW-1", "full_name": "Brand New",
         "college": "Arts", "class_year": "2028",
         "email": "new@example.edu", "phone": "555-0003",
         "housing_status": "pending"},
    ])
    preview = container.students.import_file(
        admin_session, csv_file, duplicate_strategy="skip")
    result = container.students.commit_import(admin_session, preview.preview_id)
    assert result["skipped"] == 1
    assert result["created"] == 1


def test_csv_export_roundtrip(container, admin_session, tmp_path):
    container.students.create(admin_session, _make_dto(
        student_id="EXP-1", full_name="Export Test"))
    export_path = tmp_path / "export.csv"
    count = container.students.export_file(admin_session, export_path)
    assert count >= 1
    assert export_path.exists()
    # Re-import the exported file
    preview = container.students.import_file(
        admin_session, export_path, duplicate_strategy="skip")
    # The existing record should be skipped, confirming data round-tripped
    assert len(preview.accepted) >= 1


def test_import_bad_format(container, admin_session, tmp_path):
    bad_file = tmp_path / "data.json"
    bad_file.write_text('{"not": "csv"}')
    with pytest.raises(BizError) as exc_info:
        container.students.import_file(admin_session, bad_file)
    assert exc_info.value.code == "BAD_FORMAT"
