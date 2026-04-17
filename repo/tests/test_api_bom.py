"""Service-layer API tests for BomService."""
from __future__ import annotations

import pytest
from backend.services.auth import BizError
from backend.permissions import PermissionDenied, Session
from backend import crypto, db as _db


def _make_second_admin(container):
    """Create a second system_admin user and return their session."""
    h, salt = crypto.hash_password("SecondAdmin1!")
    conn = _db.get_connection()
    conn.execute(
        "INSERT INTO users(username, full_name, password_hash, password_salt) "
        "VALUES ('admin2', 'Admin2', ?, ?)", (h, salt))
    uid = conn.execute(
        "SELECT id FROM users WHERE username='admin2'").fetchone()["id"]
    rid = conn.execute(
        "SELECT id FROM roles WHERE code='system_admin'").fetchone()["id"]
    conn.execute(
        "INSERT INTO user_roles(user_id, role_id) VALUES (?, ?)", (uid, rid))
    return container.auth.login("admin2", "SecondAdmin1!")


def _create_released_style(container, admin_session):
    """Create a style, populate BOM, and release through full approval."""
    bom = container.bom
    style = bom.create_style(admin_session, "REL-001", "Released Style")
    versions = bom.list_versions(style.id)
    vid = versions[0].id
    bom.add_bom_item(admin_session, vid,
                     component_code="COMP-A", quantity=1, unit_cost_usd=10.00)
    bom.add_routing_step(admin_session, vid,
                         operation="Cut", setup_minutes=5,
                         run_minutes=10, rate_per_hour_usd=60.00)
    bom.submit_for_approval(admin_session, vid)
    bom.first_approve(admin_session, vid)
    second_admin = _make_second_admin(container)
    bom.final_approve(second_admin, vid)
    return style, vid


