from project_mcp.plugins.rust.calls import rust_file_links, rust_symbol_uses, rust_use_imports

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


def test_rust_symbol_uses_reads_past_a_deeply_nested_module_level_macro():
    source = "table!" + "(" * 3000 + "1" + ")" * 3000 + ";\n\nfn checks() {\n    add();\n}\n"

    uses = rust_symbol_uses("src/lib.rs", source, {}, {"src.lib.add", "src.lib.checks"})

    assert uses == [("src.lib.checks", "src.lib.add", "calls")]


def test_rust_symbol_uses_keeps_a_crate_directory_named_mod_in_paths():
    known = {"mod.src.lib.add", "mod.src.util.adds", "src.lib.add"}

    uses = rust_symbol_uses("mod/src/util.rs", "fn adds() {\n    super::add();\n}\n", {}, known)

    assert uses == [("mod.src.util.adds", "mod.src.lib.add", "calls")]


def test_rust_symbol_uses_resolves_through_a_symbol_index_built_once(monkeypatch):
    from project_mcp.plugins.rust import calls

    known = {"src.lib.uses", "src.utils.mod.helper"}
    index = calls.symbol_index(known)
    # Only the index built beforehand still knows `src.utils.mod` as `src.utils`.
    monkeypatch.setattr(calls, "_module_path", lambda name: name)
    source = "fn uses() {\n    crate::utils::helper();\n}\n"

    uses = rust_symbol_uses("src/lib.rs", source, {}, known, index=index)

    assert uses == [("src.lib.uses", "src.utils.mod.helper", "calls")]


def test_workspace_crates_skips_a_manifest_that_is_not_utf_8(tmp_path):
    from project_mcp.plugins.rust.calls import workspace_crates

    (tmp_path / "good").mkdir()
    (tmp_path / "good" / "Cargo.toml").write_text('[package]\nname = "good-crate"\n')
    (tmp_path / "bad").mkdir()
    (tmp_path / "bad" / "Cargo.toml").write_bytes(b'[package]\nname = "caf\xe9"\n')

    assert workspace_crates(tmp_path, ["bad/src/lib.rs", "good/src/lib.rs"]) == {"good_crate": "good"}


def test_rust_use_imports_lists_the_known_items_a_file_s_use_declarations_name():
    known = {"src.lib.add", "src.shapes.Square", "src.shapes.Circle", "src.util.mod.helper", "src.app.run"}
    source = (
        "use crate::shapes::{Circle, Square as Shape};\n"
        "use std::fmt::Display;\n"
        "use crate::shapes::*;\n\n"
        "mod inner {\n    use crate::util::helper;\n}\n\n"
        "fn run() {\n    use crate::add;\n}\n"
    )

    imports = rust_use_imports("src/app.rs", source, {}, known)

    assert sorted(imports) == ["src.lib.add", "src.shapes.Circle", "src.shapes.Square", "src.util.mod.helper"]


def test_rust_use_imports_lists_an_item_imported_as_underscore():
    known = {"src.traits.Describe", "src.traits.Show"}
    source = "use crate::traits::Describe as _;\nuse crate::traits::{Show as _};\n"

    assert sorted(rust_use_imports("src/app.rs", source, {}, known)) == ["src.traits.Describe", "src.traits.Show"]


def test_rust_use_imports_resolves_a_block_use_through_the_module_s_aliases_only():
    known = {"src.shapes.Square", "src.shapes.Circle"}
    source = (
        "use crate::shapes as shapes_alias;\n\n"
        "fn run() {\n    use shapes_alias::Square;\n}\n\n"
        "mod inner {\n    use shapes_alias::Circle;\n}\n"
    )

    assert rust_use_imports("src/app.rs", source, {}, known) == ["src.shapes.Square"]


def test_rust_file_links_reads_uses_and_imports_from_one_parse(monkeypatch):
    from types import SimpleNamespace

    from project_mcp.plugins import treesitter
    from project_mcp.plugins.rust import calls

    known = {"src.lib.add", "src.app.run"}
    source = "use crate::add;\n\npub fn run() {\n    add();\n}\n"
    parsed = []
    monkeypatch.setattr(
        calls, "treesitter",
        SimpleNamespace(parse=lambda text, language: parsed.append(text) or treesitter.parse(text, language)),
    )

    assert rust_file_links("src/app.rs", source, {}, known) == (
        [("src.app.run", "src.lib.add", "calls")],
        ["src.lib.add"],
    )
    assert parsed == [source]


def test_rust_file_links_keeps_an_outer_alias_s_target_when_a_block_shadows_its_base():
    known = {"src.shapes.make", "src.shapes.Square", "src.other.make", "src.other.Square", "src.other", "src.app.run"}
    source = (
        "use crate::shapes as alias;\nuse alias::make as build;\nuse alias::Square as S;\n\n"
        "pub fn run() {\n    use crate::other as alias;\n    use S as T;\n    build();\n}\n"
    )

    uses, imports = rust_file_links("src/app.rs", source, {}, known)

    assert uses == [("src.app.run", "src.shapes.make", "calls")]
    assert sorted(imports) == ["src.other", "src.shapes.Square", "src.shapes.make"]
