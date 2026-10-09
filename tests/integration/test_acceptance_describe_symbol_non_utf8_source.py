from project_mcp.tools.symbol_details import describe_symbol


def test_describing_a_symbol_in_a_file_with_non_utf8_bytes_shows_its_source(tmp_path):
    (tmp_path / "legacy.py").write_bytes(b"# caf\xe9\ndef greet():\n    return 'caf\xe9'\n")

    description = describe_symbol(tmp_path, "legacy.greet")

    assert description["found"] is True
    assert description["source"] == "def greet():\n    return 'caf�'"
