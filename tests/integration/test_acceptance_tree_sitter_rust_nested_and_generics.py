from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan

SOURCE = """\
pub trait Describe {}

pub struct Wrapper<T> {
    inner: T,
}

impl<T> Describe
    for Wrapper<T>
where
    T: Clone,
{
}

pub fn
long_signature(
    a: u32,
) -> u32 {
    a
}

mod shapes {
    pub struct Circle;

    impl super::Describe for Circle {}

    pub fn area() {}
}

macro_rules! make {
    () => {
        fn hidden() {}
    };
}
"""


def _scan(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "lib.rs").write_text(SOURCE)
    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, load_config(tmp_path))
    return conn


def test_tree_sitter_finds_nested_mods_and_multiline_signatures_but_not_macro_bodies(tmp_path):
    conn = _scan(tmp_path)

    symbols = conn.execute("SELECT qualified_name, kind, visibility FROM symbols").fetchall()

    assert sorted(symbols) == [
        ("src.lib", "module", "public"),
        ("src.lib.Describe", "trait", "public"),
        ("src.lib.Wrapper", "struct", "public"),
        ("src.lib.long_signature", "function", "public"),
        ("src.lib.shapes", "module", "private"),
        ("src.lib.shapes.Circle", "struct", "public"),
        ("src.lib.shapes.area", "function", "public"),
    ]


def test_trait_impls_for_generic_types_and_in_nested_mods_become_implements(tmp_path):
    conn = _scan(tmp_path)

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
        ("src.lib.Wrapper", "src.lib.Describe"),
        ("src.lib.shapes.Circle", "src.lib.Describe"),
    ]
