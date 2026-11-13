from project_mcp.tools.symbols import get_dependents


def test_a_file_importing_a_trait_as_underscore_depends_on_the_trait(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "lib.rs").write_text("pub mod traits;\npub mod app;\n")
    (tmp_path / "src" / "traits.rs").write_text("pub trait Describe {\n    fn describe(&self) {}\n}\n")
    (tmp_path / "src" / "app.rs").write_text("use crate::traits::Describe as _;\n")

    assert [(row["source"], row["relationship_type"]) for row in get_dependents(tmp_path, "src.traits.Describe")] == [
        ("src/app.rs", "imports")
    ]
