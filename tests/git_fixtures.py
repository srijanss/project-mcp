"""Build deterministic git fixture repositories on demand.

Nested ``.git`` directories can't be committed (git records them as empty
gitlinks), so the history-based fixtures are scripted here instead.
"""

import os
import subprocess
from pathlib import Path

# Each commit: (message, {filename: content}). The first commit is the initial one.
_FIXTURES: dict[str, list[tuple[str, dict[str, str]]]] = {
    "churn-fixture": [
        ("initial", {"file1.py": "file1\n"}),
        ("change 1", {"file1.py": "file1 v2\n"}),
        ("change 2", {"file1.py": "file1 v3\n"}),
        ("change 3", {"file1.py": "file1 v4\n"}),
    ],
    "coupling-fixture": [
        ("initial", {"a.py": "a\n", "b.py": "b\n"}),
        ("change a and b 1", {"a.py": "a1\n", "b.py": "b1\n"}),
        ("change a and b 2", {"a.py": "a2\n", "b.py": "b2\n"}),
        ("change a only", {"a.py": "a3\n"}),
        ("change a and b 3", {"a.py": "a4\n", "b.py": "b3\n"}),
    ],
}


def build_git_fixture(fixture_name: str, dest_root: Path) -> Path:
    """Create ``dest_root / fixture_name`` as a git repo with scripted history."""
    repo = dest_root / fixture_name
    repo.mkdir(parents=True)
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
    }

    def git(*args: str) -> None:
        subprocess.run(
            ["git", *args], cwd=repo, env=env, check=True, capture_output=True
        )

    git("init", "-q", "-b", "main")
    for index, (message, files) in enumerate(_FIXTURES[fixture_name]):
        for name, content in files.items():
            (repo / name).write_text(content)
        git("add", "-A")
        date = f"2026-01-01T00:00:{index:02d}+0000"
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
        git("commit", "-q", "-m", message)
    return repo
