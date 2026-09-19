"""Detection of explicit architecture doc sources (MVP 10)."""

import re
from pathlib import Path

from project_mcp.config import ProjectConfig

_ARCHITECTURE_HEADING_RE = re.compile(r"^#{1,6}\s+architecture\b", re.IGNORECASE | re.MULTILINE)
_HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)


def detect_architecture_doc_sources(
    project_root: Path, config: ProjectConfig | None = None
) -> list[dict]:
    """Detect which explicit architecture doc sources exist in a project.

    Pure detection only — which files/sections exist, no fact extraction.

    Args:
        project_root: Project root directory
        config: Project config; when given, config.architecture_docs adds configured paths

    Returns:
        List of {"path": relative_path, "kind": source_kind} dicts.
    """
    project_root = Path(project_root)
    sources: list[dict] = []

    sources.extend(_scan_dir(project_root, project_root / "docs" / "architecture", "docs_architecture"))
    sources.extend(_scan_dir(project_root, project_root / "docs" / "adr", "docs_adr"))
    sources.extend(_scan_glob(project_root, "ADR*.md", "adr_file"))

    readme = project_root / "README.md"
    if readme.is_file():
        readme_text = _read_text_safe(readme)
        if readme_text is not None and _ARCHITECTURE_HEADING_RE.search(readme_text):
            sources.append({"path": "README.md", "kind": "readme_architecture_section"})

    if config is not None:
        for configured_path in config.architecture_docs:
            if (project_root / configured_path).is_file():
                sources.append({"path": configured_path, "kind": "configured_path"})

    return sources


def extract_architecture_facts(project_root: Path, sources: list[dict]) -> list[dict]:
    """Extract simple heading-based architecture facts from detected doc sources.

    Simple extraction only — headings become facts, no LLM inference of
    arbitrary document content (per MVP10 spec).

    Args:
        project_root: Project root directory
        sources: Doc sources as returned by detect_architecture_doc_sources

    Returns:
        List of {"subject", "predicate", "object", "origin", "source"} dicts
        matching the architecture_facts schema.
    """
    project_root = Path(project_root)
    facts: list[dict] = []

    for source in sources:
        doc_path = project_root / source["path"]
        if not doc_path.is_file():
            continue
        doc_text = _read_text_safe(doc_path)
        if doc_text is None:
            continue
        object_name = source["path"]
        for heading in _HEADING_RE.findall(doc_text):
            facts.append({
                "subject": heading,
                "predicate": "documented_in",
                "object": object_name,
                "origin": "explicit",
                "source": source["path"],
            })

    return facts


def _read_text_safe(path: Path) -> str | None:
    try:
        return path.read_text()
    except UnicodeDecodeError:
        return None


def _scan_dir(project_root: Path, directory: Path, kind: str) -> list[dict]:
    if not directory.is_dir():
        return []
    return [
        {"path": str(doc_file.relative_to(project_root)), "kind": kind}
        for doc_file in sorted(directory.rglob("*.md"))
    ]


def _scan_glob(project_root: Path, pattern: str, kind: str) -> list[dict]:
    return [
        {"path": str(doc_file.relative_to(project_root)), "kind": kind}
        for doc_file in sorted(project_root.glob(pattern))
    ]
