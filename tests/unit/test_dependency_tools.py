from pathlib import Path

import pytest

from project_mcp.tools.dependencies import get_dependency_version, list_dependencies


def test_list_dependencies_reads_declared_python_dependencies(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        """[project]
dependencies = ["requests>=2.31", "rich==13.7.1"]
"""
    )

    assert list_dependencies(tmp_path, ecosystem="python") == [
        {
            "name": "requests",
            "ecosystem": "python",
            "version": ">=2.31",
            "version_status": "declared",
        },
        {
            "name": "rich",
            "ecosystem": "python",
            "version": "13.7.1",
            "version_status": "declared",
        },
    ]


def test_list_dependencies_reads_declared_cargo_dependencies(tmp_path: Path):
    (tmp_path / "Cargo.toml").write_text(
        """[package]
name = "widget"
version = "0.1.0"

[dependencies]
serde = "1.0"
tokio = { version = "1", features = ["full"] }
"""
    )

    assert list_dependencies(tmp_path, ecosystem="rust") == [
        {
            "name": "serde",
            "ecosystem": "rust",
            "version": "1.0",
            "version_status": "declared",
        },
        {
            "name": "tokio",
            "ecosystem": "rust",
            "version": "1",
            "version_status": "declared",
        },
    ]


def test_list_dependencies_prefers_resolved_cargo_lock_versions(tmp_path: Path):
    (tmp_path / "Cargo.toml").write_text(
        """[package]
name = "widget"
version = "0.1.0"

[dependencies]
serde = "1.0"
"""
    )
    (tmp_path / "Cargo.lock").write_text(
        """[[package]]
name = "serde"
version = "1.0.197"
"""
    )

    assert list_dependencies(tmp_path, ecosystem="rust") == [
        {
            "name": "serde",
            "ecosystem": "rust",
            "version": "1.0.197",
            "version_status": "resolved",
        }
    ]


def test_list_dependencies_reads_a_pyproject_dependency(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["requests>=2.31"]\n'
    )

    assert list_dependencies(tmp_path) == [
        {
            "name": "requests",
            "ecosystem": "python",
            "version": ">=2.31",
            "version_status": "declared",
        }
    ]


def test_dependency_versions_prefer_uv_lockfiles_and_report_missing(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["requests>=2.0"]\n'
    )
    (tmp_path / "uv.lock").write_text(
        '[[package]]\nname = "requests"\nversion = "2.32.3"\n'
    )
    assert get_dependency_version(tmp_path, "requests") == {
        "name": "requests", "ecosystem": "python", "version": "2.32.3", "version_status": "resolved"
    }
    assert get_dependency_version(tmp_path, "missing") == {"status": "not_found"}


def test_list_dependencies_reads_requirements_files(tmp_path: Path):
    (tmp_path / "requirements-dev.txt").write_text(
        "pytest>=8.0\n# a comment\nruff==0.6.5\n"
    )

    assert list_dependencies(tmp_path, ecosystem="python") == [
        {
            "name": "pytest",
            "ecosystem": "python",
            "version": ">=8.0",
            "version_status": "declared",
        },
        {
            "name": "ruff",
            "ecosystem": "python",
            "version": "0.6.5",
            "version_status": "declared",
        }
    ]


def test_get_dependency_version_reads_uv_lock(tmp_path: Path):
    (tmp_path / "uv.lock").write_text(
        '[[package]]\nname = "requests"\nversion = "2.32.3"\n'
    )

    assert get_dependency_version(tmp_path, "requests") == {
        "name": "requests",
        "ecosystem": "python",
        "version": "2.32.3",
        "version_status": "resolved",
    }


def test_list_dependencies_skips_direct_reference_requirements(tmp_path: Path):
    (tmp_path / "requirements.txt").write_text(
        "demo @ https://example.test/demo-1.0.whl\nrequests>=2.31\n"
    )

    assert list_dependencies(tmp_path) == [
        {
            "name": "requests",
            "ecosystem": "python",
            "version": ">=2.31",
            "version_status": "declared",
        }
    ]


def test_list_dependencies_skips_direct_url_references(tmp_path: Path):
    (tmp_path / "requirements.txt").write_text(
        "demo @ https://example.test/demo-1.0.whl\n"
    )

    assert list_dependencies(tmp_path) == []


