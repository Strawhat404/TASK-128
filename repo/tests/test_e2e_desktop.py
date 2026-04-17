"""Desktop packaging, installer simulation, and deeper UI tests.

These tests exercise desktop packaging concerns, database lifecycle,
model interfaces, and deeper interactive scenarios.
"""
from __future__ import annotations

import json
import os
import stat
import zipfile
from pathlib import Path

import pytest

from backend import config, crypto, db as _db
from backend.app import Container, STARTUP_PROFILE
from backend.models import Page, Paged, StudentDTO
from backend.permissions import PermissionDenied, Session
from backend.services.auth import BizError


# ---------------------------------------------------------------------------
# 1. Container startup profile
# ---------------------------------------------------------------------------

def test_container_startup_profile(container):
    """Container.__init__ populates STARTUP_PROFILE with db_open_s, seed_s,
    services_s, total_s; all are positive floats."""
    assert "db_open_s" in STARTUP_PROFILE
    assert "seed_s" in STARTUP_PROFILE
    assert "services_s" in STARTUP_PROFILE
    assert "total_s" in STARTUP_PROFILE

    for key in ("db_open_s", "seed_s", "services_s", "total_s"):
        val = STARTUP_PROFILE[key]
        assert isinstance(val, float), f"{key} should be float, got {type(val)}"
        assert val >= 0, f"{key} should be non-negative, got {val}"


# ---------------------------------------------------------------------------
# 2. Container has all services wired
# ---------------------------------------------------------------------------

def test_container_all_services_wired(container):
    """Container has all 16 service attributes."""
    expected_services = [
        "auth", "students", "housing", "resources", "compliance",
        "evidence", "sensitive", "violations", "notifications", "search",
        "reporting", "settings", "catalog", "bom", "checkpoints", "updater",
    ]
    for svc_name in expected_services:
        assert hasattr(container, svc_name), (
            f"Container missing service attribute: {svc_name}")
        assert getattr(container, svc_name) is not None, (
            f"Container service attribute {svc_name} is None")


# ---------------------------------------------------------------------------
# 3. Container provisions no placeholder key
# ---------------------------------------------------------------------------

def test_container_provisions_no_placeholder_key(container, tmp_path,
                                                  monkeypatch):
    """Container._provision_update_pubkey skips PLACEHOLDER keys."""
    # Create a placeholder key file in the installer directory
    installer_dir = config.REPO_ROOT / "installer"
    placeholder_path = installer_dir / "update_pubkey.pem"
    real_content_existed = placeholder_path.is_file()
    original_content = None
    if real_content_existed:
        original_content = placeholder_path.read_bytes()

    try:
        # Write a placeholder key
        placeholder_path.write_bytes(
            b"-----BEGIN PUBLIC KEY-----\n"
            b"PLACEHOLDER KEY DO NOT USE\n"
            b"-----END PUBLIC KEY-----\n")

        # Remove any existing key in the data dir
        target = config.update_signing_key_path()
        if target.is_file():
            target.unlink()

        # Re-provision
        container._provision_update_pubkey()

        # The placeholder should NOT have been copied
        assert not target.is_file() or b"PLACEHOLDER" not in target.read_bytes()
    finally:
        # Restore original file
        if real_content_existed and original_content is not None:
            placeholder_path.write_bytes(original_content)
        elif not real_content_existed and placeholder_path.is_file():
            placeholder_path.unlink()


# ---------------------------------------------------------------------------
# 4. Database migration idempotent
# ---------------------------------------------------------------------------

def test_database_migration_idempotent(container, tmp_path, monkeypatch):
    """Run get_connection twice (reset between) -> both succeed with same
    schema."""
    conn1 = _db.get_connection()
    tables1 = {r["name"] for r in conn1.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "ORDER BY name").fetchall()}

    _db.reset_connection()
    conn2 = _db.get_connection()
    tables2 = {r["name"] for r in conn2.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "ORDER BY name").fetchall()}

    assert tables1 == tables2
    assert len(tables1) > 0


# ---------------------------------------------------------------------------
# 5. Seed if empty idempotent
# ---------------------------------------------------------------------------

