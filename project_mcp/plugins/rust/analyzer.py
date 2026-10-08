from pathlib import Path

from project_mcp.plugins import treesitter
from project_mcp.plugins.analysis import FileAnalysis
from project_mcp.plugins.rust.dependencies import list_rust_dependencies
from project_mcp.plugins.rust.parser import (
    _module_qualified_name,
    extract_rust_impls,
    extract_rust_use,
    parse_rust_source,
)
from project_mcp.plugins.rust.tree_parser import parse_rust_tree


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
        else:
            symbols = parse_rust_source(path, source)
        module_name = symbols[0]["qualified_name"]
        return FileAnalysis(
            symbols=symbols,
            symbol_edges=[
                (
                    f"{module_name}.{impl['struct']}",
                    f"{module_name}.{impl['trait']}",
                    "implements",
                )
                for impl in extract_rust_impls(path, source)
                if impl["trait"] is not None
            ],
            imports=[use["path"] for use in extract_rust_use(path, source)],
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
