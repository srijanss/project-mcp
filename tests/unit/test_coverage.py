from project_mcp.config import load_config
from project_mcp.coverage import coverage_block
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan
from project_mcp.plugins.registry import builtin_registry


def _scanned(tmp_path, registry):
    (tmp_path / "app.py").write_text("def run():\n    pass\n")
    (tmp_path / "lib.rs").write_text("pub fn run() {}\n")
    (tmp_path / "README.md").write_text("# demo\n")
    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, load_config(tmp_path), registry=registry)
    return conn


def _without_notes(languages):
    return {
        language: {k: v for k, v in entry.items() if k != "note"}
        for language, entry in languages.items()
    }


def test_coverage_of_files_every_active_plugin_analyzed_is_full(tmp_path):
    registry = builtin_registry()
    conn = _scanned(tmp_path, registry)

    block = coverage_block(conn, registry, {"app.py", "README.md"})

    assert block == {
        "status": "full",
        "active_plugins": ["python", "javascript", "rust", "django", "astro", "react"],
        "languages": {"python": {"analyzed": True}},
    }


def test_coverage_names_a_disabled_plugins_language_as_unanalyzed(tmp_path):
    registry = builtin_registry()
    registry.disable("rust")
    conn = _scanned(tmp_path, registry)

    mixed = coverage_block(conn, registry, {"app.py", "lib.rs"})
    rust_only = coverage_block(conn, registry, {"lib.rs"})

    rust = {"analyzed": False, "reason": "plugin_disabled"}
    assert (mixed["status"], _without_notes(mixed["languages"])) == (
        "partial",
        {"python": {"analyzed": True}, "rust": rust},
    )
    assert (rust_only["status"], _without_notes(rust_only["languages"])) == (
        "none",
        {"rust": rust},
    )


def test_coverage_reports_failed_plugins_and_failed_files_with_their_errors(tmp_path):
    registry = builtin_registry()
    conn = _scanned(tmp_path, registry)
    registry.failed_plugins["rust"] = "failed to load: missing toolchain"
    conn.execute(
        "UPDATE files SET analysis_status = 'file_failed',"
        " analysis_error = 'SyntaxError: bad' WHERE path = 'app.py'"
    )

    block = coverage_block(conn, registry, {"app.py", "lib.rs"})

    assert block["status"] == "none"
    assert _without_notes(block["languages"]) == {
        "python": {
            "analyzed": False,
            "reason": "file_failed",
            "errors": {"app.py": "SyntaxError: bad"},
        },
        "rust": {
            "analyzed": False,
            "reason": "plugin_failed",
            "error": "failed to load: missing toolchain",
        },
    }


def test_coverage_of_a_query_touching_no_files_spans_the_whole_project(tmp_path):
    registry = builtin_registry()
    registry.disable("rust")
    conn = _scanned(tmp_path, registry)

    block = coverage_block(conn, registry, set())

    assert (block["status"], sorted(block["languages"])) == ("partial", ["python", "rust"])


def test_referenced_paths_are_the_indexed_files_named_anywhere_in_a_value(tmp_path):
    from project_mcp.coverage import referenced_paths

    conn = _scanned(tmp_path, builtin_registry())
    value = {
        "items": [{"file": "app.py", "name": "run"}, {"file": "gone.py"}],
        "notes": ["see lib.rs", ("README.md",)],
        "count": 2,
    }

    assert referenced_paths(conn, value) == {"app.py", "README.md"}


def test_unanalyzed_language_entries_carry_a_relayable_note(tmp_path):
    registry = builtin_registry()
    registry.disable("rust")
    conn = _scanned(tmp_path, registry)
    conn.execute(
        "UPDATE files SET analysis_status = 'file_failed',"
        " analysis_error = 'SyntaxError: bad' WHERE path = 'app.py'"
    )

    languages = coverage_block(conn, registry, {"app.py", "lib.rs"})["languages"]

    assert languages["rust"]["note"] == (
        "The rust plugin is installed but disabled. Symbols and relationships are"
        " unavailable for these files; results are file-level only. Enable it in"
        " mcpctl.toml [plugins]: add it to `enabled`, or remove it from `disabled`."
    )
    assert languages["python"]["note"] == (
        "The python plugin could not analyze 1 file (see `errors`); those files"
        " are file-level only."
    )


def test_files_of_a_known_language_with_no_installed_plugin_name_the_plugin(tmp_path):
    (tmp_path / "main.go").write_text("package main\n")
    (tmp_path / "notes.xyz").write_text("?\n")
    registry = builtin_registry()
    conn = _scanned(tmp_path, registry)

    block = coverage_block(conn, registry, {"main.go", "notes.xyz", "app.py"})

    assert block["status"] == "partial"
    assert sorted(block["languages"]) == ["go", "python"]
    assert block["languages"]["go"] == {
        "analyzed": False,
        "reason": "plugin_not_installed",
        "note": (
            "No go plugin is installed. Symbols and relationships are unavailable"
            " for these files; results are file-level only. To analyze them,"
            " install a project-mcp plugin for go (an entry point in the"
            " project_mcp.plugins group) and enable it in mcpctl.toml [plugins]."
        ),
    }


def test_uncovered_languages_count_files_no_active_plugin_analyzes(tmp_path):
    from project_mcp.coverage import uncovered_languages

    (tmp_path / "b.rs").write_text("pub fn b() {}\n")
    (tmp_path / "main.go").write_text("package main\n")
    registry = builtin_registry()
    registry.disable("rust")
    conn = _scanned(tmp_path, registry)

    assert uncovered_languages(conn, registry) == {"go": 1, "rust": 2}


def test_server_instructions_are_built_from_the_active_plugins():
    from project_mcp.coverage import server_instructions

    registry = builtin_registry()
    registry.disable("javascript")

    instructions = server_instructions(registry)

    assert "Active plugins: python, rust, django." in instructions
    assert "Analyzed languages: python, rust." in instructions
    assert "javascript" not in instructions and "typescript" not in instructions
    assert "relay each unanalyzed language's `note`" in instructions