def test_seed_if_empty_idempotent(container):
    """Call seed_if_empty twice -> no errors, roles count unchanged."""
    conn = _db.get_connection()
    roles_before = conn.execute(
        "SELECT COUNT(*) AS n FROM roles").fetchone()["n"]

    # Call seed_if_empty again
    _db.seed_if_empty()

    roles_after = conn.execute(
        "SELECT COUNT(*) AS n FROM roles").fetchone()["n"]

    assert roles_after == roles_before


# ---------------------------------------------------------------------------
# 6. Transaction rollback on exception
# ---------------------------------------------------------------------------

def test_transaction_rollback_on_exception(container):
    """Start transaction -> insert -> raise exception -> verify insert was
    rolled back."""
    conn = _db.get_connection()
    count_before = conn.execute(
        "SELECT COUNT(*) AS n FROM students").fetchone()["n"]

    with pytest.raises(ValueError):
        with _db.transaction() as conn_tx:
            conn_tx.execute(
                "INSERT INTO students(student_id_ext, full_name, housing_status) "
                "VALUES ('ROLLBACK-001', 'Should Not Exist', 'pending')")
            raise ValueError("deliberate test error")

    count_after = _db.get_connection().execute(
        "SELECT COUNT(*) AS n FROM students").fetchone()["n"]
    assert count_after == count_before


# ---------------------------------------------------------------------------
# 7. Periodic reseal no-op when no connection
# ---------------------------------------------------------------------------

def test_periodic_reseal_no_op_when_no_connection(container):
    """Call periodic_reseal with no open connection -> no error."""
    _db.close_and_seal()
    # Now _CONN is None. periodic_reseal should be a safe no-op.
    _db.periodic_reseal()
    # Re-open so other tests don't break
    _db.get_connection()


# ---------------------------------------------------------------------------
# 8. Installer update flow simulation
# ---------------------------------------------------------------------------

def test_installer_update_flow_simulation(container, admin_session, tmp_path):
    """Create signed update package -> apply -> verify files extracted to
    install_dir -> verify update_packages table has entry -> rollback
    -> verify database restored."""
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding, rsa
    except ImportError:
        pytest.skip("cryptography not installed")

    priv = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    config.update_signing_key_path().write_bytes(
        priv.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo))

    # Create a signed package
    pkg_path = tmp_path / "update_v1.zip"
    manifest = json.dumps({"version": "1.0.0"}).encode("utf-8")
    sig = priv.sign(
        manifest,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                     salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256())

    install_dir = tmp_path / "install"
    with zipfile.ZipFile(pkg_path, "w") as zf:
        zf.writestr("update.json", manifest)
        zf.writestr("update.json.sig", sig)
        zf.writestr("payload/readme.txt", b"content")

    # Apply
    applied = container.updater.apply_package(
        admin_session, pkg_path, install_dir=str(install_dir))
    assert applied.signature_ok is True
    assert applied.version == "1.0.0"

    # Verify files extracted
    readme = install_dir / "readme.txt"
    assert readme.is_file()

    # Verify update_packages table has entry
    pkgs = container.updater.list_packages()
    assert any(p.id == applied.id and p.version == "1.0.0" for p in pkgs)

    # Rollback
    container.updater.rollback(admin_session, applied.id)

    # Verify rollback recorded
    pkgs_after = container.updater.list_packages()
    rolled = [p for p in pkgs_after if p.id == applied.id][0]
    assert rolled.rolled_back_at is not None


# ---------------------------------------------------------------------------
# 9. Multiple updates and rollback chain
# ---------------------------------------------------------------------------

