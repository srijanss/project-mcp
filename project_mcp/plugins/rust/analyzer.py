from pathlib import Path

from project_mcp.plugins.analysis import FileAnalysis
from project_mcp.plugins.rust.parser import (
    _module_qualified_name,
    extract_rust_impls,
    extract_rust_use,
    parse_rust_source,
)


class RustAnalyzer:
    def module_name(self, path: str) -> str:
        """The qualified name of the module symbol this file is indexed as."""
        return _module_qualified_name(path)

    def is_test_file(self, path: Path) -> bool:
        path = Path(path)
        in_test_dir = bool({"tests", "test"} & set(path.parts[:-1]))
        return in_test_dir or path.stem.startswith("test_") or path.stem.endswith("_test")

    def analyze(self, path: str, source: str) -> FileAnalysis:
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
