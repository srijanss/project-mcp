"""Context pack tools — compact project context for AI clients."""

import logging
from pathlib import Path
from typing import Any

from project_mcp.tools.symbols import (
    get_symbol_context,
    get_dependencies,
    get_dependents,
)

logger = logging.getLogger(__name__)


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
            "related_tests": [],
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
    return {
        "target": query,
        "type": "feature",
        "status": "not_implemented",
    }


def get_context_for_bug(project_root: Path, query: str) -> dict[str, Any]:
    """Get context for bug investigation.

    Args:
        project_root: Project root directory
        query: Bug description or affected code

    Returns:
        Context pack with likely problem code, callers, and churn data.
    """
    return {
        "target": query,
        "type": "bug",
        "status": "not_implemented",
    }


def get_context_for_refactor(project_root: Path, target: str) -> dict[str, Any]:
    """Get refactor impact context.

    Args:
        project_root: Project root directory
        target: Symbol or module to refactor

    Returns:
        Context pack with dependents, tests, and co-change patterns.
    """
    return {
        "target": target,
        "type": "refactor",
        "status": "not_implemented",
    }


def get_context_for_architecture(project_root: Path, area: str) -> dict[str, Any]:
    """Get architecture-relevant context.

    Args:
        project_root: Project root directory
        area: Area of architecture to explore

    Returns:
        Context pack with explicit docs and inferred dependency structure.
    """
    return {
        "target": area,
        "type": "architecture",
        "status": "not_implemented",
    }
