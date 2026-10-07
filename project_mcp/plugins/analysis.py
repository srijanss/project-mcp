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


@dataclass
class ChangedFile:
    """A file indexed in this run, with the analysis its plugin made of it."""

    file_id: int
    source: str
    analysis: FileAnalysis


@dataclass
class LinkContext:
    """What a plugin's link hooks get once every changed file is written.

    `changed` holds this plugin's files indexed in this run, `added` the
    ones among them that are new, and `plugin_paths` every indexed file of
    this plugin, changed or not.
    """

    conn: object
    project_root: object
    source_roots: list[str]
    path_to_file_id: dict[str, int]
    changed: dict[str, ChangedFile]
    added: set[str]
    plugin_paths: list[str]
