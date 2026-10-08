from project_mcp.plugins.rust.parser import parse_rust_source
from project_mcp.plugins.rust.tree_parser import parse_rust_implements, parse_rust_tree

SOURCE = """\
use std::fmt;

pub struct Widget {
    pub name: String,
}

pub(crate) enum Shape {
    Circle,
}

struct Unit;

pub trait Describe {
    fn describe(&self) -> String;
}

impl Describe for Widget {
    fn describe(&self) -> String {
        self.name.clone()
    }
}

pub async fn load() {}
pub(crate) const unsafe fn raw() {}
unsafe trait Marker {}

fn outer() {
    fn inner() {}
    // fn commented() {}
}
"""


def test_parse_rust_tree_finds_the_symbols_the_regex_parser_finds():
    def key(symbol):
        return (symbol["qualified_name"], symbol["start_line"])

    assert sorted(parse_rust_tree("src/lib.rs", SOURCE), key=key) == sorted(
        parse_rust_source("src/lib.rs", SOURCE), key=key
    )


def test_parse_rust_tree_qualifies_items_in_nested_mods_and_skips_macro_bodies():
    source = """\
mod outer {
    pub mod inner {
        pub fn f() {}
    }
}
macro_rules! make {
    () => { fn hidden() {} };
}
"""
    found = [(s["qualified_name"], s["kind"], s["visibility"]) for s in parse_rust_tree("src/lib.rs", source)]

    assert found == [
        ("src.lib", "module", "public"),
        ("src.lib.outer", "module", "private"),
        ("src.lib.outer.inner", "module", "public"),
        ("src.lib.outer.inner.f", "function", "public"),
    ]


def test_parse_rust_implements_links_generic_and_nested_trait_impls_to_known_symbols():
    source = """\
mod shapes;
pub trait Describe {}
pub struct Wrapper<T>(T);
impl<T> Describe
    for Wrapper<T>
where
    T: Clone,
{
}
impl<T: Clone> fmt::Display for Wrapper<T> {}
impl Wrapper<u8> {}
impl Describe for Missing {}
mod round {
    pub struct Circle;
    impl super::Describe for Circle {}
}
"""
    symbols = parse_rust_tree("src/lib.rs", source)

    assert "src.lib.shapes" not in {s["qualified_name"] for s in symbols}
    assert parse_rust_implements("src/lib.rs", source, symbols) == [
        ("src.lib.Wrapper", "src.lib.Describe", "implements"),
        ("src.lib.round.Circle", "src.lib.Describe", "implements"),
    ]
