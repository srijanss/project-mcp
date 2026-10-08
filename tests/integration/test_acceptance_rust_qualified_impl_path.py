from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan

SOURCE = """\
pub trait Named {}
pub trait Display {}

impl Named for shapes::Triangle {}
impl fmt::Display for shapes::Triangle {}

mod shapes {
    pub trait Named {}
    pub struct Circle;
    pub struct Square;
    pub struct Triangle;

    impl super::Named for Circle {}
    impl self::Named for Square {}
    impl crate::Display for Square {}
}
"""


def test_impls_through_explicit_paths_link_the_item_the_path_names(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "lib.rs").write_text(SOURCE)
    conn = get_connection(tmp_path)

    run_scan(conn, tmp_path, load_config(tmp_path))

    implements = conn.execute(
        """
        SELECT source.qualified_name, target.qualified_name
        FROM relationships
        JOIN symbols source ON source.id = relationships.source_entity_id
        JOIN symbols target ON target.id = relationships.target_entity_id
        WHERE relationship_type = 'implements'
        """
    ).fetchall()
    assert sorted(implements) == [
        ("src.lib.shapes.Circle", "src.lib.Named"),
        ("src.lib.shapes.Square", "src.lib.Display"),
        ("src.lib.shapes.Square", "src.lib.shapes.Named"),
        ("src.lib.shapes.Triangle", "src.lib.Named"),
    ]
