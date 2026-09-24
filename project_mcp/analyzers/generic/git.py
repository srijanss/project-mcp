"""Git history analysis — churn, hotspots, and temporal coupling."""

import subprocess
from pathlib import Path

from project_mcp.config import ProjectConfig


def get_file_change_count(
    project_root: Path,
    file_path: str,
    limit: int = 100,
    config: ProjectConfig | None = None,
) -> int:
    """Count how many times a file has been changed in recent history.

    Args:
        project_root: Repository root
        file_path: Relative path to the file
        limit: Maximum number of commits to examine (ignored if config is given)
        config: Project config; when given, config.git_history_limit overrides limit

    Returns:
        Number of commits touching this file (0 if file not in git or no history)
    """
    if config is not None:
        limit = config.git_history_limit
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", f"-n{limit}", "--", file_path],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return 0
        # Count non-empty lines (each line is one commit)
        return len([line for line in result.stdout.strip().split("\n") if line])
    except (FileNotFoundError, subprocess.SubprocessError):
        return 0


def get_file_last_changed(project_root: Path, file_path: str) -> str | None:
    """Get the date when a file was last modified.

    Args:
        project_root: Repository root
        file_path: Relative path to the file

    Returns:
        ISO format date string or None if not in git/no history
    """
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%aI", "--", file_path],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        return result.stdout.strip()
    except (FileNotFoundError, subprocess.SubprocessError):
        return None


def collect_git_file_stats(
    project_root: Path,
    paths: list[str],
    limit: int = 100,
    config: ProjectConfig | None = None,
) -> dict[str, dict]:
    """Change count, last change date and co-changed file count for many files.

    Reads the history once, instead of the three `git log` runs per file that
    get_file_change_count, get_file_last_changed and get_files_changed_together
    need, and reports the same values they do.

    Returns:
        {path: {"change_count", "last_changed", "coupled_file_count"}}
    """
    if config is not None:
        limit = config.git_history_limit
    wanted = set(paths)
    change_counts = dict.fromkeys(wanted, 0)
    last_changed: dict[str, str] = {}
    coupled: dict[str, set[str]] = {path: set() for path in wanted}

    for position, (date, files) in enumerate(_read_git_history(project_root)):
        in_window = position < limit
        for file in files & wanted:
            if change_counts[file] < limit:
                change_counts[file] += 1
            last_changed.setdefault(file, date)
            if in_window:
                coupled[file].update(files)

    return {
        path: {
            "change_count": change_counts[path],
            "last_changed": last_changed.get(path),
            "coupled_file_count": len(coupled[path] - {path}),
        }
        for path in paths
    }


_COMMIT_MARKER = "\x00"


def _read_git_history(project_root: Path) -> list[tuple[str, set[str]]]:
    """Every commit, newest first, as (author date, files changed)."""
    try:
        result = subprocess.run(
            # %x00 makes git print the NUL marker, which no path can contain.
            ["git", "log", "--name-only", "--format=%x00%aI"],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, NotADirectoryError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []

    commits: list[tuple[str, set[str]]] = []
    for line in result.stdout.split("\n"):
        if line.startswith(_COMMIT_MARKER):
            commits.append((line[len(_COMMIT_MARKER):].strip(), set()))
        elif commits and line.strip():
            commits[-1][1].add(line.strip())
    return commits


def get_hotspots(
    project_root: Path,
    limit: int = 100,
    threshold: int = 5,
    config: ProjectConfig | None = None,
) -> list[dict]:
    """Identify high-churn files (hotspots).

    Args:
        project_root: Repository root
        limit: Maximum commits to examine (ignored if config is given)
        threshold: Minimum change count to be considered a hotspot
        config: Project config; when given, config.git_history_limit overrides limit

    Returns:
        List of hotspot dicts with path, change_count, and last_changed.
    """
    if config is not None:
        limit = config.git_history_limit
    try:
        result = subprocess.run(
            ["git", "log", "--name-only", "--pretty=format:", f"-n{limit}"],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return []

        # Count changes per file
        churn = {}
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if line and not line.startswith(".git"):
                churn[line] = churn.get(line, 0) + 1

        # Filter by threshold and sort by frequency
        hotspots = [
            {
                "path": path,
                "change_count": count,
                "last_changed": get_file_last_changed(project_root, path),
            }
            for path, count in sorted(churn.items(), key=lambda x: x[1], reverse=True)
            if count >= threshold
        ]
        return hotspots
    except (FileNotFoundError, subprocess.SubprocessError):
        return []


def get_files_changed_together(
    project_root: Path,
    target_path: str,
    limit: int = 100,
    config: ProjectConfig | None = None,
) -> list[dict]:
    """Find files changed together with a target file (temporal coupling).

    Args:
        project_root: Repository root
        target_path: Relative path to the target file
        limit: Maximum commits to examine (ignored if config is given)
        config: Project config; when given, config.git_history_limit overrides limit

    Returns:
        List of co-changed files with coupling frequency/confidence.
    """
    if config is not None:
        limit = config.git_history_limit
    try:
        # Get all commits with all files they changed (no filtering yet)
        result = subprocess.run(
            ["git", "log", "--name-only", "--pretty=format:%H", f"-n{limit}"],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return []

        lines = result.stdout.strip().split("\n")
        commits = []
        current_commit = None
        files_in_commit = []

        for line in lines:
            line = line.strip()
            if not line:
                continue
            # Lines that look like commit hashes (40 hex chars)
            if len(line) == 40 and all(c in "0123456789abcdef" for c in line):
                if current_commit and files_in_commit:
                    commits.append((current_commit, files_in_commit))
                current_commit = line
                files_in_commit = []
            else:
                if current_commit:
                    files_in_commit.append(line)

        if current_commit and files_in_commit:
            commits.append((current_commit, files_in_commit))

        # Find commits that touched the target and count co-occurrences
        coupling = {}
        target_commit_count = 0

        for commit, files in commits:
            # Check if target file is in this commit
            if any(f.strip() == target_path for f in files):
                target_commit_count += 1
                # Count other files in this commit
                for file in files:
                    file = file.strip()
                    if file and file != target_path:
                        coupling[file] = coupling.get(file, 0) + 1

        # Sort by frequency and calculate confidence
        result_list = []
        for file, count in sorted(coupling.items(), key=lambda x: x[1], reverse=True):
            if target_commit_count > 0:
                confidence = count / target_commit_count
                result_list.append({
                    "file": file,
                    "co_changes": count,
                    "confidence": confidence,
                    "label": f"{count} / {target_commit_count} recent changes",
                })

        return result_list
    except (FileNotFoundError, subprocess.SubprocessError):
        return []
