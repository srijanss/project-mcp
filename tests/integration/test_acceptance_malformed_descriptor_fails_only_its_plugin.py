import sys
import textwrap

import pytest

from project_mcp.plugins.registry import builtin_registry
from project_mcp.tools.symbols import find_symbol

BAD_FRAMEWORK = textwrap.dedent(
    '''
    from project_mcp.plugins.descriptor import PluginDescriptor


    DESCRIPTOR = PluginDescriptor(
        name="bad_framework",
        version="0.1.0",
        api_version=1,
        extensions={},
        kind="framework",
        requires=("python",),
        analyzer="bad_framework:Framework",
        migration_kinds=None,
    )
    '''
)


@pytest.fixture
def bad_framework_installed(tmp_path, monkeypatch):
    site = tmp_path / "site"
    dist_info = site / "bad_framework-0.1.0.dist-info"
    dist_info.mkdir(parents=True)
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: bad-framework\nVersion: 0.1.0\n"
    )
    (dist_info / "entry_points.txt").write_text(
        "[project_mcp.plugins]\nbad_framework = bad_framework:DESCRIPTOR\n"
    )
    (site / "bad_framework.py").write_text(BAD_FRAMEWORK)
    monkeypatch.syspath_prepend(str(site))
    yield
    sys.modules.pop("bad_framework", None)


def test_a_malformed_descriptor_is_failed_and_symbol_search_still_works(
    tmp_path, bad_framework_installed
):
    project = tmp_path / "project"
    project.mkdir()
    (project / "things.py").write_text("class Thing:\n    pass\n")

    results = find_symbol(project, "thing", kind="class")

    assert [r["name"] for r in results] == ["Thing"]
    assert "migration_kinds" in builtin_registry().failed_plugins["bad_framework"]
