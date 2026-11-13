from project_mcp.tools.tests import get_tests_for


def test_a_crate_in_a_directory_named_mod_links_tests_through_super(tmp_path):
    crate = tmp_path / "mod"
    (crate / "src").mkdir(parents=True)
    (crate / "Cargo.toml").write_text('[package]\nname = "inner"\nversion = "0.1.0"\n')
    (crate / "src" / "lib.rs").write_text("pub mod util;\n\npub fn add() -> i32 {\n    1\n}\n")
    (crate / "src" / "util.rs").write_text("#[test]\nfn adds() {\n    assert_eq!(super::add(), 1);\n}\n")

    assert [row.get("tests") for row in get_tests_for(tmp_path, "mod.src.lib.add")] == [
        ["mod.src.util.adds"]
    ]
