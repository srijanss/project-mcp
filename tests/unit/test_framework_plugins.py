from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import refresh_index, run_scan
from project_mcp.plugins.descriptor import PluginDescriptor
from project_mcp.plugins.python.descriptor import DESCRIPTOR as python
from project_mcp.plugins.registry import PluginRegistry

CALLS = []


class _ToyFramework:
    def detect(self, context):
        CALLS.append(("detect", sorted(context.changed_languages)))
        return (context.project_root / "toy.cfg").exists()

    def enrich(self, context):
        CALLS.append(("enrich", sorted(context.changed_languages)))
        assert context.conn.execute(
            "SELECT id FROM projects WHERE id = ?", (context.project_id,)
        ).fetchone()
        assert set(context.path_to_file_id) >= {"app.py"}


def _registry():
    registry = PluginRegistry()
    registry.register(python)
    registry.register(
        PluginDescriptor(
            name="toyframe",
            version="0.1.0",
            api_version=1,
            extensions={},
            kind="framework",
            requires=("python",),
            analyzer=f"{__name__}:_ToyFramework",
        )
    )
    return registry


def test_frameworks_enrich_only_projects_they_detect(tmp_path):
    (tmp_path / "app.py").write_text("x = 1\n")
    conn = get_connection(tmp_path)
    config = load_config(tmp_path)
    registry = _registry()
    CALLS.clear()

    run_scan(conn, tmp_path, config, registry=registry)
    (tmp_path / "toy.cfg").write_text("on\n")
    refresh_index(conn, tmp_path, config, registry=registry)

    assert CALLS == [
        ("detect", ["python"]),
        ("detect", []),
        ("enrich", []),
    ]
