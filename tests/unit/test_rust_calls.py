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
