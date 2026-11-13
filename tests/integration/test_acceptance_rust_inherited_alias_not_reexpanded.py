from project_mcp.tools.symbols import get_dependencies, get_dependents


def test_a_block_import_built_on_an_outer_alias_keeps_its_crate_when_the_block_rebinds_the_crate_name(tmp_path):
    (tmp_path / "Cargo.toml").write_text('[package]\nname = "app"\nversion = "0.1.0"\n')
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "lib.rs").write_text("pub mod other;\npub mod app;\n")
    (tmp_path / "src" / "other.rs").write_text("pub fn make() {}\n")
    (tmp_path / "src" / "app.rs").write_text(
        "use dep::make as build;\n\n"
        "pub fn run() {\n    use crate::other as dep;\n    use build as go;\n    go();\n}\n"
    )
    dep = tmp_path / "dep"
    (dep / "src").mkdir(parents=True)
    (dep / "Cargo.toml").write_text('[package]\nname = "dep"\nversion = "0.1.0"\n')
    (dep / "src" / "lib.rs").write_text("pub fn make() {}\n")

    assert [(row["target"], row["relationship_type"]) for row in get_dependencies(tmp_path, "src.app.run")] == [
        ("dep.src.lib.make", "calls")
    ]
    assert get_dependents(tmp_path, "src.other.make") == []
