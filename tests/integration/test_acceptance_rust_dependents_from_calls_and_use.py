from project_mcp.tools.symbols import get_dependencies, get_dependents


def _workspace(root):
    core = root / "core"
    (core / "src").mkdir(parents=True)
    (core / "Cargo.toml").write_text('[package]\nname = "core-lib"\nversion = "0.1.0"\n')
    (core / "src" / "lib.rs").write_text("pub mod shapes;\n\npub fn area() -> i32 {\n    1\n}\n")
    (core / "src" / "shapes.rs").write_text("pub struct Square;\n")
    app = root / "app"
    (app / "src").mkdir(parents=True)
    (app / "Cargo.toml").write_text('[package]\nname = "app"\nversion = "0.1.0"\n')
    (app / "src" / "main.rs").write_text(
        "mod report;\n\nuse core_lib::area;\nuse core_lib::shapes::Square;\n\n"
        "fn main() {\n    let _square = Square;\n    area();\n}\n"
    )
    (app / "src" / "report.rs").write_text("use core_lib::shapes::Square as Shape;\n\npub type Shown = Shape;\n")


def _pairs(rows, end):
    return sorted((row[end], row["relationship_type"]) for row in rows)


def test_dependents_of_a_rust_item_are_its_callers_and_the_files_that_use_it(tmp_path):
    _workspace(tmp_path)

    assert _pairs(get_dependents(tmp_path, "core.src.lib.area"), "source") == [
        ("app.src.main.main", "calls"),
        ("app/src/main.rs", "imports"),
    ]
    assert _pairs(get_dependents(tmp_path, "core.src.shapes.Square"), "source") == [
        ("app.src.main.main", "references"),
        ("app/src/main.rs", "imports"),
        ("app/src/report.rs", "imports"),
    ]


def test_dependencies_of_a_rust_function_are_what_it_calls_and_names(tmp_path):
    _workspace(tmp_path)

    assert _pairs(get_dependencies(tmp_path, "app.src.main.main"), "target") == [
        ("core.src.lib.area", "calls"),
        ("core.src.shapes.Square", "references"),
    ]
