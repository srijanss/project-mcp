"""React as a framework plugin on top of the javascript plugin."""
import json
import os
import re
from pathlib import Path

from project_mcp.plugins import treesitter
from project_mcp.plugins.react import tree_usages, usages
from project_mcp.plugins.react.dynamic import computed_components, dynamic_route_lines, lazy_imports
from project_mcp.plugins.react.exports import default_export_name
from project_mcp.plugins.react.pages import is_page_path
from project_mcp.plugins.react.routes import route_declarations
from project_mcp.plugins.react.usages import import_candidates

_DEPENDENCY_SECTIONS = ("dependencies", "devDependencies", "peerDependencies")
_EXTENSIONS = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")
_SKIPPED_DIRS = {"node_modules", ".git"}
_REACT_IMPORT = re.compile(
    r"""^\s*import\s+(?:[^'";]*?\s+from\s+)?['"]react['"]"""
    r"""|\brequire\(\s*['"]react['"]\s*\)""",
    re.MULTILINE,
)


def _declares_react(root: Path) -> bool:
    try:
        manifest = json.loads((root / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(manifest, dict):
        return False
    return any(
        isinstance(manifest.get(section), dict) and "react" in manifest[section]
        for section in _DEPENDENCY_SECTIONS
    )


def _imports_react(root: Path) -> bool:
    for directory, subdirs, names in os.walk(root):
        subdirs[:] = [name for name in subdirs if name not in _SKIPPED_DIRS]
        for name in names:
            if not name.endswith(_EXTENSIONS):
                continue
            try:
                source = (Path(directory) / name).read_text(encoding="utf-8")
            except (OSError, ValueError):
                continue
            if _REACT_IMPORT.search(source):
                return True
    return False


def _component_in(
    rows: list[tuple[int, str, int, int]], imported: str, default_name: str | None
) -> int | None:
    """The component a file's `imported` export refers to.

    A default import means the file's default export; when that can't be
    read, the file's only component.
    """
    if imported == "default":
        if default_name is None:
            return rows[0][0] if len(rows) == 1 else None
        imported = default_name
    return next((id_ for id_, component, _, _ in rows if component == imported), None)


def _load_components(context) -> dict[str, list[tuple[int, str, int, int]]]:
    """The (id, name, start line, end line) of each component, by the .js/.ts file defining it.

    The regex parser records no end line; a component then runs to the next one.
    """
    components: dict[str, list[tuple[int, str, int, int]]] = {}
    for symbol_id, path, name, start, end in context.conn.execute(
        """
        SELECT s.id, f.path, s.name, s.start_line, s.end_line
        FROM symbols s JOIN files f ON f.id = s.file_id
        WHERE f.project_id = ? AND s.kind = 'component'
        ORDER BY s.start_line
        """,
        (context.project_id,),
    ):
        if path.endswith(_EXTENSIONS):
            components.setdefault(path, []).append((symbol_id, name, start, end))
    for path, rows in components.items():
        ends = [start - 1 for _, _, start, _ in rows[1:]] + [float("inf")]
        components[path] = [
            (id_, name, start, end if end is not None else next_end)
            for (id_, name, start, end), next_end in zip(rows, ends)
        ]
    return components


def _insert_relationship(
    context, relationship_type: str, source: int, target: int, confidence: str = "high"
) -> None:
    context.conn.execute(
        """
        INSERT INTO relationships (
            source_entity_type, source_entity_id,
            target_entity_type, target_entity_id,
            relationship_type, confidence
        ) VALUES ('symbol', ?, 'symbol', ?, ?, ?)
        """,
        (source, target, relationship_type, confidence),
    )


def _resolve_component(components, defaults, importer: str, imports, tag: str) -> int | None:
    """The project component an imported JSX tag refers to, if any."""
    if tag not in imports:
        return None
    specifier, imported = imports[tag]
    target_path = next(
        (c for c in import_candidates(importer, specifier) if c in components), None
    )
    if target_path is None:
        return None
    return _component_in(components[target_path], imported, defaults[target_path])


def _declarer(context, file_id: int, rows, line: int) -> int | None:
    """The component enclosing `line`, else the file's module symbol."""
    enclosing = next((id_ for id_, _, start, end in rows if start <= line <= end), None)
    if enclosing is not None:
        return enclosing
    row = context.conn.execute(
        "SELECT id FROM symbols WHERE file_id = ? AND kind = 'module'", (file_id,)
    ).fetchone()
    return row[0] if row else None


class ReactFramework:
    def __init__(self) -> None:
        problem = (
            treesitter.missing("javascript")
            or treesitter.missing("typescript")
            or treesitter.missing("tsx")
        )
        self.backend = "regex" if problem else "tree-sitter"
        self.warnings = [f"falls back to its regex parser: {problem}"] if problem else []

    def _imported_names(self, path: str, source: str) -> dict[str, tuple[str, str]]:
        if self.backend == "tree-sitter":
            return tree_usages.imported_names(source, tree_usages.grammar_for(path))
        return usages.imported_names(source)

    def _jsx_tags(self, path: str, source: str) -> list[tuple[str, int]]:
        if self.backend == "tree-sitter":
            return tree_usages.jsx_tags(source, tree_usages.grammar_for(path))
        return usages.jsx_tags(source)

    def _default_export_name(self, path: str, source: str) -> str | None:
        if self.backend == "tree-sitter":
            return tree_usages.default_export_name(source, tree_usages.grammar_for(path))
        return default_export_name(source)

    def _default_exports(self, context, components) -> dict[str, str | None]:
        """The default-exported name of each file that defines components."""
        defaults: dict[str, str | None] = {}
        for path in components:
            try:
                source = (Path(context.project_root) / path).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                source = ""
            defaults[path] = self._default_export_name(path, source)
        return defaults

    def detect(self, context) -> bool:
        """True when package.json declares `react` or a JS/TS file imports it."""
        root = context.project_root
        return _declares_react(root) or _imports_react(root)

    def enrich(self, context) -> None:
        self._tag_components(context)
        self._link_renders(context)
        self._declare_routes(context)
        self._link_dynamic(context)

    def _link_dynamic(self, context) -> None:
        """Record lazy and computed components with low confidence, marking their users partial."""
        components = _load_components(context)
        defaults = self._default_exports(context, components)
        context.conn.executemany(
            "UPDATE symbols SET metadata_json = json_remove(metadata_json, '$.partial')"
            " WHERE id = ?",
            [(row[0],) for rows in components.values() for row in rows],
        )
        partial: set[int] = set()
        links: set[tuple[int, int]] = set()
        for path, file_id in context.path_to_file_id.items():
            if not path.endswith(_EXTENSIONS):
                continue
            try:
                source = (Path(context.project_root) / path).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            rows = components.get(path, [])
            imports = self._imported_names(path, source)
            lazy = {name: (module, "default") for name, module in lazy_imports(source).items()}
            computed = computed_components(source)
            for tag, line in self._jsx_tags(path, source):
                user = _declarer(context, file_id, rows, line)
                if user is None or (tag not in lazy and tag not in computed):
                    continue
                partial.add(user)
                for name in [tag] if tag in lazy else computed[tag]:
                    target = _resolve_component(components, defaults, path, {**imports, **lazy}, name)
                    if target is not None and target != user:
                        links.add((user, target))
            for line in dynamic_route_lines(source):
                declarer = _declarer(context, file_id, rows, line)
                if declarer is not None:
                    partial.add(declarer)
        for symbol_id in partial:
            context.conn.execute(
                "UPDATE symbols SET metadata_json = json_set(COALESCE(metadata_json, '{}'),"
                " '$.partial', json('true')) WHERE id = ?",
                (symbol_id,),
            )
        for user, target in sorted(links):
            _insert_relationship(context, "renders", user, target, confidence="low")

    def _declare_routes(self, context) -> None:
        """Mark components routed by react-router as pages, linked from the declaring code."""
        components = _load_components(context)
        defaults = self._default_exports(context, components)
        context.conn.executemany(
            "UPDATE symbols SET metadata_json = json_remove(metadata_json, '$.routes')"
            " WHERE id = ?",
            [(row[0],) for rows in components.values() for row in rows],
        )
        context.conn.execute(
            "DELETE FROM relationships WHERE relationship_type = 'routes_to'"
            " AND source_entity_type = 'symbol'"
            " AND source_entity_id IN (SELECT s.id FROM symbols s JOIN files f"
            " ON f.id = s.file_id WHERE f.project_id = ?)",
            (context.project_id,),
        )
        routes: dict[int, set[str]] = {}
        links: set[tuple[int, int]] = set()
        for path, file_id in context.path_to_file_id.items():
            if not path.endswith(_EXTENSIONS):
                continue
            try:
                source = (Path(context.project_root) / path).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            imports = self._imported_names(path, source)
            for route, tag, line in route_declarations(source):
                target = _resolve_component(components, defaults, path, imports, tag)
                declarer = _declarer(context, file_id, components.get(path, []), line)
                if target is None or declarer is None:
                    continue
                routes.setdefault(target, set()).add(route)
                links.add((declarer, target))
        for target, paths in routes.items():
            context.conn.execute(
                "UPDATE symbols SET metadata_json = json_set(COALESCE(metadata_json, '{}'),"
                " '$.framework_kind', 'react_page', '$.routes', json(?)) WHERE id = ?",
                (json.dumps(sorted(paths)), target),
            )
        for declarer, target in sorted(links):
            _insert_relationship(context, "routes_to", declarer, target)

    def _link_renders(self, context) -> None:
        """Link each component to the imported project components its JSX renders."""
        components = _load_components(context)
        defaults = self._default_exports(context, components)
        context.conn.executemany(
            "DELETE FROM relationships WHERE relationship_type = 'renders'"
            " AND source_entity_type = 'symbol' AND source_entity_id = ?",
            [(row[0],) for rows in components.values() for row in rows],
        )
        for path, rows in components.items():
            try:
                source = (Path(context.project_root) / path).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            imports = self._imported_names(path, source)
            links = set()
            for tag, line in self._jsx_tags(path, source):
                user = next((id_ for id_, _, start, end in rows if start <= line <= end), None)
                if tag not in imports or user is None:
                    continue
                specifier, imported = imports[tag]
                target_path = next(
                    (c for c in import_candidates(path, specifier) if c in components), None
                )
                target = target_path and _component_in(
                    components[target_path], imported, defaults[target_path]
                )
                if target is not None and target != user:
                    links.add((user, target))
            for user, target in sorted(links):
                _insert_relationship(context, "renders", user, target)

    def _tag_components(self, context) -> None:
        """Tag the components the javascript plugin found in .js/.ts files, as pages in page locations."""
        for path, file_id in context.path_to_file_id.items():
            if not path.endswith(_EXTENSIONS):
                continue
            framework_kind = "react_page" if is_page_path(path) else "react_component"
            context.conn.execute(
                """
                UPDATE symbols SET metadata_json = json_set(
                    COALESCE(metadata_json, '{}'), '$.framework_kind', ?
                )
                WHERE file_id = ? AND kind = 'component'
                """,
                (framework_kind, file_id),
            )
