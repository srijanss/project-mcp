from project_mcp.plugins.rust.parser import parse_rust_source
from project_mcp.plugins.rust.tree_parser import parse_rust_tree

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
