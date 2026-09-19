"""Spec-named git history tool wrappers — get_change_history, get_hotspots, get_change_coupling."""

from pathlib import Path

from project_mcp.analyzers.generic.git import (
    get_file_change_count,
    get_file_last_changed,
    get_files_changed_together,
    get_hotspots as _get_hotspots,
)
from project_mcp.config import load_config


def get_change_history(project_root: Path, path: str) -> dict:
    config = load_config(project_root)
    return {
        "change_count": get_file_change_count(project_root, path, config=config),
        "last_changed": get_file_last_changed(project_root, path),
    }


def get_hotspots(project_root: Path) -> list[dict]:
    config = load_config(project_root)
    return _get_hotspots(project_root, config=config)


def get_change_coupling(project_root: Path, path: str) -> list[dict]:
    config = load_config(project_root)
    return get_files_changed_together(project_root, path, config=config)
