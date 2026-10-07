"""Context pack tools — compact project context for AI clients."""

import logging
from pathlib import Path
from typing import Any

from project_mcp.tools.symbols import (
    find_symbol,
    get_symbol_context,
    get_dependencies,
    get_dependents,
)
from project_mcp.tools.tests import get_tests_for
from project_mcp.tools.git import get_change_history, get_hotspots, get_change_coupling
from project_mcp.tools.legacy import get_legacy_signals
from project_mcp.db import get_connection
from project_mcp.plugins.registry import PluginRegistry, builtin_registry

logger = logging.getLogger(__name__)


def module_name_for(path: str, registry: PluginRegistry | None = None) -> str | None:
    """The module name the plugin owning `path` indexes it as, if any."""
    if registry is None:
        registry = builtin_registry()
    analyzer = registry.analyzer_for(registry.language_for(Path(path)))
    module_name = getattr(analyzer, "module_name", None)
    return module_name(path) if callable(module_name) else None


def _related_test_files(project_root: Path, target: str) -> list[dict]:
    """Test files for the target; packs stay compact, so tests are not named."""
    return [
        {key: value for key, value in row.items() if key not in ("tests", "tests_total")}
        for row in get_tests_for(project_root, target)
    ]


def get_context_for_symbol(project_root: Path, qualified_name: str) -> dict[str, Any]:
    """Get compact context for a specific symbol.

    Args:
        project_root: Project root directory
        qualified_name: Fully qualified symbol name (e.g., 'module.Class.method')

    Returns:
        Context pack with symbol definition, tests, and dependents.
    """
    try:
        # Validate inputs
        if not qualified_name or not isinstance(qualified_name, str):
            logger.warning(f"Invalid qualified_name provided: {qualified_name!r}")
            return {
                "target": qualified_name,
                "type": "symbol",
                "status": "invalid_input",
                "error": "qualified_name must be a non-empty string",
            }

        if not Path(project_root).exists():
            logger.warning(f"Project root does not exist: {project_root}")
            return {
                "target": qualified_name,
                "type": "symbol",
                "status": "error",
                "error": f"Project root does not exist: {project_root}",
            }

        # Get symbol details
        symbol_details = get_symbol_context(project_root, qualified_name)
        if not symbol_details.get("found"):
            return {
                "target": qualified_name,
                "type": "symbol",
                "status": "not_found",
            }

        # Get dependencies and dependents
        deps = get_dependencies(project_root, qualified_name)
        dependents = get_dependents(project_root, qualified_name)
        symbol = symbol_details.get("symbol", {})

        # Truncate results and track total counts
        imports_truncated = deps[:10]
        imports_total = len(deps)
        used_by_truncated = dependents[:10]
        used_by_total = len(dependents)

        return {
            "target": qualified_name,
            "type": "symbol",
            "symbol": symbol,
            "imports": imports_truncated,
            "imports_total": imports_total,
            "is_truncated_imports": imports_total > 10,
            "used_by": used_by_truncated,
            "used_by_total": used_by_total,
            "is_truncated_dependents": used_by_total > 10,
            "related_tests": _related_test_files(project_root, qualified_name),
            "entrypoints": [],
            "dependencies": imports_truncated,
            "summary": f"Symbol {qualified_name} with {used_by_total} dependents",
            "recommended_files_to_open": [symbol.get("file")],
        }
    except Exception as e:
        logger.exception(f"Error getting context for symbol {qualified_name}: {e}")
        return {
            "target": qualified_name,
            "type": "symbol",
            "status": "error",
            "error": f"Failed to get context: {e}",
        }


def get_context_for_feature(project_root: Path, query: str) -> dict[str, Any]:
    """Get context for a feature by query string.

    Args:
        project_root: Project root directory
        query: Feature description or name

    Returns:
        Context pack with related symbols, tests, and entrypoints.
    """
    if not Path(project_root).exists():
        return {
            "target": query,
            "type": "feature",
            "status": "error",
            "error": f"Project root does not exist: {project_root}",
        }

    try:
        matches = find_symbol(project_root, query)
    except Exception as e:
        logger.exception(f"Error getting context for feature {query}: {e}")
        return {
            "target": query,
            "type": "feature",
            "status": "error",
            "error": f"Failed to get context: {e}",
        }
    related_tests = [m["qualified_name"] for m in matches if m["file"].startswith("tests/")]
    related_symbols = [m["qualified_name"] for m in matches if not m["file"].startswith("tests/")]
    files = sorted({m["file"] for m in matches if not m["file"].startswith("tests/")})

    dependencies = []
    for qualified_name in related_symbols[:10]:
        for dep in get_dependencies(project_root, qualified_name):
            if dep not in dependencies:
                dependencies.append(dep)

    return {
        "target": query,
        "type": "feature",
        "related_symbols": related_symbols[:10],
        "related_symbols_total": len(related_symbols),
        "related_tests": related_tests[:10],
        "entrypoints": [],
        "dependencies": dependencies[:10],
        "recommended_files_to_open": files[:10],
        "summary": f"Feature query '{query}' matches {len(related_symbols)} symbol(s) and {len(related_tests)} test(s)",
    }


