from dataclasses import dataclass, field


@dataclass
class FileAnalysis:
    """What a language analyzer found in one file, in core's common format.

    `symbols` are dicts with name, qualified_name, kind, start_line,
    end_line and visibility, plus an optional `metadata` dict stored as
    JSON. `symbol_edges` are (source qualified name, target qualified name,
    relationship type) between symbols of this file.
    `imports` are the analyzer's own import specs (module specifiers, or
    any value it chooses); core only hands each back to the
    analyzer's resolve_import once every file is known. `extra` is the
    analyzer's private data about the file (e.g. its full parse), which
    core keeps for the analyzer's own later linking and never reads.
    """

    symbols: list[dict] = field(default_factory=list)
    symbol_edges: list[tuple[str, str, str]] = field(default_factory=list)
    imports: list = field(default_factory=list)
    extra: object = None
