"""Service-layer API tests for CatalogService."""
from __future__ import annotations

import pytest
from backend.services.auth import BizError
from backend.services.catalog import bump
from backend import db as _db


class TestCatalogTree:

    def test_create_and_list_tree(self, container, admin_session):
        container.catalog.create_node(admin_session, "NodeA")
        container.catalog.create_node(admin_session, "NodeB")
        tree = container.catalog.list_tree()
        names = [n.name for n in tree]
        assert "NodeA" in names
        assert "NodeB" in names

    def test_create_child_node(self, container, admin_session):
        parent_id = container.catalog.create_node(admin_session, "Parent")
        child_id = container.catalog.create_node(
            admin_session, "Child", parent_id=parent_id)
        assert child_id > 0
        tree = container.catalog.list_tree()
        parent = [n for n in tree if n.name == "Parent"][0]
        assert any(c.name == "Child" for c in parent.children)

    def test_rename_node(self, container, admin_session):
        nid = container.catalog.create_node(admin_session, "OldName")
        container.catalog.rename_node(admin_session, nid, "NewName")
        tree = container.catalog.list_tree()
        names = [n.name for n in tree]
        assert "NewName" in names
        assert "OldName" not in names

    def test_delete_empty_node(self, container, admin_session):
        nid = container.catalog.create_node(admin_session, "Ephemeral")
        container.catalog.delete_node(admin_session, nid)
        tree = container.catalog.list_tree()
        names = [n.name for n in tree]
        assert "Ephemeral" not in names

    def test_delete_node_in_use_fails(self, container, admin_session):
        nid = container.catalog.create_node(admin_session, "InUseNode")
        res = container.resources.create_resource(admin_session, "Attached Res")
        container.catalog.attach(admin_session, res.id,
                                 node_id=nid, type_code=None)
        with pytest.raises(BizError) as ei:
            container.catalog.delete_node(admin_session, nid)
        assert ei.value.code == "NODE_IN_USE"

    def test_empty_name_fails(self, container, admin_session):
        with pytest.raises(BizError) as ei:
            container.catalog.create_node(admin_session, "  ")
        assert ei.value.code == "BAD_NAME"


class TestCatalogTypes:

    def test_upsert_type_creates(self, container, admin_session):
        fields = [{"code": "color", "label": "Color",
                   "field_type": "text", "required": True}]
        tid = container.catalog.upsert_type(
            admin_session, "widget", "Widget", fields=fields)
        assert tid > 0
        t = container.catalog.get_type("widget")
        assert t is not None
        assert t.name == "Widget"
        assert len(t.fields) == 1

    def test_upsert_type_updates(self, container, admin_session):
        fields_v1 = [{"code": "size", "label": "Size",
                      "field_type": "text", "required": False}]
        container.catalog.upsert_type(
            admin_session, "gadget", "Gadget", fields=fields_v1)
        fields_v2 = [{"code": "weight", "label": "Weight",
                      "field_type": "int", "required": True}]
        container.catalog.upsert_type(
            admin_session, "gadget", "Gadget Updated", fields=fields_v2)
        t = container.catalog.get_type("gadget")
        assert t.name == "Gadget Updated"
        assert len(t.fields) == 1
        assert t.fields[0].code == "weight"

    def test_get_type(self, container, admin_session):
        fields = [{"code": "length", "label": "Length",
                   "field_type": "int", "required": True}]
        container.catalog.upsert_type(
            admin_session, "beam", "Beam", fields=fields)
        t = container.catalog.get_type("beam")
        assert t.code == "beam"
        assert t.name == "Beam"

    def test_get_type_not_found(self, container):
        assert container.catalog.get_type("nonexistent") is None

    def test_bad_field_type(self, container, admin_session):
        fields = [{"code": "x", "label": "X",
                   "field_type": "bogus", "required": False}]
        with pytest.raises(BizError) as ei:
            container.catalog.upsert_type(
                admin_session, "bad_ft", "BadFT", fields=fields)
        assert ei.value.code == "BAD_FIELD_TYPE"

    def test_enum_requires_values(self, container, admin_session):
        fields = [{"code": "status", "label": "Status",
                   "field_type": "enum", "required": True}]
        with pytest.raises(BizError) as ei:
            container.catalog.upsert_type(
                admin_session, "bad_enum", "BadEnum", fields=fields)
        assert ei.value.code == "BAD_FIELD"


