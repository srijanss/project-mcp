from project_mcp.tools.symbols import find_symbol


def test_a_project_first_queried_while_empty_indexes_the_files_added_afterwards(tmp_path):
    assert find_symbol(tmp_path, "greet") == []

    (tmp_path / "app.py").write_text("def greet():\n    return 1\n")

    assert [s["qualified_name"] for s in find_symbol(tmp_path, "greet")] == ["app.greet"]
