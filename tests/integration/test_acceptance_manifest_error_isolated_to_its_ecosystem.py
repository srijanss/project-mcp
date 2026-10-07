from project_mcp.tools.dependencies import get_dependency_version, list_dependencies


def test_a_broken_manifest_fails_only_its_own_ecosystem(tmp_path):
    (tmp_path / "requirements.txt").write_text("requests==2.31.0\n")
    (tmp_path / "package.json").write_text("{broken")

    assert list_dependencies(tmp_path) == [
        {
            "name": "requests",
            "ecosystem": "python",
            "version": "2.31.0",
            "version_status": "declared",
        },
        {"ecosystem": "npm", "error": "invalid package.json"},
    ]
    assert get_dependency_version(tmp_path, "requests")["version"] == "2.31.0"


def test_a_scan_indexes_the_other_ecosystems_and_warns_about_a_broken_manifest(tmp_path):
    from project_mcp.db import get_connection
    from project_mcp.tools.project import get_project_overview

    (tmp_path / "requirements.txt").write_text("requests==2.31.0\n")
    (tmp_path / "package.json").write_text("{broken")

    overview = get_project_overview(tmp_path)

    assert overview["index_status"]["warnings"] == [
        "npm dependencies not indexed: invalid package.json"
    ]
    indexed = get_connection(tmp_path).execute("SELECT name FROM dependencies")
    assert [name for (name,) in indexed] == ["requests"]
