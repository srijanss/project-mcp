from project_mcp.plugins.react.colocated import colocated_source

PATHS = {
    "src/Button.tsx",
    "src/Button.test.tsx",
    "src/Card.jsx",
    "src/__tests__/Card.spec.jsx",
    "src/__tests__/Card.jsx",
    "src/forms/Field.ts",
    "src/forms/__tests__/Field.test.ts",
    "src/Lonely.test.tsx",
    "src/Other.tsx",
}


def test_a_test_file_is_named_after_the_source_beside_it_or_above_its_tests_directory():
    assert colocated_source("src/Button.test.tsx", PATHS) == "src/Button.tsx"
    assert colocated_source("src/__tests__/Card.spec.jsx", PATHS) == "src/Card.jsx"
    assert colocated_source("src/__tests__/Card.jsx", PATHS) == "src/Card.jsx"
    assert colocated_source("src/forms/__tests__/Field.test.ts", PATHS) == "src/forms/Field.ts"
    assert colocated_source("src/Lonely.test.tsx", PATHS) is None
    assert colocated_source("src/Other.tsx", PATHS) is None
