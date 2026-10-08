from project_mcp.config import load_config
from project_mcp.coverage import coverage_block
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan
from project_mcp.plugins.registry import builtin_registry

PAGE = "src/pages/index.astro"


def _scanned(tmp_path, registry):
    (tmp_path / "src" / "pages").mkdir(parents=True)
    (tmp_path / PAGE).write_text(
        '---\nimport Layout from "../layouts/Layout.ts";\n'
        'export function title() { return "x"; }\n---\n<h1>hi</h1>\n'
    )
    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, load_config(tmp_path), registry=registry)
    return conn


def _page_symbols(conn):
    return conn.execute(
        """
        SELECT s.qualified_name, s.kind, s.start_line FROM symbols s
        JOIN files f ON f.id = s.file_id WHERE f.path = ?
        """,
        (PAGE,),
    ).fetchall()


def _language(conn):
    return conn.execute("SELECT language FROM files WHERE path = ?", (PAGE,)).fetchone()[0]


def test_astro_files_are_analyzed_through_their_frontmatter(tmp_path):
    registry = builtin_registry()
    conn = _scanned(tmp_path, registry)

    symbols = {(name, kind): line for name, kind, line in _page_symbols(conn)}

    assert _language(conn) == "astro"
    assert ("src.pages.index", "module") in symbols
    (title,) = [line for (name, _), line in symbols.items() if name.endswith(".title")]
    assert title == 3
    assert coverage_block(conn, registry, {PAGE})["languages"] == {"astro": {"analyzed": True}}


def test_astro_files_stay_unanalyzed_with_the_astro_plugin_disabled(tmp_path):
    registry = builtin_registry()
    registry.disable("astro")
    conn = _scanned(tmp_path, registry)

    assert _language(conn) == "astro"
    assert _page_symbols(conn) == []
    assert not registry.analyzed("astro")


def test_astro_files_stay_unanalyzed_with_the_javascript_plugin_disabled(tmp_path):
    registry = builtin_registry()
    registry.disable("javascript")
    conn = _scanned(tmp_path, registry)

    assert _language(conn) == "astro"
    assert _page_symbols(conn) == []
    assert not registry.analyzed("astro")
