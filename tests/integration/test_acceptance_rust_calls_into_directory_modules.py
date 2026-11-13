from project_mcp.tools.tests import get_tests_for


def _project(tmp_path):
    (tmp_path / "Cargo.toml").write_text('[package]\nname = "sample"\nversion = "0.1.0"\n')
    (tmp_path / "src" / "utils").mkdir(parents=True)
    (tmp_path / "src" / "lib.rs").write_text("pub mod utils;\n")
    (tmp_path / "src" / "utils" / "mod.rs").write_text(
        "pub mod math;\n\npub fn add() {}\n\n"
        "#[cfg(test)]\nmod tests {\n    #[test]\n    fn doubles_through_super() {\n        super::math::double();\n    }\n}\n"
    )
    (tmp_path / "src" / "utils" / "math.rs").write_text("pub fn double() {\n    super::add();\n}\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "it.rs").write_text(
        "#[test]\nfn adds_through_the_crate_path() {\n    sample::utils::add();\n}\n"
    )
    return tmp_path


def test_a_function_in_a_mod_rs_module_lists_the_tests_calling_it_by_its_module_path(tmp_path):
    project = _project(tmp_path)

    rows = {row["test_file"]: row for row in get_tests_for(project, "src.utils.mod.add")}

    assert rows["tests/it.rs"]["tests"] == ["tests.it.adds_through_the_crate_path"]
    assert rows["tests/it.rs"]["confidence"] == "high"


def test_a_module_beside_a_mod_rs_is_reached_through_super(tmp_path):
    project = _project(tmp_path)

    rows = {row["test_file"]: row for row in get_tests_for(project, "src.utils.math.double")}

    assert rows["src/utils/mod.rs"]["tests"] == ["src.utils.mod.tests.doubles_through_super"]
