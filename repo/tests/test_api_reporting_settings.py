"""API tests for ReportingService and SettingsService."""
from __future__ import annotations

import pytest

from backend.permissions import PermissionDenied
from backend.services.auth import BizError

try:
    import openpyxl
    _HAVE_OPENPYXL = True
except ImportError:
    _HAVE_OPENPYXL = False


# ---- ReportingService ------------------------------------------------------

class TestOccupancyReport:
    def test_returns_report(self, container, admin_session):
        report = container.reporting.occupancy(admin_session)
        assert report.title == "Occupancy by Dorm"
        assert "Building" in report.columns
        assert "Beds" in report.columns
        assert "Occupied" in report.columns
        assert isinstance(report.rows, list)
        assert "total_beds" in report.summary

    def test_as_of_parameter(self, container, admin_session):
        from datetime import date
        report = container.reporting.occupancy(
            admin_session, as_of=date(2026, 1, 1))
        assert report.summary["as_of"] == "2026-01-01"


class TestMoveTrends:
    def test_returns_report(self, container, admin_session):
        report = container.reporting.move_trends(admin_session, days=30)
        assert "Move trends" in report.title
        assert "Date" in report.columns


class TestResourceVelocity:
    def test_returns_report(self, container, admin_session):
        report = container.reporting.resource_velocity(admin_session)
        assert "velocity" in report.title.lower()
        assert "total" in report.summary


class TestComplianceSla:
    def test_returns_report(self, container, admin_session):
        report = container.reporting.compliance_sla(admin_session)
        assert "Compliance SLA" in report.title


class TestNotificationDelivery:
    def test_returns_report(self, container, admin_session):
        report = container.reporting.notification_delivery(admin_session)
        assert "Notification delivery" in report.title


class TestReportExport:
    def test_csv_export(self, container, admin_session, tmp_path):
        report = container.reporting.occupancy(admin_session)
        out = tmp_path / "report.csv"
        container.reporting.export(admin_session, report, "csv", str(out))
        assert out.is_file()
        content = out.read_text()
        assert "Building" in content

    @pytest.mark.skipif(not _HAVE_OPENPYXL, reason="openpyxl not installed")
    def test_xlsx_export(self, container, admin_session, tmp_path):
        report = container.reporting.occupancy(admin_session)
        out = tmp_path / "report.xlsx"
        container.reporting.export(admin_session, report, "xlsx", str(out))
        assert out.is_file()

    def test_bad_format(self, container, admin_session, tmp_path):
        report = container.reporting.occupancy(admin_session)
        with pytest.raises(ValueError):
            container.reporting.export(
                admin_session, report, "pdf", str(tmp_path / "x.pdf"))

    def test_denied_without_permission(self, container, coordinator_session):
        with pytest.raises(PermissionDenied):
            container.reporting.occupancy(coordinator_session)


# ---- SettingsService -------------------------------------------------------

class TestSettingsGetSet:
    def test_get_set_roundtrip(self, container, admin_session):
        container.settings.set(admin_session, "test.key", "hello")
        assert container.settings.get("test.key") == "hello"

    def test_get_missing_returns_none(self, container):
        assert container.settings.get("nonexistent.key") is None

    def test_set_overwrites(self, container, admin_session):
        container.settings.set(admin_session, "ow.key", "v1")
        container.settings.set(admin_session, "ow.key", "v2")
        assert container.settings.get("ow.key") == "v2"

    def test_set_denied_without_permission(self, container,
                                           coordinator_session):
        with pytest.raises(PermissionDenied):
            container.settings.set(coordinator_session, "k", "v")


class TestSynonyms:
    def test_add_synonym(self, container, admin_session):
        sid = container.settings.add_synonym(
            admin_session, "dorm", "residence")
        assert sid is not None

    def test_list_synonyms(self, container, admin_session):
        container.settings.add_synonym(admin_session, "hall", "building")
        syns = container.settings.list_synonyms()
        assert any(s["term"] == "hall" and s["alt_term"] == "building"
                   for s in syns)

    def test_remove_synonym(self, container, admin_session):
        container.settings.add_synonym(admin_session, "rm_term", "rm_alt")
        syns = container.settings.list_synonyms()
        sid = [s["id"] for s in syns
               if s["term"] == "rm_term" and s["alt_term"] == "rm_alt"][0]
        container.settings.remove_synonym(admin_session, sid)
        syns2 = container.settings.list_synonyms()
        assert not any(s["id"] == sid for s in syns2)

    def test_add_synonym_denied_without_permission(self, container,
                                                   coordinator_session):
        with pytest.raises(PermissionDenied):
            container.settings.add_synonym(
                coordinator_session, "test", "syn")