def test_dependency_matching_is_case_insensitive(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["Requests>=2"]\n'
    )
    (tmp_path / "uv.lock").write_text(
        '[[package]]\nname = "requests"\nversion = "2.32.3"\n'
    )

    assert get_dependency_version(tmp_path, "REQUESTS") == {
        "name": "Requests",
        "ecosystem": "python",
        "version": "2.32.3",
        "version_status": "resolved",
    }


def test_list_dependencies_resolves_case_insensitive_lock_names(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["Requests>=2"]\n'
    )
    (tmp_path / "uv.lock").write_text(
        '[[package]]\nname = "requests"\nversion = "2.32.3"\n'
    )

    assert list_dependencies(tmp_path)[0]["version_status"] == "resolved"


def test_get_dependency_version_ignores_lockfile_only_packages(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["requests>=2"]\n'
    )
    (tmp_path / "uv.lock").write_text(
        '[[package]]\nname = "requests"\nversion = "2.32.3"\n'
        '[[package]]\nname = "urllib3"\nversion = "2.2.3"\n'
    )

    assert get_dependency_version(tmp_path, "urllib3") == {"status": "not_found"}


def test_list_dependencies_omits_lockfile_only_packages(tmp_path: Path):
    (tmp_path / "uv.lock").write_text(
        '[[package]]\nname = "urllib3"\nversion = "2.2.3"\n'
    )

    assert list_dependencies(tmp_path) == []


def test_list_dependencies_skips_direct_references_without_spaces(tmp_path: Path):
    (tmp_path / "requirements.txt").write_text(
        "demo@https://example.test/demo-1.0.whl\nrequests>=2.31\n"
    )

    assert [dependency["name"] for dependency in list_dependencies(tmp_path)] == [
        "requests"
    ]


def test_list_dependencies_skips_a_direct_reference_without_spaces(tmp_path: Path):
    (tmp_path / "requirements.txt").write_text(
        "demo@https://example.test/demo-1.0.whl\n"
    )

    assert list_dependencies(tmp_path) == []