def get_context_for_bug(project_root: Path, query: str) -> dict[str, Any]:
    """Get context for bug investigation.

    Args:
        project_root: Project root directory
        query: Bug description or affected code

    Returns:
        Context pack with likely problem code, callers, and churn data.
    """
    if not Path(project_root).exists():
        return {
            "target": query,
            "type": "bug",
            "status": "error",
            "error": f"Project root does not exist: {project_root}",
        }

    matches = find_symbol(project_root, query)
    related_symbols = [m["qualified_name"] for m in matches if not m["file"].startswith("tests/")]
    files = sorted({m["file"] for m in matches if not m["file"].startswith("tests/")})

    callers = []
    for qualified_name in related_symbols[:10]:
        for dep in get_dependents(project_root, qualified_name):
            if dep not in callers:
                callers.append(dep)

    hotspot_paths = {h["path"] for h in get_hotspots(project_root)}
    churn = []
    for path in files[:10]:
        history = get_change_history(project_root, path)
        churn.append({
            "path": path,
            "change_count": history["change_count"],
            "high_risk": path in hotspot_paths,
        })

    return {
        "target": query,
        "type": "bug",
        "related_symbols": related_symbols[:10],
        "callers": callers[:10],
        "churn": churn,
        "recommended_files_to_open": files[:10],
        "summary": f"Bug query '{query}' matches {len(related_symbols)} symbol(s)",
    }


def get_context_for_refactor(project_root: Path, target: str) -> dict[str, Any]:
    """Get refactor impact context.

    Args:
        project_root: Project root directory
        target: Symbol or module to refactor

    Returns:
        Context pack with dependents, tests, and co-change patterns.
    """
    if not Path(project_root).exists():
        return {
            "target": target,
            "type": "refactor",
            "status": "error",
            "error": f"Project root does not exist: {project_root}",
        }

    dependents = get_dependents(project_root, target)
    related_tests = _related_test_files(project_root, target)

    symbol_details = get_symbol_context(project_root, target)
    file_path = symbol_details.get("symbol", {}).get("file") if symbol_details.get("found") else None
    temporal_coupling = get_change_coupling(project_root, file_path) if file_path else []

    legacy_signals = get_legacy_signals(project_root, target)
    if file_path and file_path != target:
        legacy_signals = legacy_signals + get_legacy_signals(project_root, file_path)

    return {
        "target": target,
        "type": "refactor",
        "dependents": dependents,
        "related_tests": related_tests,
        "temporal_coupling": temporal_coupling,
        "legacy_signals": legacy_signals,
        "recommended_files_to_open": [file_path] if file_path else [],
        "summary": f"Refactor target '{target}' has {len(dependents)} dependent(s) and {len(related_tests)} test(s)",
    }


def get_context_for_architecture(project_root: Path, area: str) -> dict[str, Any]:
    """Get architecture-relevant context.

    Args:
        project_root: Project root directory
        area: Area of architecture to explore

    Returns:
        Context pack with explicit docs and inferred dependency structure.
    """
    if not Path(project_root).exists():
        return {
            "target": area,
            "type": "architecture",
            "status": "error",
            "error": f"Project root does not exist: {project_root}",
        }

    matches = find_symbol(project_root, area)
    files = sorted({m["file"] for m in matches if not m["file"].startswith("tests/")})

    registry = builtin_registry()
    inferred_structure = []
    for path in files[:10]:
        module_qualified_name = module_name_for(path, registry)
        if module_qualified_name is None:
            continue
        deps = get_dependencies(project_root, module_qualified_name)
        if deps:
            inferred_structure.append({
                "module": path,
                "depends_on": [dep["target"] for dep in deps],
            })

    conn = get_connection(project_root)
    escaped_area = area.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    like_query = f"%{escaped_area}%"
    rows = conn.execute(
        """
        SELECT subject, predicate, object, origin, source FROM architecture_facts
        WHERE LOWER(subject) LIKE ? ESCAPE '\\' OR LOWER(object) LIKE ? ESCAPE '\\'
        """,
        (like_query, like_query),
    ).fetchall()
    explicit_facts = [
        {"subject": subject, "predicate": predicate, "object": obj, "origin": origin, "source": source}
        for subject, predicate, obj, origin, source in rows
    ]

    return {
        "target": area,
        "type": "architecture",
        "structure": {
            "explicit_facts": explicit_facts,
            "inferred_structure": inferred_structure,
        },
        "recommended_files_to_open": files[:10],
        "summary": (
            f"Architecture context for '{area}': {len(explicit_facts)} explicit fact(s), "
            f"{len(inferred_structure)} inferred module(s)"
        ),
    }
