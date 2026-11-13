import json
from pathlib import Path

from project_mcp.plugins import treesitter
from project_mcp.plugins.analysis import FileAnalysis
from project_mcp.plugins.rust.calls import rust_symbol_uses, workspace_crates
from project_mcp.plugins.rust.dependencies import list_rust_dependencies
from project_mcp.plugins.rust.parser import (
    _module_qualified_name,
    extract_rust_impls,
    extract_rust_use,
    parse_rust_source,
)
from project_mcp.plugins.rust.tree_parser import (
    discover_rust_tests,
    parse_rust_implements,
    parse_rust_tree,
)


class RustAnalyzer:
    def __init__(self) -> None:
        problem = treesitter.missing("rust")
        self.backend = "regex" if problem else "tree-sitter"
        self.warnings = [f"falls back to its regex parser: {problem}"] if problem else []

    def module_name(self, path: str) -> str:
        """The qualified name of the module symbol this file is indexed as."""
        return _module_qualified_name(path)

    def list_dependencies(self, project_root: Path) -> list[dict]:
        """The dependencies this project's manifests declare for the ecosystem."""
        return list_rust_dependencies(Path(project_root))

    def is_test_file(self, path: Path) -> bool:
        path = Path(path)
        in_test_dir = bool({"tests", "test"} & set(path.parts[:-1]))
        return in_test_dir or path.stem.startswith("test_") or path.stem.endswith("_test")

    def analyze(self, path: str, source: str) -> FileAnalysis:
        if self.backend == "tree-sitter":
            symbols = parse_rust_tree(path, source)
            symbol_edges = parse_rust_implements(path, source, symbols)
        else:
            symbols = parse_rust_source(path, source)
            module_name = symbols[0]["qualified_name"]
            symbol_edges = [
                (
                    f"{module_name}.{impl['struct']}",
                    f"{module_name}.{impl['trait']}",
                    "implements",
                )
                for impl in extract_rust_impls(path, source)
                if impl["trait"] is not None
            ]
        return FileAnalysis(
            symbols=symbols,
            symbol_edges=symbol_edges,
            imports=[use["path"] for use in extract_rust_use(path, source)],
        )

    def link_cross_file(self, context) -> None:
        """Link each function to the items it calls or names through `use`.

        Re-indexing a file drops the edges other files had into it, so every
        Rust file is relinked, not only the changed ones. The regex fallback
        cannot read function bodies and links nothing.
        """
        if self.backend != "tree-sitter":
            return
        conn = context.conn
        file_ids = [context.path_to_file_id[path] for path in context.plugin_paths]
        known: dict[str, int] = {}
        for file_id in file_ids:
            known.update(
                conn.execute("SELECT qualified_name, id FROM symbols WHERE file_id = ?", (file_id,))
            )
        crates = workspace_crates(context.project_root, context.plugin_paths)
        for path, file_id in zip(context.plugin_paths, file_ids):
            changed = context.changed.get(path)
            if changed is not None:
                source = changed.source
            else:
                try:
                    source = (Path(context.project_root) / path).read_text(errors="replace")
                except OSError:
                    continue
            conn.execute(
                """
                DELETE FROM relationships
                WHERE relationship_type IN ('calls', 'references')
                  AND source_entity_type = 'symbol' AND target_entity_type = 'symbol'
                  AND source_entity_id IN (SELECT id FROM symbols WHERE file_id = ?)
                """,
                (file_id,),
            )
            for caller, target, kind in rust_symbol_uses(path, source, crates, known):
                if caller not in known:
                    continue
                conn.execute(
                    """
                    INSERT INTO relationships (
                        source_entity_type, source_entity_id,
                        target_entity_type, target_entity_id,
                        relationship_type, confidence, evidence_json
                    ) VALUES ('symbol', ?, 'symbol', ?, ?, 'high', ?)
                    """,
                    (known[caller], known[target], kind, json.dumps([f"rust_{kind}"])),
                )

    def link_test_evidence(self, context) -> None:
        """Record the changed files' `#[test]` functions in the tests table.

        The regex fallback cannot read attributes, so without tree-sitter a
        file's tests are cleared but none are recorded.
        """
        conn = context.conn
        for path, changed in context.changed.items():
            conn.execute("DELETE FROM tests WHERE file_id = ?", (changed.file_id,))
            if self.backend != "tree-sitter":
                continue
            # An impl method can share a test's qualified name, since impls add
            # no scope; the start line tells the test function apart.
            for qualified_name, start_line in discover_rust_tests(path, changed.source):
                conn.execute(
                    """
                    INSERT INTO tests (symbol_id, file_id, test_kind, framework)
                    SELECT id, file_id, 'test_function', 'cargo' FROM symbols
                    WHERE qualified_name = ? AND file_id = ? AND start_line = ?
                    """,
                    (qualified_name, changed.file_id, start_line),
                )

    def resolve_import(self, importer: str, module: str) -> list[str]:
        """Candidate files for a `crate::` use path, relative to the crate's src/."""
        if module != "crate" and not module.startswith("crate::"):
            return []

        segments = importer.split("/")
        if "src" not in segments:
            return []
        src_index = segments.index("src")
        crate_root = "/".join(segments[: src_index + 1])

        module_segments = module.split("::")[1:]
        if not module_segments:
            return [f"{crate_root}/lib.rs", f"{crate_root}/main.rs"]

        module_path = "/".join([crate_root, *module_segments])
        return [f"{module_path}.rs", f"{module_path}/mod.rs"]