class TestBomService:

    def test_create_style(self, container, admin_session):
        style = container.bom.create_style(admin_session, "STY-001", "Test Style")
        assert style.id > 0
        assert style.name == "Test Style"

    def test_create_style_creates_draft_version(self, container, admin_session):
        style = container.bom.create_style(admin_session, "STY-002", "Draft Style")
        versions = container.bom.list_versions(style.id)
        assert len(versions) >= 1
        assert versions[0].state == "draft"

    def test_get_style_not_found(self, container, admin_session):
        with pytest.raises(BizError) as ei:
            container.bom.get_style(999999)
        assert ei.value.code == "STYLE_NOT_FOUND"

    def test_list_styles(self, container, admin_session):
        container.bom.create_style(admin_session, "STY-L1", "Style L1")
        container.bom.create_style(admin_session, "STY-L2", "Style L2")
        styles = container.bom.list_styles()
        assert len(styles) >= 2

    def test_add_bom_item(self, container, admin_session):
        style = container.bom.create_style(admin_session, "STY-BOM", "BOM Style")
        vid = container.bom.list_versions(style.id)[0].id
        container.bom.add_bom_item(admin_session, vid,
                                   component_code="COMP-1", quantity=5,
                                   unit_cost_usd=12.50)
        items = container.bom.list_bom(vid)
        assert len(items) >= 1
        assert any(i.component_code == "COMP-1" for i in items)

    def test_add_routing_step(self, container, admin_session):
        style = container.bom.create_style(admin_session, "STY-RTG", "Routing Style")
        vid = container.bom.list_versions(style.id)[0].id
        container.bom.add_routing_step(admin_session, vid,
                                       operation="Sewing",
                                       setup_minutes=10, run_minutes=30,
                                       rate_per_hour_usd=45.00)
        steps = container.bom.list_routing(vid)
        assert len(steps) >= 1
        assert any(s.operation == "Sewing" for s in steps)

    def test_cost_calculation(self, container, admin_session):
        style = container.bom.create_style(admin_session, "STY-COST", "Cost Style")
        vid = container.bom.list_versions(style.id)[0].id
        # Material: 2 x $10 = $20
        container.bom.add_bom_item(admin_session, vid,
                                   component_code="MAT-1", quantity=2,
                                   unit_cost_usd=10.00)
        # Labor: (5 + 10) = 15 min = 0.25 hr * $60/hr = $15
        container.bom.add_routing_step(admin_session, vid,
                                       operation="Assembly",
                                       setup_minutes=5, run_minutes=10,
                                       rate_per_hour_usd=60.00)
        cost = container.bom.compute_cost(vid)
        assert cost == pytest.approx(35.00)

    def test_submit_for_approval(self, container, admin_session):
        style = container.bom.create_style(admin_session, "STY-SUB", "Submit Style")
        vid = container.bom.list_versions(style.id)[0].id
        container.bom.add_bom_item(admin_session, vid,
                                   component_code="COMP-S", quantity=1,
                                   unit_cost_usd=5.00)
        container.bom.submit_for_approval(admin_session, vid)
        ver = container.bom.get_version(vid)
        assert ver.state == "submitted"

    def test_submit_empty_bom_fails(self, container, admin_session):
        style = container.bom.create_style(admin_session, "STY-EMPTY", "Empty Style")
        vid = container.bom.list_versions(style.id)[0].id
        with pytest.raises(BizError) as ei:
            container.bom.submit_for_approval(admin_session, vid)
        assert ei.value.code == "EMPTY_BOM"

    def test_first_approve(self, container, admin_session):
        style = container.bom.create_style(admin_session, "STY-FA", "FA Style")
        vid = container.bom.list_versions(style.id)[0].id
        container.bom.add_bom_item(admin_session, vid,
                                   component_code="COMP-FA", quantity=1,
                                   unit_cost_usd=5.00)
        container.bom.submit_for_approval(admin_session, vid)
        container.bom.first_approve(admin_session, vid)
        assert container.bom.get_version(vid).state == "first_approved"

    def test_final_approve_different_user(self, container, admin_session):
        style = container.bom.create_style(admin_session, "STY-FIN", "Final Style")
        vid = container.bom.list_versions(style.id)[0].id
        container.bom.add_bom_item(admin_session, vid,
                                   component_code="COMP-FIN", quantity=1,
                                   unit_cost_usd=5.00)
        container.bom.submit_for_approval(admin_session, vid)
        container.bom.first_approve(admin_session, vid)
        second = _make_second_admin(container)
        container.bom.final_approve(second, vid)
        assert container.bom.get_version(vid).state == "released"

    def test_final_approve_same_user_fails(self, container, admin_session):
        style = container.bom.create_style(admin_session, "STY-SAME", "Same Style")
        vid = container.bom.list_versions(style.id)[0].id
        container.bom.add_bom_item(admin_session, vid,
                                   component_code="COMP-SAME", quantity=1,
                                   unit_cost_usd=5.00)
        container.bom.submit_for_approval(admin_session, vid)
        container.bom.first_approve(admin_session, vid)
        with pytest.raises(BizError) as ei:
            container.bom.final_approve(admin_session, vid)
        assert ei.value.code == "SAME_APPROVER"

    def test_reject(self, container, admin_session):
        style = container.bom.create_style(admin_session, "STY-REJ", "Reject Style")
        vid = container.bom.list_versions(style.id)[0].id
        container.bom.add_bom_item(admin_session, vid,
                                   component_code="COMP-REJ", quantity=1,
                                   unit_cost_usd=5.00)
        container.bom.submit_for_approval(admin_session, vid)
        container.bom.reject(admin_session, vid, reason="Quality issues")
        assert container.bom.get_version(vid).state == "rejected"

    def test_edit_released_version_fails(self, container, admin_session):
        style, vid = _create_released_style(container, admin_session)
        with pytest.raises(BizError) as ei:
            container.bom.add_bom_item(admin_session, vid,
                                       component_code="NEW", quantity=1,
                                       unit_cost_usd=1.00)
        assert ei.value.code == "LOCKED"

    def test_open_change_request(self, container, admin_session):
        style, vid = _create_released_style(container, admin_session)
        cr_id = container.bom.open_change_request(
            admin_session, style.id, vid, "Improvement needed")
        assert cr_id > 0

    def test_change_request_copies_bom(self, container, admin_session):
        style, vid = _create_released_style(container, admin_session)
        original_items = container.bom.list_bom(vid)
        container.bom.open_change_request(
            admin_session, style.id, vid, "Copy test")
        new_versions = container.bom.list_versions(style.id)
        new_draft = [v for v in new_versions if v.state == "draft"]
        assert len(new_draft) >= 1
        new_items = container.bom.list_bom(new_draft[0].id)
        assert len(new_items) == len(original_items)

    def test_change_request_against_non_released_fails(self, container,
                                                       admin_session):
        style = container.bom.create_style(admin_session, "STY-CRB", "CR Bad")
        vid = container.bom.list_versions(style.id)[0].id
        with pytest.raises(BizError) as ei:
            container.bom.open_change_request(
                admin_session, style.id, vid, "Should fail")
        assert ei.value.code == "BAD_BASE"

    def test_list_change_requests(self, container, admin_session):
        style, vid = _create_released_style(container, admin_session)
        container.bom.open_change_request(
            admin_session, style.id, vid, "CR list test")
        crs = container.bom.list_change_requests(style_id=style.id)
        assert len(crs) >= 1
