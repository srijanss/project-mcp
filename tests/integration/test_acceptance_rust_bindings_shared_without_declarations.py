from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan
from project_mcp.plugins.rust import calls


def test_linking_copies_use_bindings_only_where_a_scope_declares_some(tmp_path, monkeypatch):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "lib.rs").write_text("pub mod app;\n\npub fn add() {}\n")
    (tmp_path / "src" / "app.rs").write_text(
        "use crate::add;\n\npub fn run() {\n    let total = 1 + 2;\n    if total > 0 {\n        add();\n    }\n}\n"
    )
    scopes = []
    scope_bindings = calls._scope_bindings

    def spy(outer, local):
        result = scope_bindings(outer, local)
        scopes.append((bool(local), result is outer))
        return result

    monkeypatch.setattr(calls, "_scope_bindings", spy)

    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, load_config(tmp_path))
    imported = conn.execute(
        """
        SELECT count(*) FROM relationships r JOIN symbols target ON target.id = r.target_entity_id
        WHERE r.relationship_type = 'imports' AND r.source_entity_type = 'file'
          AND target.qualified_name = 'src.lib.add'
        """
    ).fetchone()[0]
    conn.close()

    assert imported == 1
    assert (False, True) in scopes
    assert all(shared for declares, shared in scopes if not declares)