def test_list_dependencies_reports_an_invalid_pyproject(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project\ndependencies = [")

    with pytest.raises(ValueError, match="invalid pyproject.toml"):
        list_dependencies(tmp_path)


def test_list_dependencies_reports_an_invalid_uv_lock(tmp_path: Path):
    (tmp_path / "uv.lock").write_text("[[package\nname = 'requests'")

    with pytest.raises(ValueError, match="invalid uv.lock"):
        list_dependencies(tmp_path)


def test_unpinned_dependency_has_unknown_version_status(tmp_path: Path):
    (tmp_path / "requirements.txt").write_text("requests\n")

    assert list_dependencies(tmp_path) == [
        {
            "name": "requests",
            "ecosystem": "python",
            "version": None,
            "version_status": "unknown",
        }
    ]


def test_unpinned_pyproject_dependency_has_unknown_version_status(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["requests"]\n'
    )

    assert list_dependencies(tmp_path)[0]["version_status"] == "unknown"


def test_requirements_ignores_hashes_comments_and_markers(tmp_path: Path):
    (tmp_path / "requirements.txt").write_text(
        "requests[socks]>=2.31 ; python_version >= '3.12' --hash=sha256:abc # note\n"
    )

    assert list_dependencies(tmp_path) == [
        {
            "name": "requests",
            "ecosystem": "python",
            "version": ">=2.31",
            "version_status": "declared",
        }
    ]


def test_requirements_file_includes_another_requirements_file(tmp_path: Path):
    (tmp_path / "requirements.txt").write_text("-r constraints.in\n")
    (tmp_path / "constraints.in").write_text("pytest>=8\n")

    assert list_dependencies(tmp_path)[0]["name"] == "pytest"


def test_list_dependencies_prefers_resolved_npm_lock_versions(tmp_path: Path):
    (tmp_path / "package.json").write_text(
        """{
  "name": "widget",
  "dependencies": {
    "left-pad": "^1.3.0"
  }
}
"""
    )
    (tmp_path / "package-lock.json").write_text(
        """{
  "packages": {
    "": {"name": "widget"},
    "node_modules/left-pad": {"version": "1.3.0"}
  }
}
"""
    )

    assert list_dependencies(tmp_path, ecosystem="npm") == [
        {
            "name": "left-pad",
            "ecosystem": "npm",
            "version": "1.3.0",
            "version_status": "resolved",
        }
    ]


def test_get_dependency_version_reads_npm_lock(tmp_path: Path):
    (tmp_path / "package.json").write_text(
        """{
  "name": "widget",
  "dependencies": {
    "left-pad": "^1.3.0"
  }
}
"""
    )
    (tmp_path / "package-lock.json").write_text(
        """{
  "packages": {
    "": {"name": "widget"},
    "node_modules/left-pad": {"version": "1.3.0"}
  }
}
"""
    )

    assert get_dependency_version(tmp_path, "left-pad") == {
        "name": "left-pad",
        "ecosystem": "npm",
        "version": "1.3.0",
        "version_status": "resolved",
    }
    assert get_dependency_version(tmp_path, "missing") == {"status": "not_found"}


def test_list_dependencies_reports_an_invalid_package_json(tmp_path: Path):
    (tmp_path / "package.json").write_text("{invalid json")

    with pytest.raises(ValueError, match="invalid package.json"):
        list_dependencies(tmp_path)


def test_get_dependency_version_is_case_sensitive_for_npm(tmp_path: Path):
    (tmp_path / "package.json").write_text(
        '{"name": "widget", "dependencies": {"React": "18.2.0"}}'
    )

    assert get_dependency_version(tmp_path, "react", ecosystem="npm") == {
        "status": "not_found"
    }
    assert get_dependency_version(tmp_path, "React", ecosystem="npm") == {
        "name": "React",
        "ecosystem": "npm",
        "version": "18.2.0",
        "version_status": "declared",
    }


def test_list_dependencies_resolves_scoped_npm_package(tmp_path: Path):
    (tmp_path / "package.json").write_text(
        """{
  "name": "widget",
  "dependencies": {
    "@org/pkg": "^2.0.0"
  }
}
"""
    )
    (tmp_path / "package-lock.json").write_text(
        """{
  "packages": {
    "": {"name": "widget"},
    "node_modules/@org/pkg": {"version": "2.0.1"}
  }
}
"""
    )

    assert list_dependencies(tmp_path, ecosystem="npm") == [
        {
            "name": "@org/pkg",
            "ecosystem": "npm",
            "version": "2.0.1",
            "version_status": "resolved",
        }
    ]


def test_requirement_includes_are_not_followed_twice(tmp_path: Path):
    (tmp_path / "requirements.txt").write_text("-r constraints.in\n")
    (tmp_path / "constraints.in").write_text("-r requirements.txt\npytest>=8\n")

    assert [dependency["name"] for dependency in list_dependencies(tmp_path)] == [
        "pytest"
    ]


def test_list_dependencies_reads_declared_npm_dependencies(tmp_path: Path):
    (tmp_path / "package.json").write_text(
        """{
  "name": "widget",
  "dependencies": {
    "left-pad": "^1.3.0",
    "react": "18.2.0"
  }
}
"""
    )

    assert list_dependencies(tmp_path, ecosystem="npm") == [
        {
            "name": "left-pad",
            "ecosystem": "npm",
            "version": "^1.3.0",
            "version_status": "declared",
        },
        {
            "name": "react",
            "ecosystem": "npm",
            "version": "18.2.0",
            "version_status": "declared",
        },
    ]


class _GearAnalyzer:
    def list_dependencies(self, project_root):
        return [{"name": "gear", "ecosystem": "toy", "version": "1.0", "version_status": "declared"}]


def test_list_dependencies_reads_each_language_plugins_ecosystem(tmp_path: Path):
    from project_mcp.plugins.descriptor import PluginDescriptor
    from project_mcp.plugins.registry import PluginRegistry

    registry = PluginRegistry()
    registry.register(
        PluginDescriptor(
            name="toy",
            version="0.1.0",
            api_version=1,
            extensions={".toy": "toy"},
            analyzer=f"{__name__}:_GearAnalyzer",
            ecosystem="toy",
        )
    )
    (tmp_path / "Cargo.toml").write_text('[dependencies]\nserde = "1"\n')
    gear = {"name": "gear", "ecosystem": "toy", "version": "1.0", "version_status": "declared"}

    assert list_dependencies(tmp_path, registry=registry) == [gear]
    assert list_dependencies(tmp_path, ecosystem="toy", registry=registry) == [gear]
    assert list_dependencies(tmp_path, ecosystem="rust", registry=registry) == []
