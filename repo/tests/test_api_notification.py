"""API tests for NotificationService: templates, rules, enqueue, inbox,
drain, scheduled rules, retry, and template rendering."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from backend import db as _db
from backend.services.auth import BizError
from backend.services.notification import (
    _cron_matches, _cron_field_matches, render)


# ---- Template rendering ----------------------------------------------------

class TestRender:
    def test_substitutes_variables(self):
        assert render("{StudentName} in {Dorm}",
                       {"StudentName": "Alice", "Dorm": "Elm"}) == "Alice in Elm"

    def test_missing_variable_replaced_with_empty(self):
        assert render("Hello {StudentName}", {}) == "Hello "

    def test_no_variables(self):
        assert render("plain text", {"x": "y"}) == "plain text"

    def test_multiple_same_variable(self):
        assert render("{X} and {X}", {"X": "1"}) == "1 and 1"


# ---- Cron matching ---------------------------------------------------------

class TestCronMatching:
    def test_star_matches_any(self):
        assert _cron_field_matches("*", 5, 0, 59) is True

    def test_exact_match(self):
        assert _cron_field_matches("7", 7, 0, 59) is True
        assert _cron_field_matches("7", 8, 0, 59) is False

    def test_range(self):
        assert _cron_field_matches("1-5", 3, 0, 59) is True
        assert _cron_field_matches("1-5", 6, 0, 59) is False

    def test_list(self):
        assert _cron_field_matches("1,3,5", 3, 0, 59) is True
        assert _cron_field_matches("1,3,5", 4, 0, 59) is False

    def test_full_cron_match(self):
        when = datetime(2026, 4, 13, 7, 30)
        assert _cron_matches("30 7 * * *", when) is True
        assert _cron_matches("0 7 * * *", when) is False

    def test_cron_invalid_format(self):
        assert _cron_matches("bad", datetime.now()) is False
        assert _cron_matches(None, datetime.now()) is False
        assert _cron_matches("* *", datetime.now()) is False


# ---- Templates -------------------------------------------------------------

class TestTemplates:
    def test_upsert_creates(self, container, admin_session):
        tid = container.notifications.upsert_template(
            admin_session, "test_tpl", "Subject {StudentName}", "Body text")
        assert tid > 0

    def test_upsert_updates(self, container, admin_session):
        tid1 = container.notifications.upsert_template(
            admin_session, "upd_tpl", "Old subj", "Old body")
        tid2 = container.notifications.upsert_template(
            admin_session, "upd_tpl", "New subj", "New body")
        assert tid2 == tid1
        tpls = container.notifications.list_templates(admin_session)
        tpl = [t for t in tpls if t["name"] == "upd_tpl"][0]
        assert tpl["subject"] == "New subj"

    def test_list_templates(self, container, admin_session):
        container.notifications.upsert_template(
            admin_session, "list_tpl", "S", "B")
        tpls = container.notifications.list_templates(admin_session)
        assert any(t["name"] == "list_tpl" for t in tpls)


# ---- Enqueue and drain -----------------------------------------------------

class TestEnqueueAndDrain:
    def test_enqueue_creates_queued_messages(self, container, admin_session):
        container.notifications.upsert_template(
            admin_session, "eq_tpl", "Hi {StudentName}", "Body")
        msg_ids = container.notifications.enqueue(
            admin_session, template_name="eq_tpl",
            audience_user_ids=[admin_session.user_id],
            variables={"StudentName": "Alice"})
        assert len(msg_ids) == 1
        assert msg_ids[0] > 0

    def test_drain_delivers(self, container, admin_session):
        container.notifications.upsert_template(
            admin_session, "drain_tpl", "Drain test", "Body")
        container.notifications.enqueue(
            admin_session, template_name="drain_tpl",
            audience_user_ids=[admin_session.user_id],
            variables={})
        delivered = container.notifications.drain_queue()
        assert delivered >= 1

    def test_enqueue_unknown_template(self, container, admin_session):
        with pytest.raises(BizError) as ei:
            container.notifications.enqueue(
                admin_session, template_name="nonexistent",
                audience_user_ids=[1], variables={})
        assert ei.value.code == "TEMPLATE_NOT_FOUND"

    def test_scheduled_for_future_not_drained(self, container, admin_session):
        container.notifications.upsert_template(
            admin_session, "future_tpl", "Future", "Body")
        future = datetime.utcnow() + timedelta(hours=1)
        container.notifications.enqueue(
            admin_session, template_name="future_tpl",
            audience_user_ids=[admin_session.user_id],
            variables={}, scheduled_for=future)
        delivered = container.notifications.drain_queue()
        # The message should NOT be delivered yet
        inbox = container.notifications.inbox(admin_session)
        future_msgs = [m for m in inbox if m.subject == "Future"]
        assert len(future_msgs) == 0


# ---- Inbox -----------------------------------------------------------------

class TestInbox:
    def _enqueue_and_drain(self, container, session, subject="Test"):
        container.notifications.upsert_template(
            session, "inbox_tpl", subject, "Body")
        container.notifications.enqueue(
            session, template_name="inbox_tpl",
            audience_user_ids=[session.user_id], variables={})
        container.notifications.drain_queue()

    def test_inbox_returns_delivered(self, container, admin_session):
        self._enqueue_and_drain(container, admin_session, "InboxTest")
        msgs = container.notifications.inbox(admin_session)
        assert any(m.subject == "InboxTest" for m in msgs)

    def test_unread_count(self, container, admin_session):
        self._enqueue_and_drain(container, admin_session, "CountTest")
        count = container.notifications.unread_count(admin_session)
        assert count >= 1

    def test_mark_read_reduces_count(self, container, admin_session):
        self._enqueue_and_drain(container, admin_session, "ReadTest")
        msgs = container.notifications.inbox(admin_session)
        unread_before = container.notifications.unread_count(admin_session)
        msg = [m for m in msgs if m.read_at is None][0]
        container.notifications.mark_read(admin_session, msg.id)
        unread_after = container.notifications.unread_count(admin_session)
        assert unread_after == unread_before - 1

    def test_inbox_only_unread(self, container, admin_session):
        self._enqueue_and_drain(container, admin_session, "UnreadFilter")
        msgs = container.notifications.inbox(admin_session)
        if msgs:
            container.notifications.mark_read(admin_session, msgs[0].id)
        unread = container.notifications.inbox(admin_session, only_unread=True)
        assert all(m.read_at is None for m in unread)


# ---- Rules -----------------------------------------------------------------

class TestRules:
    def test_list_rules(self, container, admin_session):
        rules = container.notifications.list_rules(admin_session)
        assert isinstance(rules, list)

    def test_set_rule_enabled(self, container, admin_session):
        rules = container.notifications.list_rules(admin_session)
        if not rules:
            return
        rid = rules[0]["id"]
        container.notifications.set_rule_enabled(admin_session, rid, False)
        rules2 = container.notifications.list_rules(admin_session)
        rule = [r for r in rules2 if r["id"] == rid][0]
        assert rule["enabled"] == 0
        container.notifications.set_rule_enabled(admin_session, rid, True)


# ---- Retry -----------------------------------------------------------------

class TestRetry:
    def test_retry_failed_requeues_dead(self, container, admin_session):
        container.notifications.upsert_template(
            admin_session, "retry_tpl", "Retry", "Body")
        container.notifications.enqueue(
            admin_session, template_name="retry_tpl",
            audience_user_ids=[admin_session.user_id], variables={})
        # Manually mark as dead
        conn = _db.get_connection()
        conn.execute(
            "UPDATE notif_messages SET status='dead' "
            "WHERE status='queued'")
        requeued = container.notifications.retry_failed(admin_session)
        assert requeued >= 1
