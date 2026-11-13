from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan
from project_mcp.plugins.rust import calls


def test_linking_a_rust_project_indexes_its_symbols_once_for_every_file(tmp_path, monkeypatch):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "lib.rs").write_text("pub mod a;\npub mod b;\n\npub fn add() {}\n")
    (tmp_path / "src" / "a.rs").write_text("pub fn first() {\n    crate::add();\n}\n")
    (tmp_path / "src" / "b.rs").write_text("pub fn second() {\n    crate::add();\n}\n")
    built = []
    symbol_index = calls.symbol_index
    monkeypatch.setattr(calls, "symbol_index", lambda known: built.append(len(known)) or symbol_index(known))

    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, load_config(tmp_path))
    linked = conn.execute(
        """
        SELECT source.qualified_name FROM relationships r
        JOIN symbols source ON source.id = r.source_entity_id
        JOIN symbols target ON target.id = r.target_entity_id
        WHERE r.relationship_type = 'calls' AND target.qualified_name = 'src.lib.add'
        ORDER BY 1
        """
    ).fetchall()
    conn.close()

    assert linked == [("src.a.first",), ("src.b.second",)]
    assert len(built) == 1
