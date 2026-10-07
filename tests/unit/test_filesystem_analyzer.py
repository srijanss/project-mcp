import os
import shutil
from pathlib import Path

from project_mcp.analyzers.generic import filesystem
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


def test_classifies_js_source_file():
    result = classify_file(Path("app/widget.js"))
    assert result == {"language": "javascript", "file_kind": "source"}


def test_classifies_jsx_source_file():
    result = classify_file(Path("app/Widget.jsx"))
    assert result == {"language": "javascript", "file_kind": "source"}


def test_classifies_ts_source_file():
    result = classify_file(Path("app/widget.ts"))
    assert result == {"language": "typescript", "file_kind": "source"}


def test_classifies_tsx_source_file():
    result = classify_file(Path("app/Widget.tsx"))
    assert result == {"language": "typescript", "file_kind": "source"}


def test_classifies_js_test_file_by_suffix():
    result = classify_file(Path("app/widget.test.js"))
    assert result == {"language": "javascript", "file_kind": "test"}


def test_classifies_js_spec_file_by_suffix():
    result = classify_file(Path("app/widget.spec.ts"))
    assert result == {"language": "typescript", "file_kind": "test"}


def test_classifies_unknown_extension_as_source_with_no_language():
    result = classify_file(Path("app/data.bin"))
    assert result == {"language": None, "file_kind": "source"}


def test_classifies_rs_source_file():
    result = classify_file(Path("src/widget.rs"))
    assert result == {"language": "rust", "file_kind": "source"}


def test_classifies_rs_test_file_by_tests_dir():
    result = classify_file(Path("tests/widget_test.rs"))
    assert result == {"language": "rust", "file_kind": "test"}


def test_classifies_rs_test_file_by_prefix():
    result = classify_file(Path("src/test_widget.rs"))
    assert result == {"language": "rust", "file_kind": "test"}


def test_classifies_rs_test_file_by_suffix():
    result = classify_file(Path("src/widget_test.rs"))
    assert result == {"language": "rust", "file_kind": "test"}


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


def test_discover_files_prunes_excluded_dirs_without_descending_into_them(
    tmp_path, monkeypatch
):
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)

    visited_dirs = []
    real_walk = os.walk

    def spy_walk(top, *args, **kwargs):
        for dirpath, dirnames, filenames in real_walk(top, *args, **kwargs):
            visited_dirs.append(Path(dirpath).relative_to(project_root))
            yield dirpath, dirnames, filenames

    monkeypatch.setattr(filesystem.os, "walk", spy_walk)

    discover_files(project_root, config)

    assert not any("node_modules" in path.parts for path in visited_dirs)
    assert not any("target" in path.parts for path in visited_dirs)
    assert Path(".") in visited_dirs


def test_discover_files_does_not_follow_symlinked_directories(tmp_path):
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)

    outside_dir = tmp_path / "outside-project"
    outside_dir.mkdir()
    (outside_dir / "secret.py").write_text("SECRET = 1\n")
    (project_root / "linked").symlink_to(outside_dir, target_is_directory=True)

    records = discover_files(project_root, config)
    paths = {record["path"] for record in records}

    assert not any(path.startswith("linked/") for path in paths)


def test_discover_files_handles_symlink_cycle_without_hanging(tmp_path):
    project_root = _copy_fixture(tmp_path)
    config = load_config(project_root)

    looping_dir = project_root / "looping"
    looping_dir.mkdir()
    (looping_dir / "self").symlink_to(looping_dir, target_is_directory=True)

    records = discover_files(project_root, config)

    assert isinstance(records, list)


def test_discover_files_labels_languages_from_the_given_registry(tmp_path):
    from project_mcp.plugins.descriptor import PluginDescriptor
    from project_mcp.plugins.registry import PluginRegistry

    (tmp_path / "main.go").write_text("package main\n")
    (tmp_path / "app.py").write_text("VALUE = 1\n")
    registry = PluginRegistry()
    registry.register(
        PluginDescriptor(
            name="go", version="0.1.0", api_version=1, extensions={".go": "go"}
        )
    )

    records = discover_files(tmp_path, load_config(tmp_path), registry=registry)

    assert {record["path"]: record["language"] for record in records} == {
        "app.py": None,
        "main.go": "go",
    }


def test_discover_files_skips_binary_files(tmp_path):
    (tmp_path / "app.py").write_text("VALUE = 1\n")
    (tmp_path / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00")

    records = discover_files(tmp_path, load_config(tmp_path))

    assert [record["path"] for record in records] == ["app.py"]


def test_discover_files_skips_files_over_max_file_bytes(tmp_path):
    (tmp_path / ".project-mcp").mkdir()
    (tmp_path / ".project-mcp" / "config.toml").write_text("max_file_bytes = 10\n")
    (tmp_path / "small.py").write_text("A = 1\n")
    (tmp_path / "large.py").write_text("VALUE = 12345\n")

    records = discover_files(tmp_path, load_config(tmp_path))

    assert [record["path"] for record in records] == ["small.py"]


def test_classify_file_takes_the_file_kind_from_the_registry():
    from project_mcp.plugins.descriptor import PluginDescriptor
    from project_mcp.plugins.registry import PluginRegistry

    registry = PluginRegistry()
    registry.register(
        PluginDescriptor(
            name="hcl",
            version="0.1.0",
            api_version=1,
            extensions={".hcl": "hcl"},
            file_kind="config",
        )
    )

    assert classify_file(Path("infra/main.hcl"), registry) == {
        "language": "hcl",
        "file_kind": "config",
    }


class _SpecSuffixAnalyzer:
    def is_test_file(self, path: Path) -> bool:
        return Path(path).stem.endswith("_spec")


def test_classify_file_asks_the_language_analyzer_whether_a_file_is_a_test():
    from project_mcp.plugins.descriptor import PluginDescriptor
    from project_mcp.plugins.registry import PluginRegistry

    registry = PluginRegistry()
    registry.register(
        PluginDescriptor(
            name="toy",
            version="0.1.0",
            api_version=1,
            extensions={".toy": "toy"},
            analyzer=f"{__name__}:_SpecSuffixAnalyzer",
        )
    )

    assert classify_file(Path("src/shape_spec.toy"), registry)["file_kind"] == "test"
    assert classify_file(Path("tests/shape.toy"), registry)["file_kind"] == "source"
