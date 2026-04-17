"""API tests for CheckpointService: workspace state and draft checkpoints."""
from __future__ import annotations


class TestWorkspace:
    def test_save_and_load(self, container, admin_session):
        payload = {"active_tab": 2, "open_tabs": ["Students", "Housing"]}
        container.checkpoints.save_workspace(admin_session, payload)
        loaded = container.checkpoints.load_workspace(admin_session)
        assert loaded == payload

    def test_load_empty(self, container, admin_session):
        loaded = container.checkpoints.load_workspace(admin_session)
        assert loaded is None

    def test_save_overwrites(self, container, admin_session):
        container.checkpoints.save_workspace(
            admin_session, {"active_tab": 0})
        container.checkpoints.save_workspace(
            admin_session, {"active_tab": 5})
        loaded = container.checkpoints.load_workspace(admin_session)
        assert loaded["active_tab"] == 5

    def test_per_user_isolation(self, container, admin_session,
                                coordinator_session):
        container.checkpoints.save_workspace(
            admin_session, {"user": "admin"})
        container.checkpoints.save_workspace(
            coordinator_session, {"user": "coord"})
        assert container.checkpoints.load_workspace(
            admin_session)["user"] == "admin"
        assert container.checkpoints.load_workspace(
            coordinator_session)["user"] == "coord"


class TestDrafts:
    def test_save_and_load(self, container, admin_session):
        payload = {"student_id": "S1", "full_name": "Draft Student"}
        container.checkpoints.save_draft(
            admin_session, "student:new", payload)
        loaded = container.checkpoints.load_draft(
            admin_session, "student:new")
        assert loaded == payload

    def test_load_not_found(self, container, admin_session):
        loaded = container.checkpoints.load_draft(
            admin_session, "nonexistent:key")
        assert loaded is None

    def test_list_drafts(self, container, admin_session):
        container.checkpoints.save_draft(
            admin_session, "draft:a", {"a": 1})
        container.checkpoints.save_draft(
            admin_session, "draft:b", {"b": 2})
        drafts = container.checkpoints.list_drafts(admin_session)
        keys = [d["draft_key"] for d in drafts]
        assert "draft:a" in keys
        assert "draft:b" in keys

    def test_discard_draft(self, container, admin_session):
        container.checkpoints.save_draft(
            admin_session, "discard:me", {"x": 1})
        container.checkpoints.discard_draft(admin_session, "discard:me")
        assert container.checkpoints.load_draft(
            admin_session, "discard:me") is None

    def test_discard_all(self, container, admin_session):
        container.checkpoints.save_draft(
            admin_session, "da:1", {"a": 1})
        container.checkpoints.save_draft(
            admin_session, "da:2", {"b": 2})
        count = container.checkpoints.discard_all(admin_session)
        assert count == 2
        assert container.checkpoints.list_drafts(admin_session) == []

    def test_draft_overwrite(self, container, admin_session):
        container.checkpoints.save_draft(
            admin_session, "ow:key", {"version": 1})
        container.checkpoints.save_draft(
            admin_session, "ow:key", {"version": 2})
        loaded = container.checkpoints.load_draft(admin_session, "ow:key")
        assert loaded["version"] == 2

    def test_per_user_isolation(self, container, admin_session,
                                coordinator_session):
        container.checkpoints.save_draft(
            admin_session, "iso:key", {"owner": "admin"})
        loaded = container.checkpoints.load_draft(
            coordinator_session, "iso:key")
        assert loaded is None
