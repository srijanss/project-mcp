from project_mcp.tools.dependencies import get_dependency_version


def test_an_absent_dependency_is_not_found_beside_a_broken_manifest(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project\nbroken")
    (tmp_path / "package.json").write_text('{"dependencies": {"left-pad": "1.3.0"}}')

    assert get_dependency_version(tmp_path, "absent") == {
        "status": "not_found",
        "manifest_errors": [{"ecosystem": "python", "error": "invalid pyproject.toml"}],
    }
    assert get_dependency_version(tmp_path, "left-pad")["version"] == "1.3.0"
