from project_mcp.plugins.react.scope import visible_component

ROWS = [
    (1, "Row", 1, 3),
    (2, "Table", 5, 7),
    (3, "Outer", 9, 14),
    (4, "Row", 10, 12),
    (5, "Cell", 16, 18),
]


def test_a_nested_component_is_visible_only_inside_the_component_declaring_it():
    assert visible_component(ROWS, "Row", 6) == 1
    assert visible_component(ROWS, "Row", 13) == 4
    assert visible_component(ROWS, "Row", 17) == 1


def test_a_top_level_component_is_visible_everywhere_and_unknown_names_are_not():
    assert visible_component(ROWS, "Cell", 11) == 5
    assert visible_component(ROWS, "Missing", 6) is None
