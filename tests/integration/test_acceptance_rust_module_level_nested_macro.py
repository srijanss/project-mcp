from project_mcp.tools.tests import get_tests_for


def test_a_file_with_deeply_nested_module_level_macro_arguments_still_links_its_tests(tmp_path):
    depth = 3000
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "lib.rs").write_text(
        f"table!{'(' * depth}1{')' * depth};\n\n"
        "pub fn add() -> i32 {\n    1\n}\n\n#[cfg(test)]\nmod tests {\n    use super::*;\n\n"
        "    #[test]\n    fn adds() {\n        assert_eq!(add(), 1);\n    }\n}\n"
    )

    assert [row.get("tests") for row in get_tests_for(tmp_path, "src.lib.add")] == [
        ["src.lib.tests.adds"]
    ]
