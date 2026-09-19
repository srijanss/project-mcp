"""Approach A: naive-exploration baseline for the MVP14 benchmark.

Models a coding agent without Project MCP: given a task, it doesn't know
which files are relevant, so it opens every file under the directories
that contain the task's ground-truth files.

Token counts use a whitespace-split proxy, not a real tokenizer — this is
tokenizer-agnostic and documented as an approximation, not a true token
count.
"""

from dataclasses import dataclass

from project_mcp.benchmark.corpus import FIXTURE_PROJECT_ROOT, BenchmarkTask

_IGNORED_DIR_NAMES = {"__pycache__"}


@dataclass(frozen=True)
class NaiveBaselineMeasurement:
    task_name: str
    files_opened: tuple[str, ...]
    total_bytes: int
    total_tokens_proxy: int


def _scope_dirs(task: BenchmarkTask) -> set[str]:
    return {
        relative_path.rsplit("/", 1)[0] if "/" in relative_path else "."
        for relative_path in task.relevant_files
    }


def measure_naive_baseline(task: BenchmarkTask) -> NaiveBaselineMeasurement:
    files_opened = []
    total_bytes = 0
    total_tokens_proxy = 0

    for scope_dir in sorted(_scope_dirs(task)):
        scope_path = FIXTURE_PROJECT_ROOT / scope_dir
        for file_path in sorted(scope_path.iterdir()):
            if not file_path.is_file():
                continue
            if any(part in _IGNORED_DIR_NAMES for part in file_path.parts):
                continue
            try:
                text = file_path.read_text()
            except UnicodeDecodeError:
                continue
            relative = file_path.relative_to(FIXTURE_PROJECT_ROOT).as_posix()
            files_opened.append(relative)
            total_bytes += len(text.encode("utf-8"))
            total_tokens_proxy += len(text.split())

    return NaiveBaselineMeasurement(
        task_name=task.name,
        files_opened=tuple(files_opened),
        total_bytes=total_bytes,
        total_tokens_proxy=total_tokens_proxy,
    )
