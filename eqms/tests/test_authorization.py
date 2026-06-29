"""Tests for the login allow-list (authorized users)."""

from __future__ import annotations

import pytest

from eqms.auth.ms_auth import LocalAuthProvider
from eqms.auth.session import SessionManager
from eqms.core.exceptions import PermissionDeniedError
from eqms.data.settings_store import SettingsStore


def test_seed_authorized_users(store):
    s = SettingsStore(store)
    s.ensure_seeded()
    users = s.get_authorized_users()
    assert "ivy.serata@concentrix.com" in users
    assert len(users) == 14
    # The admin is allowed but is NOT part of the allow-list itself.
    assert "sundeep.bhardwaj@concentrix.com" not in users


def test_is_login_allowed_rules(store):
    s = SettingsStore(store)
    s.ensure_seeded()
    assert s.is_login_allowed("ivy.serata@concentrix.com")
    assert s.is_login_allowed("IVY.SERATA@concentrix.com")          # case-insensitive
    assert s.is_login_allowed("sundeep.bhardwaj@concentrix.com")     # admin always
    assert not s.is_login_allowed("random.person@concentrix.com")    # not listed
    assert not s.is_login_allowed("")


def test_restrict_login_toggle_off_allows_anyone(store):
    s = SettingsStore(store)
    s.ensure_seeded()
    s.set("security.restrict_login", "false")
    assert s.is_login_allowed("random.person@concentrix.com")


def test_add_and_remove_user(store):
    s = SettingsStore(store)
    s.ensure_seeded()
    assert s.add_authorized_user("new.user@concentrix.com")
    assert s.is_login_allowed("new.user@concentrix.com")
    assert not s.add_authorized_user("new.user@concentrix.com")      # duplicate
    assert s.remove_authorized_user("new.user@concentrix.com")
    assert not s.is_login_allowed("new.user@concentrix.com")
    assert not s.remove_authorized_user("does.not.exist@concentrix.com")


def test_session_rejects_unauthorized_user(store):
    SettingsStore(store).ensure_seeded()
    sm = SessionManager(LocalAuthProvider("intruder@concentrix.com"))
    with pytest.raises(PermissionDeniedError):
        sm.sign_in()
    assert not sm.is_authenticated


def test_session_allows_listed_user_and_admin(store):
    SettingsStore(store).ensure_seeded()
    qa = SessionManager(LocalAuthProvider("ivy.serata@concentrix.com"))
    qa.sign_in()
    assert qa.is_authenticated and not qa.is_admin
    admin = SessionManager(LocalAuthProvider("sundeep.bhardwaj@concentrix.com"))
    admin.sign_in()
    assert admin.is_admin
