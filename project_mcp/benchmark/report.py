"""MVP14 benchmark runner: wires the naive-baseline (Approach A) and
context-pack (Approach B) measurements together into a single report.
"""

import argparse
import json
from typing import Any

from project_mcp.benchmark.corpus import TASKS
from project_mcp.benchmark.naive_baseline import measure_naive_baseline
from project_mcp.benchmark.context_pack_measurement import measure_context_pack


def _reduction_pct(naive: int, pack: int) -> float:
    if naive == 0:
        return 0.0
    return (naive - pack) / naive * 100


def build_report(tasks=TASKS) -> dict[str, Any]:
    per_task = []
    for task in tasks:
        naive = measure_naive_baseline(task)
        pack = measure_context_pack(task)
        per_task.append({
            "task_name": task.name,
            "task_type": task.task_type,
            "naive_files_opened": len(naive.files_opened),
            "naive_bytes": naive.total_bytes,
            "naive_tokens_proxy": naive.total_tokens_proxy,
            "pack_files_opened": len(pack.recommended_files),
            "pack_bytes": pack.pack_bytes,
            "pack_tokens_proxy": pack.pack_tokens_proxy,
            "file_reduction_pct": _reduction_pct(len(naive.files_opened), len(pack.recommended_files)),
            "byte_reduction_pct": _reduction_pct(naive.total_bytes, pack.pack_bytes),
            "token_reduction_pct": _reduction_pct(naive.total_tokens_proxy, pack.pack_tokens_proxy),
            "precision": pack.precision,
            "recall": pack.recall,
        })

    if per_task:
        aggregate = {
            "avg_file_reduction_pct": sum(e["file_reduction_pct"] for e in per_task) / len(per_task),
            "avg_byte_reduction_pct": sum(e["byte_reduction_pct"] for e in per_task) / len(per_task),
            "avg_token_reduction_pct": sum(e["token_reduction_pct"] for e in per_task) / len(per_task),
            "avg_precision": sum(e["precision"] for e in per_task) / len(per_task),
            "avg_recall": sum(e["recall"] for e in per_task) / len(per_task),
        }
    else:
        aggregate = {
            "avg_file_reduction_pct": 0.0,
            "avg_byte_reduction_pct": 0.0,
            "avg_token_reduction_pct": 0.0,
            "avg_precision": 0.0,
            "avg_recall": 0.0,
        }

    return {"per_task": per_task, "aggregate": aggregate}


def main(argv: list[str] | None = None) -> None:
    argparse.ArgumentParser(description="Run the MVP14 token-efficiency benchmark.").parse_args(argv)
    print(json.dumps(build_report(), indent=2))
