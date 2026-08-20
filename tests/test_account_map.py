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


@pytest.fixture
def mock_conn():
    """Mock LDAP connection returned by a patched ldap.initialize."""
    with patch("ldap.initialize") as mock_init:
        conn = Mock()
        mock_init.return_value = conn
        yield conn


### TESTS


# file mapper tests
@pytest.mark.asyncio
async def test_file_map():
    account_map = FileMap("tests/data/file_map.yml")
    assert await account_map("alice") == "alice_123"
    assert await account_map("bob") == "bob_456"
    assert await account_map("charlie") is None


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


@pytest.mark.asyncio
async def test_ldap_map_match(ldap_map, mock_conn):
    """If LDAP returns a matching entry, should return the mapped value."""

    mock_conn.search_s.return_value = [("dn", {"uid": [b"caetano_gitlab"]})]

    result = await ldap_map("caetano_github")
    assert result == "caetano_gitlab"


@pytest.mark.asyncio
async def test_ldap_map_no_match(ldap_map, mock_conn):
    """If LDAP returns no matching entry, should return None."""

    mock_conn.search_s.return_value = []

    result = await ldap_map("caetano_github")
    assert result is None


@pytest.mark.parametrize(
    "attrs",
    [
        {"other_attr": [b"value"]},  # uid attribute missing
        {"uid": []},  # uid attribute empty
    ],
)
@pytest.mark.asyncio
async def test_ldap_map_attrib_missing(ldap_map, mock_conn, attrs):
    """Should return None when attribute is missing or empty."""

    mock_conn.search_s.return_value = [("dn", attrs)]

    result = await ldap_map("alice")
    assert result is None


@pytest.mark.asyncio
async def test_ldap_map_exception(ldap_map, mock_conn):
    """If LDAP raises an exception, should raise HubcastError."""

    mock_conn.search_s.side_effect = ldap.LDAPError("something bad")

    with pytest.raises(HubcastError, match="LDAP query failed"):
        await ldap_map("caetano_github")


@pytest.mark.asyncio
async def test_ldap_map_unbind_failure(ldap_map, mock_conn):
    """Should handle unbind failure gracefully."""

    mock_conn.search_s.return_value = [("dn", {"uid": [b"caetano_gitlab"]})]
    mock_conn.unbind_s.side_effect = ldap.LDAPError("unbind failed")

    result = await ldap_map("caetano_github")
    assert result == "caetano_gitlab"
