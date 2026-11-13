import pytest

from project_mcp.tools.tests import get_tests_for

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

    #[test]
    fn unrelated() {
        assert!(true);
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


@pytest.fixture
def project(tmp_path):
    (tmp_path / "Cargo.toml").write_text('[package]\nname = "sample"\nversion = "0.1.0"\n')
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "lib.rs").write_text(LIB)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "integration.rs").write_text(INTEGRATION)
    return tmp_path


def _tests_for(project, qualified_name):
    return {row["test_file"]: row for row in get_tests_for(project, qualified_name)}


def test_a_rust_function_lists_the_tests_that_call_it_directly_or_through_a_helper(project):
    rows = _tests_for(project, "src.lib.add")

    assert set(rows) == {"src/lib.rs", "tests/integration.rs"}
    assert rows["src/lib.rs"]["tests"] == ["src.lib.tests.adds_two_numbers"]
    assert rows["src/lib.rs"]["confidence"] == "high"
    assert rows["tests/integration.rs"]["tests"] == [
        "tests.integration.adds_from_outside_the_crate",
        "tests.integration.adds_through_a_helper",
    ]
    assert rows["tests/integration.rs"]["confidence"] == "high"
    assert "helper_call" in rows["tests/integration.rs"]["evidence"]


def test_a_rust_type_lists_the_tests_that_use_it_through_a_use_path(project):
    rows = _tests_for(project, "src.lib.Widget")

    assert {path: row["tests"] for path, row in rows.items()} == {
        "tests/integration.rs": ["tests.integration.holds_a_widget"]
    }
