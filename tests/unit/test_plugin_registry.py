from pathlib import Path

from project_mcp.plugins.descriptor import PluginDescriptor
from project_mcp.plugins.registry import PluginRegistry, builtin_registry


def _descriptor(name: str, extensions: dict[str, str]) -> PluginDescriptor:
    return PluginDescriptor(
        name=name, version="0.1.0", api_version=1, extensions=extensions
    )


def test_registry_labels_a_path_by_the_descriptor_claiming_its_extension():
    registry = PluginRegistry()
    registry.register(_descriptor("go", {".go": "go"}))

    assert registry.language_for(Path("cmd/main.go")) == "go"
    assert registry.language_for(Path("notes.txt")) is None


def test_builtin_registry_labels_python_javascript_typescript_and_rust():
    registry = builtin_registry()

    assert {
        ext: registry.language_for(Path(f"src/file{ext}"))
        for ext in (".py", ".js", ".jsx", ".ts", ".tsx", ".rs")
    } == {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".rs": "rust",
    }


def test_registry_gives_the_file_kind_a_descriptor_declares():
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
    registry.register(_descriptor("go", {".go": "go"}))

    assert registry.file_kind_for(Path("main.hcl")) == "config"
    assert registry.file_kind_for(Path("main.go")) == "source"
    assert registry.file_kind_for(Path("notes.xyz")) == "source"


def test_every_registry_labels_config_and_docs_formats():
    registry = PluginRegistry()

    assert {
        name: (registry.language_for(Path(name)), registry.file_kind_for(Path(name)))
        for name in (
            "pyproject.toml",
            "setup.cfg",
            "tox.ini",
            "ci.yaml",
            "ci.yml",
            "package.json",
            "README.md",
            "index.rst",
        )
    } == {
        "pyproject.toml": ("toml", "config"),
        "setup.cfg": ("ini", "config"),
        "tox.ini": ("ini", "config"),
        "ci.yaml": ("yaml", "config"),
        "ci.yml": ("yaml", "config"),
        "package.json": ("json", "config"),
        "README.md": ("markdown", "docs"),
        "index.rst": ("restructuredtext", "docs"),
    }


class _RecordingAnalyzer:
    loaded = 0

    def __init__(self):
        type(self).loaded += 1


def test_registry_loads_a_language_analyzer_from_its_descriptor_once():
    registry = PluginRegistry()
    registry.register(
        PluginDescriptor(
            name="toy",
            version="0.1.0",
            api_version=1,
            extensions={".toy": "toy"},
            analyzer=f"{__name__}:_RecordingAnalyzer",
        )
    )
    _RecordingAnalyzer.loaded = 0

    first = registry.analyzer_for("toy")
    second = registry.analyzer_for("toy")

    assert isinstance(first, _RecordingAnalyzer)
    assert first is second
    assert _RecordingAnalyzer.loaded == 1
    assert registry.analyzer_for("toml") is None
    assert registry.analyzer_for(None) is None


def test_registry_fails_a_plugin_with_an_unsupported_api_version():
    registry = PluginRegistry()
    registry.register(
        PluginDescriptor(
            name="toy",
            version="0.1.0",
            api_version=2,
            extensions={".toy": "toy"},
            analyzer=f"{__name__}:_RecordingAnalyzer",
        )
    )
    _RecordingAnalyzer.loaded = 0

    assert registry.language_for(Path("a.toy")) == "toy"
    assert registry.analyzer_for("toy") is None
    assert _RecordingAnalyzer.loaded == 0
    assert registry.failed_plugins == {
        "toy": "unsupported api_version 2 (supported: 1)"
    }


def test_builtin_language_plugins_declare_their_manifests_and_ecosystem():
    declared = {
        descriptor.name: (descriptor.ecosystem, set(descriptor.manifests))
        for descriptor in builtin_registry().language_descriptors()
    }

    assert declared == {
        "python": (
            "python",
            {"pyproject.toml", "setup.cfg", "setup.py", "requirements.txt"},
        ),
        "javascript": ("npm", {"package.json"}),
        "rust": ("rust", {"Cargo.toml"}),
    }
