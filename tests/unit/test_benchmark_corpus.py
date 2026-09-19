"""Tests for the MVP14 benchmark task corpus."""

from pathlib import Path

from project_mcp.benchmark.corpus import TASKS, FIXTURE_PROJECT_ROOT

EXPECTED_TASK_TYPES = {
    "find_symbol_location",
    "find_related_tests",
    "understand_legacy_module",
    "identify_bug_relevant_files",
    "prepare_architecture_context",
}


class TestBenchmarkCorpus:
    """A small hand-labeled corpus of MVP14 benchmark tasks."""

    def test_covers_every_spec_task_type_exactly_once(self):
        task_types = [task.task_type for task in TASKS]
        assert set(task_types) == EXPECTED_TASK_TYPES
        assert len(task_types) == len(EXPECTED_TASK_TYPES)

    def test_every_relevant_file_exists_in_the_fixture_project(self):
        for task in TASKS:
            for relative_path in task.relevant_files:
                assert (FIXTURE_PROJECT_ROOT / relative_path).is_file(), (
                    f"{task.name}: {relative_path} does not exist"
                )

    def test_every_task_has_a_non_empty_ground_truth_set(self):
        for task in TASKS:
            assert len(task.relevant_files) > 0
