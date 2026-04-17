"""Auth service API tests."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from backend.models import StudentDTO
from backend.services.auth import BizError
from backend.permissions import PermissionDenied, Session


# ---------- bootstrap_admin ---------------------------------------------------

def test_bootstrap_admin_creates_user(container):
    user = container.auth.bootstrap_admin("newadmin", "SecurePass1!", "New Admin")
    assert user.id > 0
    assert user.username == "newadmin"
    assert user.full_name == "New Admin"
    assert "system_admin" in user.roles


def test_bootstrap_admin_twice_fails(container):
    container.auth.bootstrap_admin("first", "SecurePass1!", "First")
    with pytest.raises(BizError) as exc_info:
        container.auth.bootstrap_admin("second", "SecurePass1!", "Second")
    assert exc_info.value.code == "BOOTSTRAP_NOT_ALLOWED"


def test_bootstrap_weak_password(container):
    with pytest.raises(BizError) as exc_info:
        container.auth.bootstrap_admin("admin", "short", "Admin")
    assert exc_info.value.code == "WEAK_PASSWORD"


# ---------- login -------------------------------------------------------------

def test_login_success(container):
    container.auth.bootstrap_admin("admin", "TestPassw0rd!", "Admin")
    session = container.auth.login("admin", "TestPassw0rd!")
    assert isinstance(session, Session)
    assert session.user_id > 0
    assert session.username == "admin"
    assert "system_admin" in session.roles
    assert len(session.permissions) > 0


def test_login_wrong_password(container):
    container.auth.bootstrap_admin("admin", "TestPassw0rd!", "Admin")
    with pytest.raises(BizError) as exc_info:
        container.auth.login("admin", "WrongPassword!")
    assert exc_info.value.code == "AUTH_INVALID"


def test_login_wrong_username(container):
    container.auth.bootstrap_admin("admin", "TestPassw0rd!", "Admin")
    with pytest.raises(BizError) as exc_info:
        container.auth.login("noone", "TestPassw0rd!")
    assert exc_info.value.code == "AUTH_INVALID"


# ---------- logout ------------------------------------------------------------

def test_logout_clears_mask(container, admin_session):
    # First unlock so mask_unlock_until is set
    container.auth.unlock_masked_fields(admin_session, "TestPassw0rd!")
    assert admin_session.mask_unlock_until is not None
    # Now logout
    container.auth.logout(admin_session)
    assert admin_session.mask_unlock_until is None


# ---------- unlock_masked_fields ----------------------------------------------

def test_unlock_masked_fields(container, admin_session):
    result = container.auth.unlock_masked_fields(admin_session, "TestPassw0rd!")
    assert isinstance(result, datetime)
    assert result > datetime.utcnow()
    assert admin_session.mask_unlock_until == result


def test_unlock_masked_fields_wrong_password(container, admin_session):
    with pytest.raises(BizError) as exc_info:
        container.auth.unlock_masked_fields(admin_session, "WrongPassword!")
    assert exc_info.value.code == "AUTH_INVALID"


# ---------- change_password ---------------------------------------------------

def test_change_password_success(container, admin_session):
    container.auth.change_password(admin_session, "TestPassw0rd!", "NewSecurePass1!")
    # Login with new password should work
    session = container.auth.login("admin", "NewSecurePass1!")
    assert session.username == "admin"


def test_change_password_wrong_old(container, admin_session):
    with pytest.raises(BizError) as exc_info:
        container.auth.change_password(admin_session, "WrongOldPass!", "NewSecurePass1!")
    assert exc_info.value.code == "AUTH_INVALID"


def test_change_password_weak_new(container, admin_session):
    with pytest.raises(BizError) as exc_info:
        container.auth.change_password(admin_session, "TestPassw0rd!", "short")
    assert exc_info.value.code == "WEAK_PASSWORD"


# ---------- session fixture properties ----------------------------------------

def test_admin_session_has_system_admin_role(admin_session):
    assert "system_admin" in admin_session.roles


def test_admin_session_has_permissions(admin_session):
    assert isinstance(admin_session.permissions, set)
    assert len(admin_session.permissions) > 0
