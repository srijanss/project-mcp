"""Approach B: Project MCP-assisted measurement for the MVP14 benchmark.

Calls the task's declared get_context_for_* tool and measures the
resulting context pack's size (using the same whitespace-token proxy as
the naive baseline, for a like-for-like comparison) plus precision/recall
of recommended_files_to_open against the task's ground-truth file set.
"""

import json
from dataclasses import dataclass

from project_mcp.benchmark.corpus import FIXTURE_PROJECT_ROOT, BenchmarkTask
from project_mcp.tools import context_packs


@dataclass(frozen=True)
class ContextPackMeasurement:
    task_name: str
    recommended_files: tuple[str, ...]
    precision: float
    recall: float
    pack_bytes: int
    pack_tokens_proxy: int


def measure_context_pack(task: BenchmarkTask) -> ContextPackMeasurement:
    tool = getattr(context_packs, task.context_pack_tool, None)
    if tool is None:
        raise ValueError(
            f"unknown context_pack_tool '{task.context_pack_tool}' for task '{task.name}'"
        )
    pack = tool(FIXTURE_PROJECT_ROOT, **task.context_pack_args)

    if "recommended_files_to_open" not in pack:
        raise RuntimeError(
            f"context pack tool '{task.context_pack_tool}' failed for task "
            f"'{task.name}': {pack}"
        )

    recommended_files = tuple(
        f for f in pack.get("recommended_files_to_open", []) if f
    )
    relevant = task.relevant_files
    recommended_set = set(recommended_files)
    overlap = len(recommended_set & relevant)

    precision = overlap / len(recommended_set) if recommended_set else 0.0
    recall = overlap / len(relevant) if relevant else 0.0

    pack_text = json.dumps(pack)

    return ContextPackMeasurement(
        task_name=task.name,
        recommended_files=recommended_files,
        precision=precision,
        recall=recall,
        pack_bytes=len(pack_text.encode("utf-8")),
        pack_tokens_proxy=len(pack_text.split()),
    )
