from types import SimpleNamespace

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan
from project_mcp.plugins import treesitter
from project_mcp.plugins.rust import calls


def test_linking_a_rust_file_parses_its_source_once(tmp_path, monkeypatch):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "lib.rs").write_text("pub mod app;\n\npub fn add() {}\n")
    app = "use crate::add;\n\npub fn run() {\n    add();\n}\n"
    (tmp_path / "src" / "app.rs").write_text(app)
    parsed = []
    monkeypatch.setattr(
        calls, "treesitter",
        SimpleNamespace(parse=lambda source, language: parsed.append(source) or treesitter.parse(source, language)),
    )

    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, load_config(tmp_path))
    edges = conn.execute(
        """
        SELECT r.relationship_type, r.source_entity_type FROM relationships r
        JOIN symbols target ON target.id = r.target_entity_id
        WHERE r.target_entity_type = 'symbol' AND target.qualified_name = 'src.lib.add'
        ORDER BY 1
        """
    ).fetchall()
    conn.close()

    assert edges == [("calls", "symbol"), ("imports", "file")]
    assert parsed.count(app) == 1
