"""Tests for authentication, admin gating and update version comparison."""

from __future__ import annotations

import pytest

from eqms.auth.ms_auth import LocalAuthProvider, is_admin_email
from eqms.auth.session import SessionManager
from eqms.core.exceptions import PermissionDeniedError
from eqms.services.update_service import parse_version


def test_admin_email_match_is_case_insensitive():
    assert is_admin_email("SUNDEEP.BHARDWAJ@concentrix.com")
    assert not is_admin_email("someone.else@concentrix.com")


def test_qa_session_is_not_admin(store):
    from eqms.data.settings_store import SettingsStore

    SettingsStore(store).set("security.restrict_login", "false")  # not testing the allow-list here
    sm = SessionManager(LocalAuthProvider("qa@concentrix.com"))
    sm.sign_in()
    assert not sm.is_admin
    with pytest.raises(PermissionDeniedError):
        sm.require_admin()


def test_admin_session_passes_gate():
    sm = SessionManager(LocalAuthProvider("sundeep.bhardwaj@concentrix.com"))
    sm.sign_in()
    assert sm.is_admin
    sm.require_admin()  # must not raise
    assert sm.can_edit_audit("anyone@x.com")  # admin can edit any


def test_qa_can_edit_only_own(store):
    from eqms.data.settings_store import SettingsStore

    SettingsStore(store).set("security.restrict_login", "false")
    sm = SessionManager(LocalAuthProvider("qa@concentrix.com"))
    sm.sign_in()
    assert sm.can_edit_audit("qa@concentrix.com")
    assert not sm.can_edit_audit("other@concentrix.com")


@pytest.mark.parametrize("a,b,newer", [
    ("1.0.0", "1.0.1", True),
    ("1.2.0", "1.10.0", True),
    ("2.0.0", "1.9.9", False),
    ("1.0.0", "1.0.0", False),
])
def test_version_ordering(a, b, newer):
    assert (parse_version(b) > parse_version(a)) is newer
