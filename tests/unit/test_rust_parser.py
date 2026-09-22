from project_mcp.analyzers.rust.parser import (
    extract_rust_impls,
    extract_rust_use,
    parse_rust_source,
)

SOURCE = """
struct Widget {
    name: String,
}

enum State {
    On,
    Off,
}

fn render(widget: &Widget) -> String {
    widget.name.clone()
}

pub fn public_render() -> String {
    String::new()
}
"""


def test_parse_rust_source_extracts_module_struct_enum_and_function():
    symbols = parse_rust_source("src/widget.rs", SOURCE)
    by_qualified_name = {s["qualified_name"]: s for s in symbols}

    module_symbol = by_qualified_name["src.widget"]
    assert module_symbol["kind"] == "module"
    assert module_symbol["name"] == "src.widget"

    struct_symbol = by_qualified_name["src.widget.Widget"]
    assert struct_symbol["kind"] == "struct"
    assert struct_symbol["name"] == "Widget"
    assert struct_symbol["visibility"] == "private"

    enum_symbol = by_qualified_name["src.widget.State"]
    assert enum_symbol["kind"] == "enum"
    assert enum_symbol["name"] == "State"
    assert enum_symbol["visibility"] == "private"

    func_symbol = by_qualified_name["src.widget.render"]
    assert func_symbol["kind"] == "function"
    assert func_symbol["name"] == "render"
    assert func_symbol["visibility"] == "private"

    pub_func_symbol = by_qualified_name["src.widget.public_render"]
    assert pub_func_symbol["kind"] == "function"
    assert pub_func_symbol["name"] == "public_render"
    assert pub_func_symbol["visibility"] == "public"


USE_SOURCE = """
use std::collections::HashMap;
use crate::widget::Widget;
use std::fmt::{self, Display};
"""


def test_extract_rust_use_extracts_simple_and_grouped_use_statements():
    uses = extract_rust_use("src/widget.rs", USE_SOURCE)
    by_line = {u["line"]: u for u in uses}

    assert by_line[2] == {"path": "std::collections", "names": ["HashMap"], "line": 2}
    assert by_line[3] == {"path": "crate::widget", "names": ["Widget"], "line": 3}
    assert by_line[4] == {
        "path": "std::fmt",
        "names": ["self", "Display"],
        "line": 4,
    }


MULTILINE_USE_SOURCE = """
use std::collections::{
    HashMap,
    HashSet,
};
"""


def test_extract_rust_use_extracts_multiline_grouped_use_statement():
    uses = extract_rust_use("src/widget.rs", MULTILINE_USE_SOURCE)

    assert uses == [
        {"path": "std::collections", "names": ["HashMap", "HashSet"], "line": 2}
    ]


NESTED_GROUP_USE_SOURCE = """
use std::{fmt::{self, Display}, io::Read};
"""


def test_extract_rust_use_flattens_nested_brace_groups():
    uses = extract_rust_use("src/widget.rs", NESTED_GROUP_USE_SOURCE)

    assert {"path": "std::fmt", "names": ["self", "Display"], "line": 2} in uses
    assert {"path": "std::io", "names": ["Read"], "line": 2} in uses


TRAIT_SOURCE = """
trait Greet {
    fn greet(&self) -> String;
}

pub trait Shout {
    fn shout(&self) -> String;
}
"""


def test_parse_rust_source_extracts_trait_symbols():
    symbols = parse_rust_source("src/widget.rs", TRAIT_SOURCE)
    by_qualified_name = {s["qualified_name"]: s for s in symbols}

    greet_trait = by_qualified_name["src.widget.Greet"]
    assert greet_trait["kind"] == "trait"
    assert greet_trait["name"] == "Greet"
    assert greet_trait["visibility"] == "private"

    shout_trait = by_qualified_name["src.widget.Shout"]
    assert shout_trait["kind"] == "trait"
    assert shout_trait["name"] == "Shout"
    assert shout_trait["visibility"] == "public"


FN_MODIFIER_SOURCE = """
async fn fetch() -> String {
    String::new()
}

pub async fn public_fetch() -> String {
    String::new()
}

const fn compute() -> i32 {
    0
}

unsafe fn raw_access() -> i32 {
    0
}
"""


def test_parse_rust_source_extracts_functions_with_async_const_unsafe_modifiers():
    symbols = parse_rust_source("src/widget.rs", FN_MODIFIER_SOURCE)
    by_qualified_name = {s["qualified_name"]: s for s in symbols}

    fetch_fn = by_qualified_name["src.widget.fetch"]
    assert fetch_fn["kind"] == "function"
    assert fetch_fn["visibility"] == "private"

    public_fetch_fn = by_qualified_name["src.widget.public_fetch"]
    assert public_fetch_fn["kind"] == "function"
    assert public_fetch_fn["visibility"] == "public"

    compute_fn = by_qualified_name["src.widget.compute"]
    assert compute_fn["kind"] == "function"

    raw_access_fn = by_qualified_name["src.widget.raw_access"]
    assert raw_access_fn["kind"] == "function"


UNSAFE_TRAIT_SOURCE = """
unsafe trait Sync2 {
    fn marker(&self);
}
"""


def test_parse_rust_source_extracts_unsafe_trait():
    symbols = parse_rust_source("src/widget.rs", UNSAFE_TRAIT_SOURCE)
    by_qualified_name = {s["qualified_name"]: s for s in symbols}

    sync_trait = by_qualified_name["src.widget.Sync2"]
    assert sync_trait["kind"] == "trait"
    assert sync_trait["visibility"] == "private"


IMPL_SOURCE = """
impl Widget {
    fn new() -> Self {
        Widget { name: String::new() }
    }
}

impl Display for Widget {
    fn fmt(&self, f: &mut Formatter) -> Result {
        Ok(())
    }
}
"""


def test_extract_rust_impls_distinguishes_inherent_and_trait_impls():
    impls = extract_rust_impls("src/widget.rs", IMPL_SOURCE)
    by_line = {i["line"]: i for i in impls}

    assert by_line[2] == {"struct": "Widget", "trait": None, "line": 2}
    assert by_line[8] == {"struct": "Widget", "trait": "Display", "line": 8}


NESTED_GENERIC_IMPL_SOURCE = """
impl<T: From<u32>> Widget<T> {
    fn new() -> Self {
        todo!()
    }
}
"""


def test_extract_rust_impls_handles_nested_generic_bounds():
    impls = extract_rust_impls("src/widget.rs", NESTED_GENERIC_IMPL_SOURCE)
    by_line = {i["line"]: i for i in impls}

    assert by_line[2] == {"struct": "Widget", "trait": None, "line": 2}
