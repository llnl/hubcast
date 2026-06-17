from unittest.mock import Mock, patch

import ldap
import pytest

from hubcast.account_map.file import FileMap, FileMapError
from hubcast.account_map.ldap import LDAPMap
from hubcast.exceptions import HubcastError

### FIXTURES


@pytest.fixture
def ldap_map():
    """Generic LDAPMap fixture."""
    return LDAPMap(
        uri="ldap://test.example.com",
        search_base="ou=users,dc=test,dc=com",
        input_attr="githubId",
        output_attr="uid",
        search_scope=ldap.SCOPE_SUBTREE,
        bind_dn="cn=admin,dc=test,dc=com",
        bind_password="password",
    )


### TESTS


# file mapper tests
def test_file_map():
    account_map = FileMap("tests/data/file_map.yml")
    assert account_map("alice") == "alice_123"
    assert account_map("bob") == "bob_456"
    assert account_map("charlie") is None


def test_file_map_no_file():
    file_path = "tests/data/non_existent_file.yml"
    try:
        FileMap(file_path)
    except FileMapError as e:
        assert str(e) == f"File map not found. path={file_path}"


def test_file_map_invalid_yaml():
    file_path = "tests/data/invalid_yaml.yml"
    try:
        FileMap(file_path)
    except FileMapError as e:
        assert str(e) == f"Failed to parse file map. path={file_path}"


def test_file_map_missing_users_key():
    file_path = "tests/data/no_users.yml"
    try:
        FileMap(file_path)
    except FileMapError as e:
        assert str(e) == f"File map missing Users section. path={file_path}"


# ldap mapper tests


def test_ldap_map_match(ldap_map):
    """If LDAP returns a matching entry, should return the mapped value."""

    with patch("ldap.initialize") as mock_init:
        mock_conn = Mock()
        mock_init.return_value = mock_conn
        mock_conn.search_s.return_value = [("dn", {"uid": [b"caetano_gitlab"]})]
        mock_conn.unbind_s.return_value = None

        result = ldap_map("caetano_github")
        assert result == "caetano_gitlab"


def test_ldap_map_no_match(ldap_map):
    """If LDAP returns no matching entry, should return None."""

    with patch("ldap.initialize") as mock_init:
        mock_conn = Mock()
        mock_init.return_value = mock_conn
        mock_conn.search_s.return_value = []
        mock_conn.unbind_s.return_value = None

        result = ldap_map("caetano_github")
        assert result is None


@pytest.mark.parametrize(
    "attrs",
    [
        {"other_attr": [b"value"]},  # uid attribute missing
        {"uid": []},  # uid attribute empty
    ],
)
def test_ldap_map_attrib_missing(ldap_map, attrs):
    """Should return None when attribute is missing or empty."""

    with patch("ldap.initialize") as mock_init:
        mock_conn = Mock()
        mock_init.return_value = mock_conn
        mock_conn.search_s.return_value = [("dn", attrs)]

        result = ldap_map("alice")

        assert result is None


def test_ldap_map_exception(ldap_map):
    """If LDAP raises an exception, should raise HubcastError."""

    with patch("ldap.initialize") as mock_init:
        mock_conn = Mock()
        mock_init.return_value = mock_conn
        mock_conn.search_s.side_effect = ldap.LDAPError("something bad")
        mock_conn.unbind_s.return_value = None

        with pytest.raises(HubcastError, match="LDAP query failed"):
            ldap_map("caetano_github")


def test_ldap_map_unbind_failure(ldap_map):
    """Should handle unbind failure gracefully."""

    with patch("ldap.initialize") as mock_init:
        mock_conn = Mock()
        mock_init.return_value = mock_conn
        mock_conn.search_s.return_value = [("dn", {"uid": [b"caetano_gitlab"]})]
        mock_conn.unbind_s.side_effect = ldap.LDAPError("unbind failed")

        result = ldap_map("caetano_github")
        assert result == "caetano_gitlab"
