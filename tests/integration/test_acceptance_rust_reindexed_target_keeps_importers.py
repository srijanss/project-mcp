from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan


def test_reindexing_only_the_imported_file_keeps_its_importers_edges(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "lib.rs").write_text("pub mod app;\n\npub struct Widget;\n\npub fn add() {}\n")
    (tmp_path / "src" / "app.rs").write_text("use crate::{add, Widget};\n")

    def imports():
        return sorted(
            conn.execute(
                """
                SELECT f.path, s.qualified_name FROM relationships r
                JOIN files f ON f.id = r.source_entity_id
                JOIN symbols s ON s.id = r.target_entity_id
                WHERE r.relationship_type = 'imports'
                  AND r.source_entity_type = 'file' AND r.target_entity_type = 'symbol'
                """
            )
        )

    conn = get_connection(tmp_path)
    try:
        run_scan(conn, tmp_path, load_config(tmp_path))
        (tmp_path / "src" / "lib.rs").write_text("pub mod app;\n\npub fn add() {}\n\npub struct Widget;\n")
        run_scan(conn, tmp_path, load_config(tmp_path))

        assert imports() == [("src/app.rs", "src.lib.Widget"), ("src/app.rs", "src.lib.add")]
    finally:
        conn.close()
