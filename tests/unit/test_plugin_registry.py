from pathlib import Path

import pytest

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
        "astro": (None, set()),
    }


class _ToyFramework:
    pass


def test_registry_loads_registered_framework_plugins():
    from project_mcp.plugins.python.descriptor import DESCRIPTOR as python

    registry = PluginRegistry()
    registry.register(python)
    registry.register(
        PluginDescriptor(
            name="toyframe",
            version="0.1.0",
            api_version=1,
            extensions={},
            kind="framework",
            requires=("python",),
            analyzer=f"{__name__}:_ToyFramework",
        )
    )

    (framework,) = registry.frameworks()
    assert isinstance(framework, _ToyFramework)
    assert registry.frameworks() == [framework]
    assert registry.language_descriptors() == [python]


def test_builtin_registry_serves_the_django_framework_plugin():
    from project_mcp.plugins.astro.framework import AstroFramework
    from project_mcp.plugins.django.framework import DjangoFramework
    from project_mcp.plugins.react.framework import ReactFramework

    assert [type(f) for f in builtin_registry().frameworks()] == [
        DjangoFramework,
        AstroFramework,
        ReactFramework,
    ]


def test_configured_registry_disables_plugins_left_out_of_the_selection(tmp_path):
    from project_mcp.config import ProjectConfig
    from project_mcp.plugins.registry import configured_registry

    registry = configured_registry(
        ProjectConfig(
            project_root=tmp_path,
            plugins_enabled=["python", "rust", "django"],
            plugins_disabled=["rust"],
        )
    )

    assert registry.language_for(Path("lib.rs")) == "rust"
    assert registry.language_for(Path("app.ts")) == "typescript"
    assert [registry.analyzed(lang) for lang in ("python", "rust", "typescript")] == [
        True,
        False,
        False,
    ]
    assert registry.analyzer_for("rust") is None
    assert registry.disabled_plugins == {"astro", "javascript", "react", "rust"}


def test_registry_skips_frameworks_whose_required_language_plugin_is_inactive():
    registry = builtin_registry()
    registry.disable("python")

    assert [type(f).__name__ for f in registry.frameworks()] == [
        "AstroFramework",
        "ReactFramework",
    ]
    assert registry.skipped_frameworks() == {"django": ["python"]}


def _claiming_py(name: str) -> PluginDescriptor:
    return PluginDescriptor(
        name=name,
        version="0.1.0",
        api_version=1,
        extensions={".py": name},
        analyzer="project_mcp.plugins.python.analyzer:PythonAnalyzer",
    )


def test_resolving_extension_claims_rejects_two_active_claimants():
    from project_mcp.config import ConfigError

    registry = PluginRegistry()
    registry.register(_claiming_py("python"))
    registry.register(_claiming_py("snake"))

    with pytest.raises(ConfigError, match="plugins python and snake both claim .py"):
        registry.resolve_extension_claims()


def test_resolving_extension_claims_gives_the_extension_to_its_active_claimant():
    registry = PluginRegistry()
    registry.register(_claiming_py("python"))
    registry.register(_claiming_py("snake"))
    registry.disable("snake")

    registry.resolve_extension_claims()

    assert registry.language_for(Path("app.py")) == "python"


def test_a_plugin_whose_analyzer_fails_to_load_is_failed_not_raised():
    registry = PluginRegistry()
    registry.register(
        PluginDescriptor(
            name="ghost",
            version="0.1.0",
            api_version=1,
            extensions={".ghost": "ghost"},
            analyzer="project_mcp.plugins.no_such_module:Ghost",
        )
    )

    assert registry.analyzer_for("ghost") is None
    assert registry.failed_plugins["ghost"].startswith(
        "failed to load: No module named 'project_mcp.plugins.no_such_module'"
    )
    assert registry.analyzed("ghost") is False


class _EntryPoint:
    def __init__(self, name, load):
        self.name = name
        self._load = load

    def load(self):
        return self._load()


def test_builtin_registry_registers_plugins_from_the_entry_point_group(monkeypatch):
    from project_mcp.plugins import registry as registry_module

    toy = PluginDescriptor(
        name="toy",
        version="0.1.0",
        api_version=1,
        extensions={".toy": "toy"},
        analyzer="toy_plugin:ToyAnalyzer",
    )
    groups = []

    def entry_points(group):
        groups.append(group)
        return [_EntryPoint("toy", lambda: toy)]

    monkeypatch.setattr(registry_module, "entry_points", entry_points)

    registry = builtin_registry()

    assert groups == ["project_mcp.plugins"]
    assert registry.language_for(Path("main.toy")) == "toy"
    assert registry.plugin_names()[-1] == "toy"


