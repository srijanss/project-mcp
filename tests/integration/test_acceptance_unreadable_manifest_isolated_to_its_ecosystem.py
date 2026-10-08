import os

import pytest

from project_mcp.tools.dependencies import list_dependencies

pytestmark = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0, reason="root reads unreadable files"
)


def _project_with_unreadable_pyproject(root):
    (root / "package.json").write_text('{"dependencies": {"left-pad": "1.3.0"}}')
    pyproject = root / "pyproject.toml"
    pyproject.write_text('[project]\ndependencies = ["requests"]\n')
    pyproject.chmod(0)


def test_an_unreadable_manifest_fails_only_its_own_ecosystem(tmp_path):
    _project_with_unreadable_pyproject(tmp_path)

    assert list_dependencies(tmp_path) == [
        {
            "name": "left-pad",
            "ecosystem": "npm",
            "version": "1.3.0",
            "version_status": "declared",
        },
        {"ecosystem": "python", "error": "unreadable pyproject.toml"},
    ]


def test_a_scan_indexes_the_other_ecosystems_and_warns_about_an_unreadable_manifest(tmp_path):
    from project_mcp.db import get_connection
    from project_mcp.tools.project import get_project_overview

    _project_with_unreadable_pyproject(tmp_path)

    overview = get_project_overview(tmp_path)

    assert overview["index_status"]["warnings"] == [
        "python dependencies not indexed: unreadable pyproject.toml"
    ]
    indexed = get_connection(tmp_path).execute("SELECT name FROM dependencies")
    assert [name for (name,) in indexed] == ["left-pad"]
