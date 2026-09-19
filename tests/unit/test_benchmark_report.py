"""Tests for the MVP14 benchmark report runner."""

import json

from project_mcp.benchmark.corpus import TASKS
from project_mcp.benchmark.report import build_report, main


class TestBenchmarkReport:
    """Wires the naive-baseline and context-pack measurements together
    into a single per-task and aggregate report."""

    def test_reports_one_entry_per_task_with_reduction_percentages(self):
        report = build_report()

        assert len(report["per_task"]) == len(TASKS)
        for entry in report["per_task"]:
            assert entry["token_reduction_pct"] > 0
            assert 0.0 <= entry["precision"] <= 1.0
            assert 0.0 <= entry["recall"] <= 1.0

    def test_aggregate_summarizes_average_token_reduction(self):
        report = build_report()

        assert 0.0 < report["aggregate"]["avg_token_reduction_pct"] <= 100.0

    def test_main_prints_the_report_as_json(self, capsys):
        main([])

        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert len(parsed["per_task"]) == len(TASKS)

    def test_handles_an_empty_task_list_without_raising(self):
        report = build_report(tasks=())

        assert report["per_task"] == []
        assert report["aggregate"]["avg_token_reduction_pct"] == 0.0