def test_an_entry_point_that_fails_to_load_is_failed_not_raised(monkeypatch):
    from project_mcp.plugins import registry as registry_module

    def broken():
        raise ImportError("no module named toy_plugin")

    monkeypatch.setattr(
        registry_module, "entry_points", lambda group: [_EntryPoint("toy", broken)]
    )

    registry = builtin_registry()

    assert registry.failed_plugins == {"toy": "failed to load: no module named toy_plugin"}
    assert registry.analyzed("python")


def test_a_language_fingerprint_names_its_active_plugin_and_version():
    registry = PluginRegistry()
    registry.register(
        PluginDescriptor(
            name="toy",
            version="0.2.0",
            api_version=1,
            extensions={".toy": "toy"},
            analyzer="project_mcp.plugins.python.analyzer:PythonAnalyzer",
        )
    )

    fingerprint = registry.fingerprint("toy")
    registry.disable("toy")

    assert fingerprint.startswith("toy@0.2.0")
    assert registry.fingerprint("toy") is None
    assert registry.fingerprint(None) is None


def test_a_language_fingerprint_changes_with_its_plugins_config(tmp_path):
    from project_mcp.config import load_config
    from project_mcp.plugins.registry import configured_registry

    def python_fingerprint(settings):
        (tmp_path / "mcpctl.toml").write_text(f"[plugins.python]\n{settings}\n")
        return configured_registry(load_config(tmp_path)).fingerprint("python")

    assert python_fingerprint("strict = true") == python_fingerprint("strict = true")
    assert python_fingerprint("strict = true") != python_fingerprint("strict = false")


def test_active_plugins_leave_out_disabled_failed_and_skipped_plugins():
    registry = builtin_registry()
    registry.disable("rust")
    registry.failed_plugins["javascript"] = "failed to load: boom"
    without_python = builtin_registry()
    without_python.disable("python")

    assert registry.active_plugins() == ["python", "django"]
    assert without_python.active_plugins() == ["javascript", "rust", "astro", "react"]


TOY_DESCRIPTOR = PluginDescriptor(
    name="toy",
    version="0.1.0",
    api_version=1,
    extensions={".toy": "toy"},
    analyzer="toy_plugin:ToyAnalyzer",
)


def test_builtin_registry_loads_the_built_in_plugins_named_as_module_attribute(monkeypatch):
    from project_mcp.plugins import registry as registry_module

    monkeypatch.setattr(
        registry_module, "BUILTIN_PLUGINS", (f"{__name__}:TOY_DESCRIPTOR",)
    )
    monkeypatch.setattr(registry_module, "entry_points", lambda group: [])

    registry = builtin_registry()

    assert registry.plugin_names() == ["toy"]


def test_configured_registry_rejects_an_unknown_plugin_in_enabled(tmp_path):
    from project_mcp.config import ConfigError, ProjectConfig
    from project_mcp.plugins.registry import configured_registry

    config = ProjectConfig(project_root=tmp_path, plugins_enabled=["python", "pyhton"])

    with pytest.raises(
        ConfigError,
        match=r"unknown plugin pyhton in mcpctl.toml plugins.enabled"
        r" \(installed: python, javascript, rust, django, astro, react\)",
    ):
        configured_registry(config)


def test_an_entry_point_reusing_a_registered_plugin_name_is_failed_not_registered(
    monkeypatch,
):
    from project_mcp.plugins import registry as registry_module

    impostor = PluginDescriptor(
        name="python",
        version="9.9.9",
        api_version=1,
        extensions={".py": "python"},
        analyzer="acme_python.analyzer:AcmeAnalyzer",
    )
    entry_point = _EntryPoint("python", lambda: impostor)
    entry_point.value = "acme_python.descriptor:DESCRIPTOR"
    monkeypatch.setattr(registry_module, "entry_points", lambda group: [entry_point])

    registry = builtin_registry()
    registry.resolve_extension_claims()

    assert registry.failed_plugins == {
        "acme_python.descriptor:DESCRIPTOR": (
            "not registered: plugin name python is already registered"
        )
    }
    assert registry.plugin_names().count("python") == 1
    assert registry.fingerprint("python").startswith("python@0.")


