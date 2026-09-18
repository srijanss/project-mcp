import shutil
from pathlib import Path

from project_mcp.analyzers.generic.filesystem import classify_file, discover_files
from project_mcp.config import load_config

FIXTURE_ROOT = (
    Path(__file__).resolve().parents[1] / "fixtures" / "python" / "sample_project"
)


def _copy_fixture(tmp_path: Path) -> Path:
    project_root = tmp_path / "sample_project"
    shutil.copytree(FIXTURE_ROOT, project_root)
    return project_root


def test_classifies_python_source_file():
    result = classify_file(Path("app/models.py"))
    assert result == {"language": "python", "file_kind": "source"}


def test_classifies_pytest_style_test_file_by_prefix():
    result = classify_file(Path("tests/test_models.py"))
    assert result == {"language": "python", "file_kind": "test"}


def test_classifies_test_file_by_suffix():
    result = classify_file(Path("app/models_test.py"))
    assert result == {"language": "python", "file_kind": "test"}


def test_classifies_manifest_as_config():
    result = classify_file(Path("pyproject.toml"))
    assert result == {"language": "toml", "file_kind": "config"}


def test_classifies_cfg_file_as_config():
    result = classify_file(Path("setup.cfg"))
    assert result == {"language": "ini", "file_kind": "config"}


def test_classifies_markdown_as_docs():
    result = classify_file(Path("README.md"))
    assert result == {"language": "markdown", "file_kind": "docs"}


def test_classifies_unknown_extension_as_source_with_no_language():
    result = classify_file(Path("app/data.bin"))
    assert result == {"language": None, "file_kind": "source"}


def test_discover_files_finds_expected_project_files(tmp_path):
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)

    records = discover_files(project_root, config)
    paths = {record["path"] for record in records}

    assert "app/models.py" in paths
    assert "tests/test_models.py" in paths
    assert "pyproject.toml" in paths
    assert "README.md" in paths


def test_discover_files_excludes_generated_and_vendor_dirs(tmp_path):
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)

    records = discover_files(project_root, config)
    paths = {record["path"] for record in records}

    assert not any(path.startswith(".venv/") for path in paths)
    assert not any(path.startswith("node_modules/") for path in paths)
    assert not any(path.startswith("target/") for path in paths)
    assert not any(path.startswith(".project-mcp/") for path in paths)


def test_discover_files_returns_classification_and_stat_fields(tmp_path):
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)

    records = discover_files(project_root, config)
    by_path = {record["path"]: record for record in records}

    models_record = by_path["app/models.py"]
    assert models_record["language"] == "python"
    assert models_record["file_kind"] == "source"
    assert models_record["size"] > 0
    assert isinstance(models_record["mtime_ns"], int)

    test_record = by_path["tests/test_models.py"]
    assert test_record["file_kind"] == "test"
