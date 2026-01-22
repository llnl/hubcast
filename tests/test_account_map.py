from hubcast.account_map.file import FileMap, FileMapError


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
        assert (
            str(e)
            == f"Failed to parse file map. 'Users' key not found. path={file_path}"
        )
