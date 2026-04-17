"""Service-layer API tests for ResourceService."""
from __future__ import annotations

import pytest
from backend.services.auth import BizError
from backend.permissions import PermissionDenied


class TestResourceService:

    def test_create_resource(self, container, admin_session):
        res = container.resources.create_resource(admin_session, "Test Resource")
        assert res.id > 0
        assert res.title == "Test Resource"

    def test_create_resource_empty_title(self, container, admin_session):
        with pytest.raises(BizError) as ei:
            container.resources.create_resource(admin_session, "")
        assert ei.value.code == "BAD_TITLE"

    def test_create_resource_whitespace_only(self, container, admin_session):
        with pytest.raises(BizError) as ei:
            container.resources.create_resource(admin_session, "   ")
        assert ei.value.code == "BAD_TITLE"

    def test_add_version(self, container, admin_session):
        res = container.resources.create_resource(admin_session, "Versioned")
        ver = container.resources.add_version(
            admin_session, res.id, "v1 summary", "v1 body")
        assert ver.version_no == 1
        assert ver.summary == "v1 summary"

    def test_list_versions_descending(self, container, admin_session):
        res = container.resources.create_resource(admin_session, "Multi-Ver")
        container.resources.add_version(
            admin_session, res.id, "First", "body1")
        container.resources.add_version(
            admin_session, res.id, "Second", "body2")
        versions = container.resources.list_versions(admin_session, res.id)
        assert len(versions) >= 2
        assert versions[0].summary == "Second"
        assert versions[1].summary == "First"

    def test_search_by_text(self, container, admin_session):
        container.resources.create_resource(admin_session, "Alpha Guide")
        container.resources.create_resource(admin_session, "Beta Manual")
        results = container.resources.search(admin_session, text="Alpha")
        assert any(r.title == "Alpha Guide" for r in results)

    def test_search_by_status(self, container, admin_session):
        res = container.resources.create_resource(admin_session, "Status Res")
        container.resources.place_on_hold(admin_session, res.id, "testing")
        on_hold = container.resources.search(admin_session, status="on_hold")
        assert any(r.id == res.id for r in on_hold)

    def test_publish_requires_catalog_attachment(self, container, admin_session):
        res = container.resources.create_resource(admin_session, "Unattached")
        ver = container.resources.add_version(
            admin_session, res.id, "s", "b")
        with pytest.raises(BizError) as ei:
            container.resources.publish_version(admin_session, ver.id)
        assert ei.value.code == "NOT_ATTACHED"

    def test_publish_requires_approval(self, container, admin_session):
        res = container.resources.create_resource(admin_session, "Unapproved")
        ver = container.resources.add_version(
            admin_session, res.id, "s", "b")
        container.catalog.attach(admin_session, res.id,
                                 node_id=None, type_code=None)
        with pytest.raises(BizError) as ei:
            container.resources.publish_version(admin_session, ver.id)
        assert ei.value.code == "NOT_APPROVED"

    def test_unpublish_version(self, container, admin_session):
        res = container.resources.create_resource(admin_session, "UnpubRes")
        ver = container.resources.add_version(
            admin_session, res.id, "s", "b")
        container.catalog.attach(admin_session, res.id,
                                 node_id=None, type_code=None)
        container.catalog.submit_for_review(admin_session, res.id)
        container.catalog.review(admin_session, res.id, "approve", "ok")
        container.resources.publish_version(admin_session, ver.id)
        container.resources.unpublish_version(admin_session, ver.id)
        versions = container.resources.list_versions(admin_session, res.id)
        target = [v for v in versions if v.id == ver.id][0]
        assert target.status == "unpublished"

    def test_place_on_hold(self, container, admin_session):
        res = container.resources.create_resource(admin_session, "Hold Me")
        container.resources.place_on_hold(admin_session, res.id, "under review")
        found = container.resources.search(admin_session, status="on_hold")
        assert any(r.id == res.id for r in found)

    def test_release_hold(self, container, admin_session):
        res = container.resources.create_resource(admin_session, "Hold&Release")
        container.resources.place_on_hold(admin_session, res.id, "temp")
        container.resources.release_hold(admin_session, res.id)
        active = container.resources.search(admin_session, status="active")
        assert any(r.id == res.id for r in active)

    def test_list_versions_denied_without_permission(self, container,
                                                     admin_session,
                                                     coordinator_session):
        res = container.resources.create_resource(admin_session, "Restricted")
        container.resources.add_version(admin_session, res.id, "s", "b")
        with pytest.raises(PermissionDenied):
            container.resources.list_versions(coordinator_session, res.id)

    def test_list_categories(self, container, admin_session):
        cats = container.resources.list_categories(admin_session)
        assert isinstance(cats, list)
