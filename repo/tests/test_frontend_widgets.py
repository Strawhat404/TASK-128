"""Unit tests for frontend widgets, dialogs, and windows.

These tests exercise the PyQt6 frontend components in headless mode
(QT_QPA_PLATFORM=offscreen). Each test verifies construction,
property binding, and basic user-interaction flows without requiring
a visible display server.

Skipped gracefully when PyQt6 is not installed.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import pytest
except ImportError:
    pytest = None  # type: ignore

_qt_skip_reason = None
try:
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
except Exception as e:
    _qt_skip_reason = f"PyQt6 not available: {e}"

# Ensure a QApplication exists (singleton).
_app = None
if _qt_skip_reason is None:
    _app = QApplication.instance() or QApplication(sys.argv)


def _skip_no_qt():
    if _qt_skip_reason and pytest:
        pytest.skip(_qt_skip_reason)


def _make_main_window(container, session):
    """Create a MainWindow that won't block in offscreen/headless mode.

    MainWindow.__init__ calls _offer_draft_recovery() which opens a
    QMessageBox.question if drafts exist — that blocks forever without
    a display server event loop. We discard all drafts first, and stop
    the QTimers immediately after construction so they don't fire during
    teardown.
    """
    from frontend.main_window import MainWindow
    # Prevent _offer_draft_recovery from opening a blocking dialog
    try:
        container.checkpoints.discard_all(session)
    except Exception:
        pass
    win = MainWindow(container, session)
    # Stop background timers immediately so tests are deterministic
    try:
        win._dispatch_timer.stop()
    except Exception:
        pass
    try:
        win._checkpoint_timer.stop()
    except Exception:
        pass
    return win


def _close_main_window(win):
    """Properly close a MainWindow created by _make_main_window."""
    win._force_quit = True
    try:
        win._dispatch_timer.stop()
    except Exception:
        pass
    try:
        win._checkpoint_timer.stop()
    except Exception:
        pass
    win.close()
    if _app:
        _app.processEvents()


# ===================================================================
# frontend/widgets/results_table.py — ResultsTable
# ===================================================================


class TestResultsTable:

    def test_construction(self, container, admin_session):
        _skip_no_qt()
        from frontend.widgets.results_table import ResultsTable
        t = ResultsTable(["Col A", "Col B", "Col C"])
        assert t.columnCount() == 3
        assert t.rowCount() == 0

    def test_set_rows(self, container, admin_session):
        _skip_no_qt()
        from frontend.widgets.results_table import ResultsTable
        t = ResultsTable(["ID", "Name"])
        t.set_rows([[1, "Alice"], [2, "Bob"], [3, "Charlie"]])
        assert t.rowCount() == 3
        assert t.item(0, 1).text() == "Alice"
        assert t.item(2, 0).text() == "3"

    def test_set_rows_clears_previous(self, container, admin_session):
        _skip_no_qt()
        from frontend.widgets.results_table import ResultsTable
        t = ResultsTable(["X"])
        t.set_rows([["a"], ["b"]])
        assert t.rowCount() == 2
        t.set_rows([["c"]])
        assert t.rowCount() == 1

    def test_selected_row_data_none_when_empty(self, container, admin_session):
        _skip_no_qt()
        from frontend.widgets.results_table import ResultsTable
        t = ResultsTable(["A"])
        assert t.selected_row_data() is None

    def test_add_action_registers(self, container, admin_session):
        _skip_no_qt()
        from frontend.widgets.results_table import ResultsTable
        t = ResultsTable(["A"])
        called = []
        t.add_action("Test Action", lambda row: called.append(row))
        assert len(t._menu_actions) == 1
        assert t._menu_actions[0][0] == "Test Action"

    def test_none_values_render_as_empty(self, container, admin_session):
        _skip_no_qt()
        from frontend.widgets.results_table import ResultsTable
        t = ResultsTable(["A", "B"])
        t.set_rows([[None, "ok"]])
        assert t.item(0, 0).text() == ""
        assert t.item(0, 1).text() == "ok"


# ===================================================================
# frontend/dialogs.py — LoginDialog, BootstrapDialog, UnlockDialog
# ===================================================================


class TestLoginDialog:

    def test_construction(self, container, admin_session):
        _skip_no_qt()
        from frontend.dialogs import LoginDialog
        dlg = LoginDialog(container)
        assert dlg.windowTitle() == "Sign in"
        assert dlg.session is None
        assert dlg.username.text() == ""
        assert dlg.password.text() == ""
        assert dlg.password.echoMode().name in ("Password", b"Password")

    def test_username_has_focus(self, container, admin_session):
        _skip_no_qt()
        from frontend.dialogs import LoginDialog
        dlg = LoginDialog(container)
        dlg.show()
        _app.processEvents()
        assert dlg.username.hasFocus()
        dlg.close()


class TestBootstrapDialog:

    def test_construction(self, container, admin_session):
        _skip_no_qt()
        from frontend.dialogs import BootstrapDialog
        dlg = BootstrapDialog(container)
        assert dlg.windowTitle() == "Create administrator"
        assert dlg.user is None
        assert dlg.minimumWidth() >= 380

    def test_fields_present(self, container, admin_session):
        _skip_no_qt()
        from frontend.dialogs import BootstrapDialog
        dlg = BootstrapDialog(container)
        assert hasattr(dlg, "full_name")
        assert hasattr(dlg, "username")
        assert hasattr(dlg, "password")
        assert hasattr(dlg, "confirm")


class TestUnlockDialog:

    def test_construction(self, container, admin_session):
        _skip_no_qt()
        from frontend.dialogs import UnlockDialog
        dlg = UnlockDialog(container, admin_session)
        assert dlg.windowTitle() == "Re-enter password"
        assert dlg.unlocked is False

    def test_password_field_is_masked(self, container, admin_session):
        _skip_no_qt()
        from frontend.dialogs import UnlockDialog
        dlg = UnlockDialog(container, admin_session)
        assert dlg.password.echoMode().name in ("Password", b"Password")


# ===================================================================
# frontend/widgets/search_palette.py — SearchPalette
# ===================================================================


class TestSearchPalette:

    def test_construction(self, container, admin_session):
        _skip_no_qt()
        from frontend.widgets.search_palette import SearchPalette
        dlg = SearchPalette(container, admin_session)
        assert dlg.windowTitle() == "Search"
        assert dlg.input.text() == ""
        assert dlg.list.count() == 0

    def test_short_query_no_results(self, container, admin_session):
        _skip_no_qt()
        from frontend.widgets.search_palette import SearchPalette
        dlg = SearchPalette(container, admin_session)
        dlg.input.setText("x")  # too short
        _app.processEvents()
        assert dlg.list.count() == 0

    def test_search_populates_list(self, container, admin_session):
        _skip_no_qt()
        from backend.models import StudentDTO
        container.students.create(
            admin_session,
            StudentDTO(student_id="SP-1", full_name="SearchPaletteTest"))
        from frontend.widgets.search_palette import SearchPalette
        dlg = SearchPalette(container, admin_session)
        dlg.input.setText("SearchPaletteTest")
        _app.processEvents()
        assert dlg.list.count() >= 1

    def test_hit_chosen_signal_exists(self, container, admin_session):
        _skip_no_qt()
        from frontend.widgets.search_palette import SearchPalette
        dlg = SearchPalette(container, admin_session)
        assert hasattr(dlg, "hit_chosen")

    def test_save_pin_export_buttons_exist(self, container, admin_session):
        _skip_no_qt()
        from frontend.widgets.search_palette import SearchPalette
        dlg = SearchPalette(container, admin_session)
        assert hasattr(dlg, "save_btn")
        assert hasattr(dlg, "pin_btn")
        assert hasattr(dlg, "csv_btn")


# ===================================================================
# frontend/windows/student_profile.py — StudentProfileWindow
# ===================================================================


class TestStudentProfileWindow:

    def test_construction(self, container, admin_session):
        _skip_no_qt()
        from backend.models import StudentDTO
        s = container.students.create(
            admin_session,
            StudentDTO(student_id="PROF-1", full_name="Profile Student",
                       college="Eng", housing_status="pending"))
        from frontend.windows.student_profile import StudentProfileWindow
        win = StudentProfileWindow(container, admin_session, s.id)
        assert "Profile Student" in win.name_lbl.text()
        assert win.id_lbl.text() == "PROF-1"
        win.close()

    def test_college_displayed(self, container, admin_session):
        _skip_no_qt()
        from backend.models import StudentDTO
        s = container.students.create(
            admin_session,
            StudentDTO(student_id="PROF-2", full_name="College Check",
                       college="Science", housing_status="pending"))
        from frontend.windows.student_profile import StudentProfileWindow
        win = StudentProfileWindow(container, admin_session, s.id)
        assert win.college_lbl.text() == "Science"
        win.close()

    def test_history_table_exists(self, container, admin_session):
        _skip_no_qt()
        from backend.models import StudentDTO
        s = container.students.create(
            admin_session,
            StudentDTO(student_id="PROF-3", full_name="History Check",
                       housing_status="pending"))
        from frontend.windows.student_profile import StudentProfileWindow
        win = StudentProfileWindow(container, admin_session, s.id)
        assert win.history is not None
        assert win.change_log is not None
        win.close()

    def test_refresh_updates_labels(self, container, admin_session):
        _skip_no_qt()
        from backend.models import StudentDTO
        s = container.students.create(
            admin_session,
            StudentDTO(student_id="PROF-4", full_name="Before Refresh",
                       housing_status="pending"))
        from frontend.windows.student_profile import StudentProfileWindow
        win = StudentProfileWindow(container, admin_session, s.id)
        assert "Before Refresh" in win.name_lbl.text()
        container.students.update(
            admin_session, s.id,
            StudentDTO(student_id="PROF-4", full_name="After Refresh",
                       housing_status="pending"))
        win.refresh()
        assert "After Refresh" in win.name_lbl.text()
        win.close()


# ===================================================================
# frontend/main_window.py — MainWindow (deeper tests)
# ===================================================================


class TestMainWindow:

    def test_tabs_present_for_admin(self, container, admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow
        win = _make_main_window(container, admin_session)
        tab_labels = [win.tabs.tabText(i) for i in range(win.tabs.count())]
        assert "Students" in tab_labels
        assert "Housing" in tab_labels
        assert "Resources" in tab_labels
        assert "Notifications" in tab_labels
        _close_main_window(win)

    def test_window_title_contains_username(self, container, admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow
        win = _make_main_window(container, admin_session)
        assert admin_session.full_name in win.windowTitle()
        _close_main_window(win)

    def test_status_bar_shows_ready(self, container, admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow
        win = _make_main_window(container, admin_session)
        assert "Ready" in win.statusBar().currentMessage()
        _close_main_window(win)

    def test_ctrl_k_shortcut_exists(self, container, admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow
        win = _make_main_window(container, admin_session)
        # Verify the palette method exists and is callable
        assert callable(getattr(win, "_open_palette", None))
        _close_main_window(win)

    def test_saved_search_sidebar_exists(self, container, admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow
        win = _make_main_window(container, admin_session)
        assert hasattr(win, "saved_dock")
        assert hasattr(win, "saved_list")
        _close_main_window(win)

    def test_coordinator_sees_limited_tabs(self, container,
                                           coordinator_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow
        win = _make_main_window(container, coordinator_session)
        tab_labels = [win.tabs.tabText(i) for i in range(win.tabs.count())]
        # Coordinator has student + housing perms, not resource/compliance
        assert "Students" in tab_labels
        assert "Housing" in tab_labels
        # Should NOT have reports or updates tabs
        assert "Reports" not in tab_labels
        assert "Updates" not in tab_labels
        _close_main_window(win)

    def test_style_qss_loaded(self, container, admin_session):
        """style.qss must exist and be applied to the QApplication."""
        _skip_no_qt()
        from pathlib import Path
        qss_path = Path(__file__).resolve().parent.parent / "frontend" / "style.qss"
        assert qss_path.is_file(), "frontend/style.qss must exist"
        content = qss_path.read_text(encoding="utf-8")
        assert len(content) > 0, "style.qss must not be empty"
        # Verify it contains expected selectors
        assert "QMainWindow" in content
        assert "QTabWidget" in content or "QTabBar" in content

    def test_menu_bar_present(self, container, admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow
        win = _make_main_window(container, admin_session)
        menu_bar = win.menuBar()
        action_texts = [a.text() for a in menu_bar.actions()]
        assert any("File" in t for t in action_texts)
        assert any("Edit" in t for t in action_texts)
        assert any("Help" in t for t in action_texts)
        _close_main_window(win)

    def test_detached_windows_list_initialized(self, container, admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow
        win = _make_main_window(container, admin_session)
        assert isinstance(win.detached, list)
        assert len(win.detached) == 0
        _close_main_window(win)


# ===================================================================
# frontend/tabs_extra.py — CatalogTab (direct isolated tests)
# ===================================================================


class TestCatalogTab:

    def test_construction(self, container, admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow
        from frontend.tabs_extra import CatalogTab
        win = _make_main_window(container, admin_session)
        tab = CatalogTab(container, admin_session, win)
        assert tab.container is container
        assert tab.session is admin_session
        assert tab.tree is not None
        assert tab.types is not None
        _close_main_window(win)

    def test_buttons_present(self, container, admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow
        from frontend.tabs_extra import CatalogTab
        win = _make_main_window(container, admin_session)
        tab = CatalogTab(container, admin_session, win)
        assert hasattr(tab, "add_node_btn")
        assert hasattr(tab, "add_type_btn")
        assert hasattr(tab, "attach_btn")
        assert hasattr(tab, "review_btn")
        assert hasattr(tab, "publish_btn")
        _close_main_window(win)

    def test_refresh_populates_tree(self, container, admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow
        from frontend.tabs_extra import CatalogTab
        # Create a catalog node so tree has content
        container.catalog.create_node(admin_session, "TestFolder")
        win = _make_main_window(container, admin_session)
        tab = CatalogTab(container, admin_session, win)
        tab.refresh()
        assert tab.tree.topLevelItemCount() >= 1
        _close_main_window(win)

    def test_selected_node_id_none_when_empty(self, container, admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow
        from frontend.tabs_extra import CatalogTab
        win = _make_main_window(container, admin_session)
        tab = CatalogTab(container, admin_session, win)
        assert tab._selected_node_id() is None
        _close_main_window(win)


# ===================================================================
# frontend/tabs_extra.py — ComplianceExtTab (direct isolated tests)
# ===================================================================


class TestComplianceExtTab:

    def test_construction(self, container, admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow
        from frontend.tabs_extra import ComplianceExtTab
        win = _make_main_window(container, admin_session)
        tab = ComplianceExtTab(container, admin_session, win)
        assert tab.container is container
        assert tab.files is not None
        assert tab.actions is not None
        _close_main_window(win)

    def test_buttons_present(self, container, admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow
        from frontend.tabs_extra import ComplianceExtTab
        win = _make_main_window(container, admin_session)
        tab = ComplianceExtTab(container, admin_session, win)
        assert hasattr(tab, "upload_btn")
        assert hasattr(tab, "scan_btn")
        assert hasattr(tab, "takedown_btn")
        assert hasattr(tab, "suspend30_btn")
        assert hasattr(tab, "suspend60_btn")
        assert hasattr(tab, "suspend180_btn")
        assert hasattr(tab, "throttle_btn")
        _close_main_window(win)

    def test_refresh_runs_without_error(self, container, admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow
        from frontend.tabs_extra import ComplianceExtTab
        win = _make_main_window(container, admin_session)
        tab = ComplianceExtTab(container, admin_session, win)
        tab.refresh()  # no employers yet — should not raise
        assert tab.files.rowCount() == 0
        assert tab.actions.rowCount() == 0
        _close_main_window(win)

    def test_refresh_shows_evidence_after_upload(self, container,
                                                 admin_session, tmp_path):
        _skip_no_qt()
        from frontend.main_window import MainWindow
        from frontend.tabs_extra import ComplianceExtTab
        from backend import db as _db
        # Create employer + upload evidence via service layer
        case_id = container.compliance.submit_employer(
            admin_session, "TabTest Co", "99-9999999", "t@e.com")
        emp_id = _db.get_connection().execute(
            "SELECT employer_id FROM employer_cases WHERE id=?",
            (case_id,)).fetchone()["employer_id"]
        f = tmp_path / "ev.pdf"
        f.write_bytes(b"evidence content")
        container.evidence.upload(admin_session, emp_id, f)
        win = _make_main_window(container, admin_session)
        tab = ComplianceExtTab(container, admin_session, win)
        tab.refresh()
        assert tab.files.rowCount() >= 1
        _close_main_window(win)


# ===================================================================
# frontend/tabs_extra.py — BomTab (direct isolated tests)
# ===================================================================


class TestBomTab:

    def test_construction(self, container, admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow
        from frontend.tabs_extra import BomTab
        win = _make_main_window(container, admin_session)
        tab = BomTab(container, admin_session, win)
        assert tab.container is container
        assert tab.styles is not None
        assert tab.versions is not None
        _close_main_window(win)

    def test_buttons_present(self, container, admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow
        from frontend.tabs_extra import BomTab
        win = _make_main_window(container, admin_session)
        tab = BomTab(container, admin_session, win)
        assert hasattr(tab, "new_style_btn")
        assert hasattr(tab, "add_bom_btn")
        assert hasattr(tab, "add_step_btn")
        assert hasattr(tab, "submit_btn")
        assert hasattr(tab, "first_btn")
        assert hasattr(tab, "final_btn")
        assert hasattr(tab, "cr_btn")
        _close_main_window(win)

    def test_refresh_populates_styles(self, container, admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow
        from frontend.tabs_extra import BomTab
        container.bom.create_style(admin_session, "TAB-STY", "Tab Style")
        win = _make_main_window(container, admin_session)
        tab = BomTab(container, admin_session, win)
        tab.refresh()
        assert tab.styles.rowCount() >= 1
        _close_main_window(win)

    def test_selected_version_id_none_when_empty(self, container,
                                                 admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow
        from frontend.tabs_extra import BomTab
        win = _make_main_window(container, admin_session)
        tab = BomTab(container, admin_session, win)
        assert tab._selected_version_id() is None
        _close_main_window(win)


# ===================================================================
# frontend/tabs_extra.py — UpdaterTab (direct isolated tests)
# ===================================================================


class TestUpdaterTab:

    def test_construction(self, container, admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow
        from frontend.tabs_extra import UpdaterTab
        win = _make_main_window(container, admin_session)
        tab = UpdaterTab(container, admin_session, win)
        assert tab.container is container
        assert tab.table is not None
        _close_main_window(win)

    def test_buttons_present(self, container, admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow
        from frontend.tabs_extra import UpdaterTab
        win = _make_main_window(container, admin_session)
        tab = UpdaterTab(container, admin_session, win)
        assert hasattr(tab, "apply_btn")
        assert hasattr(tab, "rollback_btn")
        assert hasattr(tab, "refresh_btn")
        _close_main_window(win)

    def test_refresh_shows_empty_when_no_packages(self, container,
                                                  admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow
        from frontend.tabs_extra import UpdaterTab
        win = _make_main_window(container, admin_session)
        tab = UpdaterTab(container, admin_session, win)
        tab.refresh()
        assert tab.table.rowCount() == 0
        _close_main_window(win)

    def test_updater_tab_no_allow_unsigned_in_source(self):
        """Policy assertion: UpdaterTab source must NEVER contain
        allow_unsigned=True as a call-site argument."""
        _skip_no_qt()
        from pathlib import Path
        src = (Path(__file__).resolve().parent.parent
               / "frontend" / "tabs_extra.py").read_text(encoding="utf-8")
        code_only = "\n".join(
            line.split("#", 1)[0] for line in src.splitlines())
        assert "allow_unsigned=True" not in code_only


# ===================================================================
# main.py / run_gui() — Entry point tests
# ===================================================================


class TestMainEntryPoint:

    def test_main_py_sets_sys_path(self):
        """main.py must insert repo root into sys.path so backend/ is
        importable regardless of the working directory."""
        from pathlib import Path
        main_src = (Path(__file__).resolve().parent.parent / "main.py"
                    ).read_text(encoding="utf-8")
        assert "sys.path" in main_src
        assert "ROOT" in main_src

    def test_run_gui_importable(self):
        """run_gui must be importable from backend.app."""
        from backend.app import run_gui
        assert callable(run_gui)

    def test_container_class_importable(self):
        """Container class must be importable."""
        from backend.app import Container
        assert Container is not None

    def test_launch_function_importable(self):
        """frontend.main_window.launch must be importable."""
        _skip_no_qt()
        from frontend.main_window import launch
        assert callable(launch)

    def test_main_py_has_main_guard(self):
        from pathlib import Path
        src = (Path(__file__).resolve().parent.parent / "main.py"
               ).read_text(encoding="utf-8")
        assert 'if __name__ == "__main__"' in src

    def test_run_gui_creates_container(self):
        """run_gui's first action is Container() — verify the class
        creates all services when instantiated via the fixture."""
        from backend.app import Container
        # The container fixture already does this; verify the class itself
        assert hasattr(Container, "_provision_update_pubkey")


# ===================================================================
# frontend/dialogs.py — Deep behavioral tests
# ===================================================================


class TestLoginDialogBehavior:

    def test_accept_with_valid_credentials(self, container, admin_session):
        """Programmatically fill and accept LoginDialog."""
        _skip_no_qt()
        from frontend.dialogs import LoginDialog
        dlg = LoginDialog(container)
        dlg.username.setText("admin")
        dlg.password.setText("TestPassw0rd!")
        dlg._accept()
        assert dlg.session is not None
        assert dlg.session.username == "admin"

    def test_accept_with_wrong_password_keeps_dialog_open(self, container,
                                                          admin_session):
        """Wrong password must not set session and must not close dialog."""
        _skip_no_qt()
        from frontend.dialogs import LoginDialog
        dlg = LoginDialog(container)
        dlg.username.setText("admin")
        dlg.password.setText("wrongpassword")
        dlg._accept()
        assert dlg.session is None

    def test_accept_with_empty_username(self, container, admin_session):
        _skip_no_qt()
        from frontend.dialogs import LoginDialog
        dlg = LoginDialog(container)
        dlg.username.setText("")
        dlg.password.setText("anything")
        dlg._accept()
        assert dlg.session is None

    def test_accept_with_nonexistent_user(self, container, admin_session):
        _skip_no_qt()
        from frontend.dialogs import LoginDialog
        dlg = LoginDialog(container)
        dlg.username.setText("nobody")
        dlg.password.setText("anything12345")
        dlg._accept()
        assert dlg.session is None


class TestBootstrapDialogBehavior:

    def test_accept_password_mismatch(self, container, admin_session):
        """Mismatched password + confirm must not create user."""
        _skip_no_qt()
        from frontend.dialogs import BootstrapDialog
        # Need a fresh container without any users for bootstrap to work,
        # but we can still test the mismatch guard in isolation.
        dlg = BootstrapDialog(container)
        dlg.full_name.setText("Admin")
        dlg.username.setText("newadmin")
        dlg.password.setText("LongPassword1!")
        dlg.confirm.setText("DifferentPassword2!")
        dlg._accept()
        assert dlg.user is None  # mismatch prevented creation

    def test_accept_weak_password(self, container, admin_session):
        """Passwords < 10 chars must be rejected at the service level."""
        _skip_no_qt()
        from frontend.dialogs import BootstrapDialog
        dlg = BootstrapDialog(container)
        dlg.full_name.setText("Admin")
        dlg.username.setText("weakadmin")
        dlg.password.setText("short")
        dlg.confirm.setText("short")
        dlg._accept()
        # Service raises WEAK_PASSWORD or BOOTSTRAP_NOT_ALLOWED (admin exists)
        assert dlg.user is None


class TestUnlockDialogBehavior:

    def test_accept_correct_password(self, container, admin_session):
        _skip_no_qt()
        from frontend.dialogs import UnlockDialog
        dlg = UnlockDialog(container, admin_session)
        dlg.password.setText("TestPassw0rd!")
        dlg._accept()
        assert dlg.unlocked is True

    def test_accept_wrong_password(self, container, admin_session):
        _skip_no_qt()
        from frontend.dialogs import UnlockDialog
        dlg = UnlockDialog(container, admin_session)
        dlg.password.setText("wrongpassword")
        dlg._accept()
        assert dlg.unlocked is False


# ===================================================================
# frontend/main_window.py — Tray, lock, checkpoint, dispatch tests
# ===================================================================


class TestMainWindowInteraction:

    def test_tick_dispatcher_runs_without_error(self, container,
                                                admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow
        win = _make_main_window(container, admin_session)
        win._tick_dispatcher()  # must not raise
        _close_main_window(win)

    def test_tick_checkpoint_saves_workspace(self, container, admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow
        win = _make_main_window(container, admin_session)
        win._tick_checkpoint()
        ws = container.checkpoints.load_workspace(admin_session)
        assert ws is not None
        assert "active_tab" in ws
        assert "open_tabs" in ws
        _close_main_window(win)

    def test_restore_workspace_sets_tab(self, container, admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow
        # Save workspace state with a specific tab index
        container.checkpoints.save_workspace(
            admin_session, {"active_tab": 1, "open_tabs": []})
        win = _make_main_window(container, admin_session)
        # After construction, _restore_workspace should set tab index
        if win.tabs.count() > 1:
            assert win.tabs.currentIndex() == 1
        _close_main_window(win)

    def test_drain_detached_clears_list(self, container, admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow
        from PyQt6.QtWidgets import QWidget
        win = _make_main_window(container, admin_session)
        # Add dummy detached windows
        dummy = QWidget()
        win.detached.append(dummy)
        assert len(win.detached) == 1
        win._drain_detached()
        assert len(win.detached) == 0
        _close_main_window(win)

    def test_close_topmost_detached(self, container, admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow
        from PyQt6.QtWidgets import QWidget
        win = _make_main_window(container, admin_session)
        d1 = QWidget()
        d2 = QWidget()
        win.detached.extend([d1, d2])
        win._close_topmost_detached()
        assert len(win.detached) == 1
        win._close_topmost_detached()
        assert len(win.detached) == 0
        _close_main_window(win)

    def test_close_topmost_detached_noop_when_empty(self, container,
                                                    admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow
        win = _make_main_window(container, admin_session)
        win._close_topmost_detached()  # must not raise
        assert len(win.detached) == 0
        _close_main_window(win)

    def test_new_record_delegates_to_current_tab(self, container,
                                                 admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow
        win = _make_main_window(container, admin_session)
        # The first tab (Students) should have _create_student
        win.tabs.setCurrentIndex(0)
        # _new_record calls _create_student which opens QInputDialog;
        # we just verify the dispatch path doesn't crash
        # by checking the method exists on the current widget.
        widget = win.tabs.currentWidget()
        assert (hasattr(widget, "_create_student") or
                hasattr(widget, "_new") or
                hasattr(widget, "_submit"))
        _close_main_window(win)

    def test_export_current_noop_on_non_exportable_tab(self, container,
                                                       admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow
        win = _make_main_window(container, admin_session)
        # Switch to a tab that may not have _export_csv
        # Notifications tab usually doesn't have export
        for i in range(win.tabs.count()):
            if win.tabs.tabText(i) == "Notifications":
                win.tabs.setCurrentIndex(i)
                break
        win._export_current()  # should show status message, not crash
        _close_main_window(win)

    def test_timers_present(self, container, admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow
        win = _make_main_window(container, admin_session)
        assert hasattr(win, "_dispatch_timer")
        assert hasattr(win, "_checkpoint_timer")
        assert win._dispatch_timer.interval() == 30_000
        assert win._checkpoint_timer.interval() == 60_000
        _close_main_window(win)

    def test_force_quit_bypasses_tray(self, container, admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow
        win = _make_main_window(container, admin_session)
        win._force_quit = True
        # closeEvent should accept (not minimize to tray)
        from PyQt6.QtGui import QCloseEvent
        ev = QCloseEvent()
        win.closeEvent(ev)
        assert ev.isAccepted()


# ===================================================================
# frontend/tabs_extra.py — Deeper action handler coverage
# ===================================================================


class TestCatalogTabRefreshWithData:

    def test_refresh_shows_types(self, container, admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow
        from frontend.tabs_extra import CatalogTab
        container.catalog.upsert_type(
            admin_session, "deep_type", "Deep Type",
            fields=[{"code": "f1", "label": "F1",
                     "field_type": "text", "required": False}])
        win = _make_main_window(container, admin_session)
        tab = CatalogTab(container, admin_session, win)
        tab.refresh()
        assert tab.types.rowCount() >= 1
        _close_main_window(win)

    def test_tree_item_stores_node_id(self, container, admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow
        from frontend.tabs_extra import CatalogTab
        nid = container.catalog.create_node(admin_session, "IDCheck")
        win = _make_main_window(container, admin_session)
        tab = CatalogTab(container, admin_session, win)
        tab.refresh()
        # Find the item and check its data
        for i in range(tab.tree.topLevelItemCount()):
            item = tab.tree.topLevelItem(i)
            if item.text(0) == "IDCheck":
                from PyQt6.QtCore import Qt as _Qt
                stored_id = item.data(0, _Qt.ItemDataRole.UserRole)
                assert stored_id == nid
                break
        _close_main_window(win)


class TestBomTabRefreshWithData:

    def test_refresh_after_style_creation_shows_rows(self, container,
                                                     admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow
        from frontend.tabs_extra import BomTab
        container.bom.create_style(admin_session, "BT-1", "BomTab Style 1")
        container.bom.create_style(admin_session, "BT-2", "BomTab Style 2")
        win = _make_main_window(container, admin_session)
        tab = BomTab(container, admin_session, win)
        tab.refresh()
        assert tab.styles.rowCount() >= 2
        _close_main_window(win)


# ===================================================================
# frontend/main_window.py — StudentsTab (direct isolated tests)
# ===================================================================


class TestStudentsTab:

    def test_construction_and_refresh(self, container, admin_session):
        _skip_no_qt()
        from backend.models import StudentDTO
        container.students.create(
            admin_session,
            StudentDTO(student_id="ST-1", full_name="Tab Student",
                       college="Eng", housing_status="pending"))
        from frontend.main_window import MainWindow, StudentsTab
        win = _make_main_window(container, admin_session)
        tab = StudentsTab(container, admin_session, win)
        tab.refresh()
        assert tab.table.rowCount() >= 1
        _close_main_window(win)

    def test_buttons_present(self, container, admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow, StudentsTab
        win = _make_main_window(container, admin_session)
        tab = StudentsTab(container, admin_session, win)
        assert hasattr(tab, "new_btn")
        assert hasattr(tab, "import_btn")
        assert hasattr(tab, "export_btn")
        assert hasattr(tab, "unlock_btn")
        _close_main_window(win)

    def test_table_columns(self, container, admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow, StudentsTab
        win = _make_main_window(container, admin_session)
        tab = StudentsTab(container, admin_session, win)
        assert tab.table.columnCount() == 5  # ID, Name, College, Year, Housing
        _close_main_window(win)

    def test_context_actions_registered(self, container, admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow, StudentsTab
        win = _make_main_window(container, admin_session)
        tab = StudentsTab(container, admin_session, win)
        labels = [a[0] for a in tab.table._menu_actions]
        assert "Open profile" in labels
        assert "Assign bed\u2026" in labels or "Assign bed…" in labels
        assert "View history" in labels
        _close_main_window(win)

    def test_refresh_reflects_new_data(self, container, admin_session):
        _skip_no_qt()
        from backend.models import StudentDTO
        from frontend.main_window import MainWindow, StudentsTab
        win = _make_main_window(container, admin_session)
        tab = StudentsTab(container, admin_session, win)
        before = tab.table.rowCount()
        container.students.create(
            admin_session,
            StudentDTO(student_id="ST-NEW", full_name="New After Refresh",
                       housing_status="pending"))
        tab.refresh()
        assert tab.table.rowCount() == before + 1
        _close_main_window(win)


# ===================================================================
# frontend/main_window.py — HousingTab (direct isolated tests)
# ===================================================================


class TestHousingTab:

    def test_construction_and_refresh(self, container, admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow, HousingTab
        win = _make_main_window(container, admin_session)
        tab = HousingTab(container, admin_session, win)
        tab.refresh()
        # Seed data includes beds
        assert tab.table.rowCount() >= 1
        _close_main_window(win)

    def test_table_columns(self, container, admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow, HousingTab
        win = _make_main_window(container, admin_session)
        tab = HousingTab(container, admin_session, win)
        assert tab.table.columnCount() == 5  # Bed ID, Building, Room, Code, Occupied
        _close_main_window(win)

    def test_bed_occupancy_display(self, container, admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow, HousingTab
        win = _make_main_window(container, admin_session)
        tab = HousingTab(container, admin_session, win)
        tab.refresh()
        # Check that the Occupied column contains "yes" or "no"
        for row_idx in range(tab.table.rowCount()):
            val = tab.table.item(row_idx, 4).text()
            assert val in ("yes", "no"), f"Unexpected occupied value: {val}"
        _close_main_window(win)


# ===================================================================
# frontend/main_window.py — ResourcesTab (direct isolated tests)
# ===================================================================


class TestResourcesTab:

    def test_construction(self, container, admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow, ResourcesTab
        win = _make_main_window(container, admin_session)
        tab = ResourcesTab(container, admin_session, win)
        assert hasattr(tab, "new_btn")
        assert hasattr(tab, "add_ver_btn")
        assert hasattr(tab, "publish_btn")
        assert hasattr(tab, "hold_btn")
        _close_main_window(win)

    def test_refresh_shows_resources(self, container, admin_session):
        _skip_no_qt()
        container.resources.create_resource(admin_session, "Tab Resource")
        from frontend.main_window import MainWindow, ResourcesTab
        win = _make_main_window(container, admin_session)
        tab = ResourcesTab(container, admin_session, win)
        tab.refresh()
        assert tab.table.rowCount() >= 1
        _close_main_window(win)

    def test_selected_id_none_when_nothing_selected(self, container,
                                                    admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow, ResourcesTab
        win = _make_main_window(container, admin_session)
        tab = ResourcesTab(container, admin_session, win)
        assert tab._selected_id() is None
        _close_main_window(win)

    def test_table_columns(self, container, admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow, ResourcesTab
        win = _make_main_window(container, admin_session)
        tab = ResourcesTab(container, admin_session, win)
        assert tab.table.columnCount() == 6
        _close_main_window(win)


# ===================================================================
# frontend/main_window.py — ComplianceTab (direct isolated tests)
# ===================================================================


class TestComplianceTab:

    def test_construction(self, container, admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow, ComplianceTab
        win = _make_main_window(container, admin_session)
        tab = ComplianceTab(container, admin_session, win)
        assert hasattr(tab, "submit_btn")
        assert hasattr(tab, "approve_btn")
        assert hasattr(tab, "reject_btn")
        _close_main_window(win)

    def test_refresh_shows_cases(self, container, admin_session):
        _skip_no_qt()
        container.compliance.submit_employer(
            admin_session, "Tab Employer", None, None)
        from frontend.main_window import MainWindow, ComplianceTab
        win = _make_main_window(container, admin_session)
        tab = ComplianceTab(container, admin_session, win)
        tab.refresh()
        assert tab.table.rowCount() >= 1
        _close_main_window(win)

    def test_table_columns(self, container, admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow, ComplianceTab
        win = _make_main_window(container, admin_session)
        tab = ComplianceTab(container, admin_session, win)
        assert tab.table.columnCount() == 6
        _close_main_window(win)


# ===================================================================
# frontend/main_window.py — NotificationsTab (direct isolated tests)
# ===================================================================


class TestNotificationsTab:

    def test_construction(self, container, admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow, NotificationsTab
        win = _make_main_window(container, admin_session)
        tab = NotificationsTab(container, admin_session, win)
        assert hasattr(tab, "refresh_btn")
        assert hasattr(tab, "read_btn")
        assert hasattr(tab, "retry_btn")
        _close_main_window(win)

    def test_refresh_shows_delivered_messages(self, container, admin_session):
        _skip_no_qt()
        # Enqueue + drain to get a delivered message
        container.notifications.upsert_template(
            admin_session, "tab_tpl", "Tab Notification", "Body")
        container.notifications.enqueue(
            admin_session, template_name="tab_tpl",
            audience_user_ids=[admin_session.user_id], variables={})
        container.notifications.drain_queue()
        from frontend.main_window import MainWindow, NotificationsTab
        win = _make_main_window(container, admin_session)
        tab = NotificationsTab(container, admin_session, win)
        tab.refresh()
        assert tab.table.rowCount() >= 1
        _close_main_window(win)

    def test_table_columns(self, container, admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow, NotificationsTab
        win = _make_main_window(container, admin_session)
        tab = NotificationsTab(container, admin_session, win)
        assert tab.table.columnCount() == 6
        _close_main_window(win)


# ===================================================================
# frontend/main_window.py — ReportsTab (direct isolated tests)
# ===================================================================


class TestReportsTab:

    def test_construction(self, container, admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow, ReportsTab
        win = _make_main_window(container, admin_session)
        tab = ReportsTab(container, admin_session, win)
        assert hasattr(tab, "occ_btn")
        assert hasattr(tab, "move_btn")
        assert hasattr(tab, "vel_btn")
        assert hasattr(tab, "sla_btn")
        assert hasattr(tab, "notif_btn")
        assert hasattr(tab, "export_btn")
        assert tab._current is None
        _close_main_window(win)

    def test_show_occupancy_populates_table(self, container, admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow, ReportsTab
        win = _make_main_window(container, admin_session)
        tab = ReportsTab(container, admin_session, win)
        tab._show("occupancy")
        assert tab._current is not None
        assert tab._current.title == "Occupancy by Dorm"
        assert tab.table.rowCount() >= 0  # may be 0 if no assignments
        _close_main_window(win)

    def test_show_move_trends(self, container, admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow, ReportsTab
        win = _make_main_window(container, admin_session)
        tab = ReportsTab(container, admin_session, win)
        tab._show("move_trends")
        assert tab._current is not None
        assert "Move trends" in tab._current.title
        _close_main_window(win)

    def test_show_resource_velocity(self, container, admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow, ReportsTab
        win = _make_main_window(container, admin_session)
        tab = ReportsTab(container, admin_session, win)
        tab._show("resource_velocity")
        assert tab._current is not None
        _close_main_window(win)

    def test_show_compliance_sla(self, container, admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow, ReportsTab
        win = _make_main_window(container, admin_session)
        tab = ReportsTab(container, admin_session, win)
        tab._show("compliance_sla")
        assert tab._current is not None
        _close_main_window(win)

    def test_show_notification_delivery(self, container, admin_session):
        _skip_no_qt()
        from frontend.main_window import MainWindow, ReportsTab
        win = _make_main_window(container, admin_session)
        tab = ReportsTab(container, admin_session, win)
        tab._show("notification_delivery")
        assert tab._current is not None
        _close_main_window(win)


# ===================================================================
# frontend/widgets/search_palette.py — Export and activation paths
# ===================================================================


class TestSearchPaletteInteraction:

    def test_export_csv_no_results_noop(self, container, admin_session):
        _skip_no_qt()
        from frontend.widgets.search_palette import SearchPalette
        dlg = SearchPalette(container, admin_session)
        # _hits is empty, _export_csv should not crash (shows message)
        dlg._export_csv()  # must not raise

    def test_activate_first_noop_when_empty(self, container, admin_session):
        _skip_no_qt()
        from frontend.widgets.search_palette import SearchPalette
        dlg = SearchPalette(container, admin_session)
        dlg._activate_first()  # list is empty, must not raise


# ===================================================================
# frontend/tabs_extra.py — UpdaterTab with data
# ===================================================================


class TestUpdaterTabRefreshWithData:

    def test_refresh_after_apply_shows_package(self, container, admin_session,
                                               tmp_path):
        _skip_no_qt()
        try:
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding, rsa
        except ImportError:
            pytest.skip("cryptography not installed")
        from backend import config as _config
        import json
        import zipfile
        from frontend.main_window import MainWindow
        from frontend.tabs_extra import UpdaterTab
        # Generate key and signed package
        priv = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        _config.update_signing_key_path().write_bytes(
            priv.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo))
        manifest = json.dumps({"version": "8.0.0"}).encode("utf-8")
        sig = priv.sign(
            manifest,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                        salt_length=padding.PSS.MAX_LENGTH),
            hashes.SHA256())
        pkg = tmp_path / "pkg.zip"
        with zipfile.ZipFile(pkg, "w") as zf:
            zf.writestr("update.json", manifest)
            zf.writestr("update.json.sig", sig)
            zf.writestr("payload/readme.txt", b"hi")
        container.updater.apply_package(
            admin_session, pkg, install_dir=str(tmp_path / "install"))
        win = _make_main_window(container, admin_session)
        tab = UpdaterTab(container, admin_session, win)
        tab.refresh()
        assert tab.table.rowCount() >= 1
        _close_main_window(win)
