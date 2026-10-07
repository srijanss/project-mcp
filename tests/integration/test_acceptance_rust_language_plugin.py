from pathlib import Path

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import refresh_index, run_scan
from project_mcp.plugins.analysis import FileAnalysis
from project_mcp.plugins.descriptor import PluginDescriptor
from project_mcp.plugins.registry import builtin_registry
from tests.golden import dump_snapshot


class ToyAnalyzer:
    """A one-line-per-fact language: `def NAME`, `NAME is OTHER`, `use PATH`."""

    def is_test_file(self, path: Path) -> bool:
        return Path(path).name.startswith("test_")

    def analyze(self, path: str, source: str) -> FileAnalysis:
        module = Path(path).stem
        analysis = FileAnalysis()
        for line_no, line in enumerate(source.splitlines(), start=1):
            words = line.split()
            if words[:1] == ["def"]:
                analysis.symbols.append(
                    {
                        "name": words[1],
                        "qualified_name": f"{module}.{words[1]}",
                        "kind": "class",
                        "start_line": line_no,
                        "end_line": line_no,
                        "visibility": "public",
                    }
                )
            elif words[1:2] == ["is"]:
                analysis.symbol_edges.append(
                    (f"{module}.{words[0]}", f"{module}.{words[2]}", "implements")
                )
            elif words[:1] == ["use"]:
                analysis.imports.append(words[1])
        return analysis

    def resolve_import(self, importer: str, module: str) -> list[str]:
        return [f"{module}.toy"]


def _toy_registry():
    registry = builtin_registry()
    registry.register(
        PluginDescriptor(
            name="toy",
            version="0.1.0",
            api_version=1,
            extensions={".toy": "toy"},
            analyzer=f"{__name__}:ToyAnalyzer",
        )
    )
    return registry


def _write_toy_project(root: Path) -> None:
    (root / "shapes.toy").write_text("def Shape\n")
    (root / "square.toy").write_text("def Square\ndef Drawable\nSquare is Drawable\nuse shapes\n")
    (root / "test_square.toy").write_text("use square\n")


def test_scan_indexes_a_language_plugin_through_the_generic_loop(tmp_path):
    _write_toy_project(tmp_path)
    conn = get_connection(tmp_path)

    run_scan(conn, tmp_path, load_config(tmp_path), registry=_toy_registry())

    snapshot = dump_snapshot(conn)
    assert {
        (row["path"], row["language"], row["file_kind"]) for row in snapshot["files"]
    } == {
        ("shapes.toy", "toy", "source"),
        ("square.toy", "toy", "source"),
        ("test_square.toy", "toy", "test"),
    }
    assert {row["qualified_name"] for row in snapshot["symbols"]} == {
        "shapes.Shape",
        "square.Drawable",
        "square.Square",
    }
    assert {
        (str(row["source"]), str(row["target"]), row["relationship_type"])
        for row in snapshot["relationships"]
    } == {
        (
            str({"symbol": "square.Square", "path": "square.toy"}),
            str({"symbol": "square.Drawable", "path": "square.toy"}),
            "implements",
        ),
        (str({"file": "square.toy"}), str({"file": "shapes.toy"}), "imports"),
        (str({"file": "test_square.toy"}), str({"file": "square.toy"}), "imports"),
    }


def test_rust_files_are_analyzed_only_through_the_rust_plugin(tmp_path):
    from dataclasses import replace

    from project_mcp.plugins.registry import PluginRegistry
    from project_mcp.plugins.rust.descriptor import DESCRIPTOR
    from tests.golden import copy_fixture

    project_root = copy_fixture("rust", tmp_path)
    registry = PluginRegistry()
    registry.register(replace(DESCRIPTOR, analyzer=None))
    conn = get_connection(project_root)

    run_scan(conn, project_root, load_config(project_root), registry=registry)

    assert conn.execute(
        "SELECT COUNT(*) FROM files WHERE language = 'rust'"
    ).fetchone()[0] > 0
    assert conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM relationships").fetchone()[0] == 0
