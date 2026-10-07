from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import refresh_index, run_scan
from project_mcp.plugins.analysis import FileAnalysis
from project_mcp.plugins.descriptor import PluginDescriptor
from project_mcp.plugins.registry import PluginRegistry

CONTEXTS = []


class _ContextKeeper:
    """A two-dialect toy plugin whose hooks keep the context they get."""

    def is_test_file(self, path):
        return False

    def analyze(self, path, source):
        return FileAnalysis(extra=source.upper())

    def resolve_import(self, importer, spec):
        return []

    def link_cross_file(self, context):
        CONTEXTS.append(context)


def _registry():
    registry = PluginRegistry()
    registry.register(
        PluginDescriptor(
            name="toy",
            version="0.1.0",
            api_version=1,
            extensions={".toy": "toy", ".toyx": "toyx"},
            analyzer=f"{__name__}:_ContextKeeper",
        )
    )
    return registry


def test_link_context_carries_each_changed_files_id_source_and_analysis(tmp_path):
    (tmp_path / "a.toy").write_text("a\n")
    (tmp_path / "b.toyx").write_text("b\n")
    (tmp_path / ".project-mcp").mkdir()
    (tmp_path / ".project-mcp" / "config.toml").write_text('source_roots = ["src"]\n')
    conn = get_connection(tmp_path)
    config = load_config(tmp_path)
    registry = _registry()
    run_scan(conn, tmp_path, config, registry=registry)
    CONTEXTS.clear()

    (tmp_path / "a.toy").write_text("a changed\n")
    refresh_index(conn, tmp_path, config, registry=registry)

    (context,) = CONTEXTS
    file_ids = dict(conn.execute("SELECT path, id FROM files"))
    changed = context.changed["a.toy"]
    assert (changed.file_id, changed.source, changed.analysis.extra) == (
        file_ids["a.toy"],
        "a changed\n",
        "A CHANGED\n",
    )
    assert context.conn is conn
    assert context.project_root == tmp_path
    assert context.source_roots == config.source_roots
    assert context.path_to_file_id == file_ids
    assert sorted(context.plugin_paths) == ["a.toy", "b.toyx"]


HOOK_ORDER = []


class _OrderRecorder:
    def is_test_file(self, path):
        return False

    def analyze(self, path, source):
        return FileAnalysis()

    def resolve_import(self, importer, spec):
        return []

    def link_cross_file(self, context):
        HOOK_ORDER.append(("cross_file", sorted(context.changed)))

    def link_test_evidence(self, context):
        HOOK_ORDER.append(("test_evidence", sorted(context.changed)))


def test_every_plugins_cross_file_links_run_before_any_test_evidence(tmp_path):
    registry = PluginRegistry()
    for name in ("one", "two"):
        registry.register(
            PluginDescriptor(
                name=name,
                version="0.1.0",
                api_version=1,
                extensions={f".{name}": name},
                analyzer=f"{__name__}:_OrderRecorder",
            )
        )
    (tmp_path / "a.one").write_text("a\n")
    (tmp_path / "b.two").write_text("b\n")
    HOOK_ORDER.clear()

    run_scan(get_connection(tmp_path), tmp_path, load_config(tmp_path), registry=registry)

    assert sorted(HOOK_ORDER[:2]) == [("cross_file", ["a.one"]), ("cross_file", ["b.two"])]
    assert sorted(HOOK_ORDER[2:]) == [
        ("test_evidence", ["a.one"]),
        ("test_evidence", ["b.two"]),
    ]
