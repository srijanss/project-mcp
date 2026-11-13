from project_mcp.plugins.rust.calls import rust_symbol_uses

LIB = """\
pub struct Widget;

pub fn add(a: i32, b: i32) -> i32 {
    a + b
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn adds_two_numbers() {
        assert_eq!(add(2, 2), 4);
    }
}
"""

INTEGRATION = """\
use sample::{add, Widget};

fn sum_of(a: i32, b: i32) -> i32 {
    add(a, b)
}

#[test]
fn adds_from_outside_the_crate() {
    assert_eq!(sample::add(2, 3), 5);
}

#[test]
fn adds_through_a_helper() {
    assert_eq!(sum_of(1, 1), 2);
}

#[test]
fn holds_a_widget() {
    let _widget: Widget = Widget;
}
"""

KNOWN = {
    "src.lib",
    "src.lib.Widget",
    "src.lib.add",
    "src.lib.tests",
    "src.lib.tests.adds_two_numbers",
    "tests.integration",
    "tests.integration.sum_of",
    "tests.integration.adds_from_outside_the_crate",
    "tests.integration.adds_through_a_helper",
    "tests.integration.holds_a_widget",
}


def test_rust_symbol_uses_resolves_calls_and_use_bound_names_to_known_symbols():
    crates = {"sample": ""}

    assert rust_symbol_uses("src/lib.rs", LIB, crates, KNOWN) == [
        ("src.lib.tests.adds_two_numbers", "src.lib.add", "calls"),
    ]
    assert rust_symbol_uses("tests/integration.rs", INTEGRATION, crates, KNOWN) == [
        ("tests.integration.sum_of", "src.lib.add", "calls"),
        ("tests.integration.adds_from_outside_the_crate", "src.lib.add", "calls"),
        ("tests.integration.adds_through_a_helper", "tests.integration.sum_of", "calls"),
        ("tests.integration.holds_a_widget", "src.lib.Widget", "references"),
    ]


def test_rust_symbol_uses_resolves_paths_into_and_out_of_mod_rs_modules():
    known = {"src.utils.mod.add", "src.utils.mod.tests.checks", "src.utils.math.double", "tests.it.calls"}

    assert rust_symbol_uses(
        "tests/it.rs", "fn calls() {\n    sample::utils::add();\n}\n", {"sample": ""}, known
    ) == [("tests.it.calls", "src.utils.mod.add", "calls")]
    assert rust_symbol_uses(
        "src/utils/math.rs", "pub fn double() {\n    super::add();\n}\n", {}, known
    ) == [("src.utils.math.double", "src.utils.mod.add", "calls")]
    assert rust_symbol_uses(
        "src/utils/mod.rs", "mod tests {\n    fn checks() {\n        super::math::double();\n    }\n}\n", {}, known
    ) == [("src.utils.mod.tests.checks", "src.utils.math.double", "calls")]


def test_rust_symbol_uses_applies_a_block_s_use_only_inside_that_block():
    source = (
        "use crate::a::run;\n\n"
        "fn outer() {\n    {\n        use crate::b::run;\n        run();\n    }\n    run();\n}\n"
    )

    uses = rust_symbol_uses("src/lib.rs", source, {}, {"src.lib.a.run", "src.lib.b.run", "src.lib.outer"})

    assert sorted(uses) == [
        ("src.lib.outer", "src.lib.a.run", "calls"),
        ("src.lib.outer", "src.lib.b.run", "calls"),
    ]


def test_rust_symbol_uses_skips_call_like_text_in_macro_strings_and_comments():
    source = (
        'fn checks() {\n'
        '    println!("add() {}", r#"add()"#, \'a\', b"add()");\n'
        '    assert!(sub() /* add() */ == 0); // add()\n'
        '}\n'
    )

    uses = rust_symbol_uses("src/lib.rs", source, {}, {"src.lib.add", "src.lib.sub", "src.lib.checks"})

    assert uses == [("src.lib.checks", "src.lib.sub", "calls")]


def test_rust_symbol_uses_scans_a_macro_s_tokens_once_however_deeply_nested(monkeypatch):
    from project_mcp.plugins.rust import calls

    scanned = []
    code_text = calls._code_text
    monkeypatch.setattr(calls, "_code_text", lambda tree: scanned.append(tree) or code_text(tree))
    source = "fn checks() {\n    assert!(" + "(" * 3000 + "add()" + ")" * 3000 + ");\n}\n"

    uses = rust_symbol_uses("src/lib.rs", source, {}, {"src.lib.add", "src.lib.checks"})

    assert uses == [("src.lib.checks", "src.lib.add", "calls")]
    assert len(scanned) == 1