class TestCatalogAttach:

    def test_attach_resource(self, container, admin_session):
        nid = container.catalog.create_node(admin_session, "AttachNode")
        res = container.resources.create_resource(admin_session, "Attachable")
        container.catalog.attach(admin_session, res.id,
                                 node_id=nid, type_code=None)
        att = container.catalog.get_attachment(res.id)
        assert att is not None
        assert att["node_id"] == nid

    def test_attach_with_metadata(self, container, admin_session):
        fields = [{"code": "color", "label": "Color",
                   "field_type": "text", "required": True}]
        container.catalog.upsert_type(
            admin_session, "colored", "Colored", fields=fields)
        nid = container.catalog.create_node(admin_session, "MetaNode")
        res = container.resources.create_resource(admin_session, "MetaRes")
        container.catalog.attach(admin_session, res.id,
                                 node_id=nid, type_code="colored",
                                 metadata={"color": "red"})
        meta = container.catalog.get_metadata(res.id)
        assert meta["color"] == "red"

    def test_attach_with_tags(self, container, admin_session):
        nid = container.catalog.create_node(admin_session, "TagNode")
        res = container.resources.create_resource(admin_session, "TagRes")
        container.catalog.attach(admin_session, res.id,
                                 node_id=nid, type_code=None,
                                 tags=["important", "urgent"])
        tags = container.catalog.list_tags(res.id)
        assert "important" in tags
        assert "urgent" in tags

    def test_metadata_required_field_missing(self, container, admin_session):
        fields = [{"code": "serial", "label": "Serial",
                   "field_type": "text", "required": True}]
        container.catalog.upsert_type(
            admin_session, "serialized", "Serialized", fields=fields)
        nid = container.catalog.create_node(admin_session, "ValNode")
        res = container.resources.create_resource(admin_session, "MissingMeta")
        with pytest.raises(BizError) as ei:
            container.catalog.attach(admin_session, res.id,
                                     node_id=nid, type_code="serialized",
                                     metadata={})
        assert ei.value.code == "METADATA_MISSING"


class TestCatalogRelations:

    def test_relate_resources(self, container, admin_session):
        r1 = container.resources.create_resource(admin_session, "Source")
        r2 = container.resources.create_resource(admin_session, "Dest")
        container.catalog.relate(admin_session, r1.id, r2.id, "related")

    def test_relate_self_fails(self, container, admin_session):
        r = container.resources.create_resource(admin_session, "Lonely")
        with pytest.raises(BizError) as ei:
            container.catalog.relate(admin_session, r.id, r.id, "related")
        assert ei.value.code == "BAD_RELATION"

    def test_bad_relation_type(self, container, admin_session):
        r1 = container.resources.create_resource(admin_session, "Src")
        r2 = container.resources.create_resource(admin_session, "Dst")
        with pytest.raises(BizError) as ei:
            container.catalog.relate(admin_session, r1.id, r2.id, "depends_on")
        assert ei.value.code == "BAD_RELATION"


class TestCatalogReview:

    def test_review_approve(self, container, admin_session):
        nid = container.catalog.create_node(admin_session, "RevNode")
        res = container.resources.create_resource(admin_session, "ReviewMe")
        container.catalog.attach(admin_session, res.id,
                                 node_id=nid, type_code=None)
        container.catalog.submit_for_review(admin_session, res.id)
        container.catalog.review(admin_session, res.id, "approve", "ok")
        att = container.catalog.get_attachment(res.id)
        assert att["review_state"] == "approved"

    def test_review_reject(self, container, admin_session):
        nid = container.catalog.create_node(admin_session, "RejNode")
        res = container.resources.create_resource(admin_session, "RejectMe")
        container.catalog.attach(admin_session, res.id,
                                 node_id=nid, type_code=None)
        container.catalog.submit_for_review(admin_session, res.id)
        container.catalog.review(admin_session, res.id, "reject", "Not ready")
        att = container.catalog.get_attachment(res.id)
        assert att["review_state"] == "rejected"

    def test_review_bad_decision(self, container, admin_session):
        nid = container.catalog.create_node(admin_session, "BadDecNode")
        res = container.resources.create_resource(admin_session, "BadDec")
        container.catalog.attach(admin_session, res.id,
                                 node_id=nid, type_code=None)
        container.catalog.submit_for_review(admin_session, res.id)
        with pytest.raises(BizError) as ei:
            container.catalog.review(admin_session, res.id, "maybe")
        assert ei.value.code == "BAD_DECISION"

    def test_publish_with_semver(self, container, admin_session):
        nid = container.catalog.create_node(admin_session, "SemNode")
        res = container.resources.create_resource(admin_session, "SemRes")
        container.resources.add_version(admin_session, res.id, "v1", "body")
        container.catalog.attach(admin_session, res.id,
                                 node_id=nid, type_code=None)
        container.catalog.submit_for_review(admin_session, res.id)
        container.catalog.review(admin_session, res.id, "approve", "ok")
        new_v = container.catalog.publish_with_semver(
            admin_session, res.id, level="minor")
        assert new_v == "0.2.0"


class TestSemverBump:

    def test_major(self):
        assert bump("0.1.0", "major") == "1.0.0"

    def test_minor(self):
        assert bump("0.1.0", "minor") == "0.2.0"

    def test_patch(self):
        assert bump("0.1.0", "patch") == "0.1.1"

    def test_from_higher_version(self):
        assert bump("2.3.4", "minor") == "2.4.0"
        assert bump("2.3.4", "patch") == "2.3.5"
        assert bump("2.3.4", "major") == "3.0.0"

    def test_invalid_version(self):
        # Should parse to (0, 1, 0) fallback
        assert bump("", "minor") == "0.2.0"
        assert bump("bad", "minor") == "0.2.0"
