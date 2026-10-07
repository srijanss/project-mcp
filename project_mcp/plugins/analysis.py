from dataclasses import dataclass, field


@dataclass
class FileAnalysis:
    """What a language analyzer found in one file, in core's common format.

    `symbols` are dicts with name, qualified_name, kind, start_line,
    end_line and visibility. `symbol_edges` are (source qualified name,
    target qualified name, relationship type) between symbols of this file.
    `imports` are module specifiers, resolved to files by the analyzer's
    resolve_import once every file is known.
    """

    symbols: list[dict] = field(default_factory=list)
    symbol_edges: list[tuple[str, str, str]] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