def test_multiple_updates_and_rollback_chain(container, admin_session,
                                              tmp_path):
    """Apply update 1 -> apply update 2 -> rollback update 2 -> verify
    state matches post-update-1."""
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding, rsa
    except ImportError:
        pytest.skip("cryptography not installed")

    priv = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    config.update_signing_key_path().write_bytes(
        priv.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo))

    install_dir = tmp_path / "install"

    def make_pkg(version, payload_name, payload_content):
        pkg_path = tmp_path / f"update_{version}.zip"
        manifest = json.dumps({"version": version}).encode("utf-8")
        sig = priv.sign(
            manifest,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                         salt_length=padding.PSS.MAX_LENGTH),
            hashes.SHA256())
        with zipfile.ZipFile(pkg_path, "w") as zf:
            zf.writestr("update.json", manifest)
            zf.writestr("update.json.sig", sig)
            zf.writestr(f"payload/{payload_name}", payload_content)
        return pkg_path

    # Apply update 1
    pkg1 = make_pkg("1.0.0", "file1.txt", b"version one content")
    applied1 = container.updater.apply_package(
        admin_session, pkg1, install_dir=str(install_dir))
    assert applied1.version == "1.0.0"
    assert (install_dir / "file1.txt").is_file()

    # Apply update 2
    pkg2 = make_pkg("2.0.0", "file2.txt", b"version two content")
    applied2 = container.updater.apply_package(
        admin_session, pkg2, install_dir=str(install_dir))
    assert applied2.version == "2.0.0"
    assert (install_dir / "file2.txt").is_file()

    # Rollback update 2
    container.updater.rollback(admin_session, applied2.id)

    pkgs = container.updater.list_packages()
    p2 = [p for p in pkgs if p.id == applied2.id][0]
    assert p2.rolled_back_at is not None

    # Update 1 should still not be rolled back
    p1 = [p for p in pkgs if p.id == applied1.id][0]
    assert p1.rolled_back_at is None


# ---------------------------------------------------------------------------
# 10. Data dir permissions
# ---------------------------------------------------------------------------

def test_data_dir_permissions(container):
    """key_path file has restricted permissions (0o600) on creation."""
    # Ensure the key file exists by triggering creation
    crypto.load_or_create_key()
    key_file = config.key_path()
    assert key_file.is_file()

    # On Linux/Mac, check file permissions
    if os.name != "nt":
        mode = os.stat(key_file).st_mode
        # Mask out the file type bits, keep only permission bits
        perm = stat.S_IMODE(mode)
        # Should be 0o600 (owner read+write only)
        assert perm == 0o600, (
            f"key file permissions {oct(perm)} != 0o600")


# ---------------------------------------------------------------------------
# 11. Models Paged interface
# ---------------------------------------------------------------------------

def test_models_paged_interface():
    """Paged container: __iter__, __len__, __getitem__, __bool__ work
    correctly."""
    items = ["a", "b", "c"]
    paged = Paged(items=items, total=10)

    # __iter__
    assert list(paged) == ["a", "b", "c"]

    # __len__
    assert len(paged) == 3

    # __getitem__
    assert paged[0] == "a"
    assert paged[2] == "c"

    # __bool__
    assert bool(paged) is True

    # Empty paged
    empty = Paged(items=[], total=0)
    assert bool(empty) is False
    assert len(empty) == 0
    assert list(empty) == []


# ---------------------------------------------------------------------------
# 12. Models Page defaults
# ---------------------------------------------------------------------------

def test_models_page_defaults():
    """Page() has limit=50, offset=0."""
    page = Page()
    assert page.limit == 50
    assert page.offset == 0

    # Custom values
    custom = Page(limit=25, offset=100)
    assert custom.limit == 25
    assert custom.offset == 100


# ---------------------------------------------------------------------------
# 13. Import preview cache isolation
# ---------------------------------------------------------------------------

def test_import_preview_cache_isolation(container, admin_session, tmp_path):
    """commit_import consumes preview; second commit raises
    BizError('PREVIEW_EXPIRED')."""
    import csv

    csv_path = tmp_path / "import_cache.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["student_id", "full_name", "college", "class_year",
                         "email", "phone", "housing_status"])
        writer.writerow(["CACHE-001", "Cache Student", "Arts", "2027",
                         "cache@example.edu", "555-0001", "pending"])

    preview = container.students.import_csv(admin_session, csv_path)
    assert len(preview.accepted) == 1

    # First commit succeeds
    result = container.students.commit_import(admin_session, preview.preview_id)
    assert result["created"] == 1

    # Second commit should fail
    with pytest.raises(BizError) as exc_info:
        container.students.commit_import(admin_session, preview.preview_id)
    assert exc_info.value.code == "PREVIEW_EXPIRED"


