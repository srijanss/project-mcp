from project_mcp.tools.tests import get_tests_for

LIB = """\
pub struct Widget;

pub fn make() -> Widget {
    Widget
}

pub fn wrap(widget: Widget) -> Widget {
    widget
}

#[cfg(test)]
mod tests {
    use super::{make, wrap, Widget};

    #[test]
    fn wraps_a_made_widget() {
        assert!(matches!(wrap(wrap(make())), Widget));
    }
}
"""


def test_calls_and_names_nested_in_macro_arguments_link_the_test_once_each(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "lib.rs").write_text(LIB)

    def linked(name):
        return [(row["tests"], row["evidence"]) for row in get_tests_for(tmp_path, name)]

    assert linked("src.lib.make") == [(["src.lib.tests.wraps_a_made_widget"], ["rust_calls"])]
    assert linked("src.lib.wrap") == [(["src.lib.tests.wraps_a_made_widget"], ["rust_calls"])]
    assert linked("src.lib.Widget") == [(["src.lib.tests.wraps_a_made_widget"], ["rust_references"])]


def test_a_call_deep_inside_nested_macro_arguments_is_linked(tmp_path):
    depth = 3000
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "lib.rs").write_text(
        "pub fn add() -> i32 {\n    1\n}\n\n#[cfg(test)]\nmod tests {\n    use super::*;\n\n"
        "    #[test]\n    fn adds_deep_down() {\n"
        f"        assert!({'(' * depth}add(){')' * depth} == 1);\n"
        "    }\n}\n"
    )

    assert [row.get("tests") for row in get_tests_for(tmp_path, "src.lib.add")] == [
        ["src.lib.tests.adds_deep_down"]
    ]
