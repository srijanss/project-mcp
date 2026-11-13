from project_mcp.tools.tests import get_tests_for

LIB = """\
pub mod a {
    pub fn run() {}
}

pub mod b {
    pub fn run() {}
}

#[cfg(test)]
mod tests {
    use crate::a::run;

    #[test]
    fn runs_b_inside_the_block() {
        {
            use crate::b::run;
            run();
        }
    }

    #[test]
    fn runs_a_after_the_block() {
        {
            use crate::b::run;
        }
        run();
    }
}
"""


def test_a_use_inside_a_block_binds_its_name_only_within_that_block(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "lib.rs").write_text(LIB)

    def tests_for(name):
        return [test for row in get_tests_for(tmp_path, name) for test in row.get("tests", [])]

    assert tests_for("src.lib.a.run") == ["src.lib.tests.runs_a_after_the_block"]
    assert tests_for("src.lib.b.run") == ["src.lib.tests.runs_b_inside_the_block"]
