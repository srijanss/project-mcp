from project_mcp.tools.tests import get_tests_for

LIB = """\
pub fn add() -> i32 {
    1
}

pub fn sub() -> i32 {
    0
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_mentions_add() {
        println!("add() is {}", r#"add()"#);
        assert_eq!(
            sub(), // add()
            /* add() */ 0
        );
    }
}
"""


def test_call_like_text_in_a_macro_s_strings_and_comments_does_not_link_a_test(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "lib.rs").write_text(LIB)

    assert get_tests_for(tmp_path, "src.lib.add") == []
    assert [row.get("tests") for row in get_tests_for(tmp_path, "src.lib.sub")] == [
        ["src.lib.tests.only_mentions_add"]
    ]
