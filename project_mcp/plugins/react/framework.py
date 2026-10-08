"""React as a framework plugin on top of the javascript plugin."""
import json
import os
import re
from pathlib import Path

from project_mcp.plugins.react.pages import is_page_path
from project_mcp.plugins.react.routes import route_declarations
from project_mcp.plugins.react.usages import import_candidates, imported_names, jsx_tags

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
    rows: list[tuple[int, str, int, int]], name: str, default_import: bool
) -> int | None:
    """The component called `name` in a file; a default import falls back to its only component."""
    named = [id_ for id_, component, _, _ in rows if component == name]
    if named:
        return named[0]
    return rows[0][0] if default_import and len(rows) == 1 else None


def _load_components(context) -> dict[str, list[tuple[int, str, int, int]]]:
    """The (id, name, start line, end line) of each component, by the .js/.ts file defining it."""
    components: dict[str, list[tuple[int, str, int, int]]] = {}
    for symbol_id, path, name, start, end in context.conn.execute(
        """
        SELECT s.id, f.path, s.name, s.start_line, s.end_line
        FROM symbols s JOIN files f ON f.id = s.file_id
        WHERE f.project_id = ? AND s.kind = 'component'
        """,
        (context.project_id,),
    ):
        if path.endswith(_EXTENSIONS):
            components.setdefault(path, []).append((symbol_id, name, start, end))
    return components


def _insert_relationship(context, relationship_type: str, source: int, target: int) -> None:
    context.conn.execute(
        """
        INSERT INTO relationships (
            source_entity_type, source_entity_id,
            target_entity_type, target_entity_id,
            relationship_type, confidence
        ) VALUES ('symbol', ?, 'symbol', ?, ?, 'high')
        """,
        (source, target, relationship_type),
    )


def _resolve_component(components, importer: str, imports, tag: str) -> int | None:
    """The project component an imported JSX tag refers to, if any."""
    if tag not in imports:
        return None
    specifier, imported = imports[tag]
    target_path = next(
        (c for c in import_candidates(importer, specifier) if c in components), None
    )
    if target_path is None:
        return None
    return _component_in(
        components[target_path],
        tag if imported == "default" else imported,
        default_import=imported == "default",
    )


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
    def detect(self, context) -> bool:
        """True when package.json declares `react` or a JS/TS file imports it."""
        root = context.project_root
        return _declares_react(root) or _imports_react(root)

    def enrich(self, context) -> None:
        self._tag_components(context)
        self._link_renders(context)
        self._declare_routes(context)

    def _declare_routes(self, context) -> None:
        """Mark components routed by react-router as pages, linked from the declaring code."""
        components = _load_components(context)
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
            imports = imported_names(source)
            for route, tag, line in route_declarations(source):
                target = _resolve_component(components, path, imports, tag)
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
            imports = imported_names(source)
            links = set()
            for tag, line in jsx_tags(source):
                user = next((id_ for id_, _, start, end in rows if start <= line <= end), None)
                if tag not in imports or user is None:
                    continue
                specifier, imported = imports[tag]
                target_path = next(
                    (c for c in import_candidates(path, specifier) if c in components), None
                )
                target = target_path and _component_in(
                    components[target_path],
                    tag if imported == "default" else imported,
                    default_import=imported == "default",
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