def test_migration_kinds_gather_every_registered_plugins_declared_kinds():
    registry = PluginRegistry()
    registry.register(
        PluginDescriptor(
            name="orm",
            version="0.1.0",
            api_version=1,
            extensions={},
            kind="framework",
            analyzer="orm:Framework",
            migration_kinds=("orm_migration",),
        )
    )
    registry.register(_descriptor("go", {".go": "go"}))

    assert registry.migration_kinds() == {"orm_migration"}


def test_a_descriptor_with_malformed_migration_kinds_is_failed_and_contributes_nothing():
    registry = PluginRegistry()
    registry.register(
        PluginDescriptor(
            name="orm",
            version="0.1.0",
            api_version=1,
            extensions={},
            kind="framework",
            analyzer="orm:Framework",
            migration_kinds=None,
        )
    )

    assert registry.failed_plugins["orm"].startswith("invalid descriptor: migration_kinds")
    assert registry.plugin_names() == []
    assert registry.migration_kinds() == set()


@pytest.mark.parametrize("field", ["manifests", "requires", "migration_kinds"])
@pytest.mark.parametrize("value", [None, "orm_migration", (None,), ("ok", 1)])
def test_a_descriptor_whose_string_tuple_field_is_malformed_is_failed(field, value):
    registry = PluginRegistry()
    registry.register(
        PluginDescriptor(
            name="orm",
            version="0.1.0",
            api_version=1,
            extensions={},
            kind="framework",
            analyzer="orm:Framework",
            **{field: value},
        )
    )

    assert registry.failed_plugins["orm"].startswith(f"invalid descriptor: {field}")
    assert registry.plugin_names() == []


@pytest.mark.parametrize("extensions", [None, {".orm": None}, {1: "orm"}])
def test_a_descriptor_whose_extensions_are_not_a_string_mapping_is_failed(extensions):
    registry = PluginRegistry()
    registry.register(_descriptor("orm", extensions))

    assert registry.failed_plugins["orm"].startswith("invalid descriptor: extensions")
    assert registry.language_for(Path("models.orm")) is None


class _FallbackAnalyzer:
    warnings = ["falls back to its regex parser: tree_sitter is not installed"]


class _PlainAnalyzer:
    pass


def test_plugin_warnings_gather_each_active_analyzers_warnings():
    registry = PluginRegistry()
    for name, analyzer in (("toy", "_FallbackAnalyzer"), ("plain", "_PlainAnalyzer")):
        registry.register(
            PluginDescriptor(
                name=name,
                version="0.1.0",
                api_version=1,
                extensions={f".{name}": name},
                analyzer=f"{__name__}:{analyzer}",
            )
        )
    registry.resolve_extension_claims()

    assert registry.plugin_warnings() == {
        "toy": ["falls back to its regex parser: tree_sitter is not installed"]
    }


class _TreeSitterBackend:
    backend = "tree-sitter"


class _RegexBackend:
    backend = "regex"


def test_an_analyzers_backend_feeds_its_plugins_fingerprint():
    def fingerprint(analyzer):
        registry = PluginRegistry()
        registry.register(
            PluginDescriptor(
                name="toy",
                version="0.1.0",
                api_version=1,
                extensions={".toy": "toy"},
                analyzer=f"{__name__}:{analyzer}",
            )
        )
        registry.resolve_extension_claims()
        return registry.fingerprint("toy")

    tree_sitter, regex, plain = (
        fingerprint(a) for a in ("_TreeSitterBackend", "_RegexBackend", "_PlainAnalyzer")
    )

    assert tree_sitter != regex
    assert plain not in (tree_sitter, regex)


def test_a_languages_fingerprint_changes_when_a_framework_requiring_it_is_disabled():
    def fingerprint(disabled=()):
        registry = PluginRegistry()
        registry.register(
            PluginDescriptor(
                name="toy",
                version="0.1.0",
                api_version=1,
                extensions={".toy": "toy"},
                analyzer=f"{__name__}:_PlainAnalyzer",
            )
        )
        registry.register(
            PluginDescriptor(
                name="toyfw",
                version="0.1.0",
                api_version=1,
                extensions={},
                kind="framework",
                requires=("toy",),
                analyzer=f"{__name__}:_PlainAnalyzer",
            )
        )
        for name in disabled:
            registry.disable(name)
        registry.resolve_extension_claims()
        return registry.fingerprint("toy")

    assert fingerprint(disabled=("toyfw",)) != fingerprint()
    assert fingerprint() == fingerprint()