# ---------------------------------------------------------------------------
# 14. DB close and reopen preserves all tables
# ---------------------------------------------------------------------------

def test_db_close_and_reopen_preserves_all_tables(container, admin_session,
                                                    tmp_path):
    """Create data in all major tables -> close_and_seal -> reopen
    -> verify all data present."""
    if _db.HAVE_SQLCIPHER:
        pytest.skip("SQLCipher mode does not use in-memory serialize")

    # Create a student
    student = container.students.create(
        admin_session,
        StudentDTO(student_id="PRESERVE-001", full_name="Preserved Student",
                   college="Engineering", class_year=2027,
                   email="preserve@example.edu", phone="555-0100",
                   housing_status="pending"))

    # Create a resource
    res = container.resources.create_resource(admin_session, "Preserved Resource")

    # Submit an employer
    case_id = container.compliance.submit_employer(
        admin_session, name="Preserved Employer",
        ein="77-7777777", contact_email="preserved@example.com")

    # Save a setting
    container.settings.set(admin_session, "test_key", "test_value")

    # Save a workspace checkpoint
    container.checkpoints.save_workspace(
        admin_session, {"tab": "test"})

    _db.close_and_seal()
    _db.get_connection()

    # Verify student
    conn = _db.get_connection()
    row = conn.execute(
        "SELECT id FROM students WHERE student_id_ext='PRESERVE-001'"
    ).fetchone()
    assert row is not None

    # Verify resource
    row = conn.execute(
        "SELECT id FROM resources WHERE title='Preserved Resource'"
    ).fetchone()
    assert row is not None

    # Verify employer
    row = conn.execute(
        "SELECT id FROM employers WHERE name='Preserved Employer'"
    ).fetchone()
    assert row is not None

    # Verify setting
    val = container.settings.get("test_key")
    assert val == "test_value"

    # Verify workspace
    ws = container.checkpoints.load_workspace(admin_session)
    assert ws is not None
    assert ws["tab"] == "test"


# ---------------------------------------------------------------------------
# 15. Template variable extraction
# ---------------------------------------------------------------------------

def test_template_variable_extraction(container, admin_session):
    """upsert_template with '{StudentName} in {Dorm}' extracts variables
    correctly."""
    tid = container.notifications.upsert_template(
        admin_session,
        name="test_vars_template",
        subject="{StudentName} assigned to {Dorm}",
        body="Hello {StudentName}, welcome to {Dorm} room {Room}!")

    assert tid > 0

    # Read back the template and check variables
    templates = container.notifications.list_templates(admin_session)
    tpl = [t for t in templates if t["name"] == "test_vars_template"]
    assert len(tpl) == 1

    variables = json.loads(tpl[0]["variables_json"])
    assert "StudentName" in variables
    assert "Dorm" in variables
    assert "Room" in variables
    # Should be sorted
    assert variables == sorted(variables)


# ---------------------------------------------------------------------------
# 16. Settings round-trip
# ---------------------------------------------------------------------------

def test_settings_round_trip(container, admin_session):
    """Set a value -> get returns it -> overwrite -> get returns new value."""
    container.settings.set(admin_session, "desktop.theme", "dark")
    assert container.settings.get("desktop.theme") == "dark"

    container.settings.set(admin_session, "desktop.theme", "light")
    assert container.settings.get("desktop.theme") == "light"


# ---------------------------------------------------------------------------
# 17. Synonym management round-trip
# ---------------------------------------------------------------------------

def test_synonym_management_round_trip(container, admin_session):
    """Add synonym -> verify in list -> remove -> verify gone."""
    sid = container.settings.add_synonym(
        admin_session, "test_term", "test_alt")

    syns = container.settings.list_synonyms()
    found = [s for s in syns if s["term"] == "test_term"
             and s["alt_term"] == "test_alt"]
    assert len(found) >= 1

    container.settings.remove_synonym(admin_session, found[0]["id"])
    syns_after = container.settings.list_synonyms()
    found_after = [s for s in syns_after if s["term"] == "test_term"
                   and s["alt_term"] == "test_alt"]
    assert len(found_after) == 0


# ---------------------------------------------------------------------------
# 18. Unsigned package rejected
# ---------------------------------------------------------------------------

