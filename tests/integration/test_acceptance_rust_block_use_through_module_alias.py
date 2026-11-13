from project_mcp.tools.symbols import get_dependents


def test_a_block_use_through_a_module_alias_imports_the_item(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "lib.rs").write_text("pub mod shapes;\npub mod app;\n")
    (tmp_path / "src" / "shapes.rs").write_text("pub struct Square;\n")
    (tmp_path / "src" / "app.rs").write_text(
        "use crate::shapes as shapes_alias;\n\npub fn run() {\n    use shapes_alias::Square;\n}\n"
    )

    assert [(row["source"], row["relationship_type"]) for row in get_dependents(tmp_path, "src.shapes.Square")] == [
        ("src/app.rs", "imports")
    ]
