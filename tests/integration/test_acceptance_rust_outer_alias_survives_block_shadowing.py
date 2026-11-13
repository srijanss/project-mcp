from project_mcp.tools.symbols import get_dependencies, get_dependents


def test_an_outer_alias_keeps_its_target_when_a_block_rebinds_a_name_it_was_built_from(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "lib.rs").write_text("pub mod shapes;\npub mod other;\npub mod app;\n")
    (tmp_path / "src" / "shapes.rs").write_text("pub struct Square;\n\npub fn make() {}\n")
    (tmp_path / "src" / "other.rs").write_text("pub struct Square;\n\npub fn make() {}\n")
    (tmp_path / "src" / "app.rs").write_text(
        "use crate::shapes as alias;\nuse alias::make as build;\nuse alias::Square as S;\n\n"
        "pub fn run() {\n    use crate::other as alias;\n    use S as T;\n    build();\n}\n"
    )

    assert [(row["target"], row["relationship_type"]) for row in get_dependencies(tmp_path, "src.app.run")] == [
        ("src.shapes.make", "calls")
    ]
    assert get_dependents(tmp_path, "src.other.Square") == []