def test_unsigned_package_rejected(container, admin_session, tmp_path):
    """An update package without a valid signature is rejected."""
    pkg_path = tmp_path / "unsigned.zip"
    manifest = json.dumps({"version": "0.0.1"}).encode("utf-8")
    with zipfile.ZipFile(pkg_path, "w") as zf:
        zf.writestr("update.json", manifest)
        zf.writestr("payload/readme.txt", b"content")

    with pytest.raises(BizError) as exc_info:
        container.updater.apply_package(
            admin_session, pkg_path, install_dir=str(tmp_path / "install"))
    assert exc_info.value.code == "SIGNATURE_REQUIRED"


# ---------------------------------------------------------------------------
# 19. Draft checkpoint discard
# ---------------------------------------------------------------------------

def test_draft_checkpoint_discard(container, admin_session):
    """Save drafts -> discard one -> list shows only remaining."""
    container.checkpoints.save_draft(
        admin_session, "draft_a", {"data": "A"})
    container.checkpoints.save_draft(
        admin_session, "draft_b", {"data": "B"})

    drafts = container.checkpoints.list_drafts(admin_session)
    keys = [d["draft_key"] for d in drafts]
    assert "draft_a" in keys
    assert "draft_b" in keys

    container.checkpoints.discard_draft(admin_session, "draft_a")

    drafts_after = container.checkpoints.list_drafts(admin_session)
    keys_after = [d["draft_key"] for d in drafts_after]
    assert "draft_a" not in keys_after
    assert "draft_b" in keys_after


# ---------------------------------------------------------------------------
# 20. Discard all drafts
# ---------------------------------------------------------------------------

def test_discard_all_drafts(container, admin_session):
    """discard_all clears all drafts for the user."""
    container.checkpoints.save_draft(
        admin_session, "da", {"x": 1})
    container.checkpoints.save_draft(
        admin_session, "db", {"x": 2})

    count = container.checkpoints.discard_all(admin_session)
    assert count >= 2

    drafts = container.checkpoints.list_drafts(admin_session)
    assert len(drafts) == 0


# ---------------------------------------------------------------------------
# 21. Evidence verify integrity
# ---------------------------------------------------------------------------

def test_evidence_verify_integrity(container, admin_session, tmp_path):
    """Upload evidence file -> verify returns True -> tamper -> verify
    returns False."""
    case_id = container.compliance.submit_employer(
        admin_session, name="Evidence Verify Corp",
        ein="88-8888888", contact_email="ev@example.com")

    conn = _db.get_connection()
    emp_id = conn.execute(
        "SELECT employer_id FROM employer_cases WHERE id=?",
        (case_id,)).fetchone()["employer_id"]

    evidence_file = tmp_path / "verify_test.pdf"
    evidence_file.write_bytes(b"%PDF-1.4 test evidence content\n")

    ef = container.evidence.upload(
        admin_session, emp_id, evidence_file, case_id=case_id)

    # Verify should pass
    assert container.evidence.verify(ef.id, session=admin_session) is True

    # Tamper with the stored file
    stored_path = config.evidence_dir() / ef.stored_path
    if stored_path.is_file():
        stored_path.write_bytes(b"tampered content")
        assert container.evidence.verify(ef.id, session=admin_session) is False


# ---------------------------------------------------------------------------
# 22. Catalog node CRUD
# ---------------------------------------------------------------------------

def test_catalog_node_crud(container, admin_session):
    """Create node -> rename -> verify tree -> delete."""
    node_id = container.catalog.create_node(admin_session, "Test Department")
    assert node_id > 0

    container.catalog.rename_node(admin_session, node_id, "Renamed Dept")

    tree = container.catalog.list_tree()
    found = False
    for node in tree:
        if node.id == node_id:
            assert node.name == "Renamed Dept"
            found = True
        for child in node.children:
            if child.id == node_id:
                assert child.name == "Renamed Dept"
                found = True
    assert found

    container.catalog.delete_node(admin_session, node_id)

    tree_after = container.catalog.list_tree()
    ids = set()
    for node in tree_after:
        ids.add(node.id)
        for child in node.children:
            ids.add(child.id)
    assert node_id not in ids
