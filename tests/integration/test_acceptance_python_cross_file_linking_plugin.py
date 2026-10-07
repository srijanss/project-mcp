from dataclasses import replace

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import refresh_index, run_scan
from project_mcp.plugins.analysis import FileAnalysis
from project_mcp.plugins.descriptor import PluginDescriptor
from project_mcp.plugins.python.analyzer import PythonAnalyzer
from project_mcp.plugins.python.descriptor import DESCRIPTOR
from project_mcp.plugins.registry import PluginRegistry
from tests.golden import copy_fixture

HOOK_CALLS = []


class _RecordingAnalyzer:
    def is_test_file(self, path):
        return False

    def analyze(self, path, source):
        return FileAnalysis()

    def resolve_import(self, importer, spec):
        return []

    def link_cross_file(self, context):
        HOOK_CALLS.append(("cross_file", sorted(context.changed), sorted(context.added)))

    def link_test_evidence(self, context):
        HOOK_CALLS.append(("test_evidence", sorted(context.changed), sorted(context.added)))


def test_link_hooks_receive_the_changed_files_of_their_plugin(tmp_path):
    registry = PluginRegistry()
    registry.register(
        PluginDescriptor(
            name="toy",
            version="0.1.0",
            api_version=1,
            extensions={".toy": "toy"},
            analyzer=f"{__name__}:_RecordingAnalyzer",
        )
    )
    (tmp_path / "a.toy").write_text("a\n")
    (tmp_path / "b.toy").write_text("b\n")
    conn = get_connection(tmp_path)
    config = load_config(tmp_path)
    HOOK_CALLS.clear()

    run_scan(conn, tmp_path, config, registry=registry)
    (tmp_path / "a.toy").write_text("a changed\n")
    refresh_index(conn, tmp_path, config, registry=registry)

    assert HOOK_CALLS == [
        ("cross_file", ["a.toy", "b.toy"], ["a.toy", "b.toy"]),
        ("test_evidence", ["a.toy", "b.toy"], ["a.toy", "b.toy"]),
        ("cross_file", ["a.toy"], []),
        ("test_evidence", ["a.toy"], []),
    ]


class _PythonWithoutLinking(PythonAnalyzer):
    link_cross_file = None
    link_test_evidence = None


def test_python_cross_file_edges_and_tests_come_only_from_the_plugin_hooks(tmp_path):
    project_root = copy_fixture("python", tmp_path)
    registry = PluginRegistry()
    registry.register(
        replace(DESCRIPTOR, analyzer=f"{__name__}:_PythonWithoutLinking")
    )
    conn = get_connection(project_root)

    run_scan(conn, project_root, load_config(project_root), registry=registry)

    assert conn.execute("SELECT COUNT(*) FROM tests").fetchone()[0] == 0
    assert conn.execute(
        """
        SELECT COUNT(*) FROM relationships r
        LEFT JOIN symbols source ON r.source_entity_type = 'symbol'
            AND source.id = r.source_entity_id
        LEFT JOIN symbols target ON r.target_entity_type = 'symbol'
            AND target.id = r.target_entity_id
        WHERE r.relationship_type != 'imports'
          AND (source.file_id IS NULL OR target.file_id IS NULL
               OR source.file_id != target.file_id)
        """
    ).fetchone()[0] == 0
