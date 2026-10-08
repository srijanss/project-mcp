import hashlib
import importlib
import json
from importlib.metadata import entry_points
from pathlib import Path

from project_mcp.config import ConfigError
from project_mcp.plugins.descriptor import PluginDescriptor, descriptor_problem
from project_mcp.plugins.formats import FORMAT_DESCRIPTORS

SUPPORTED_API_VERSIONS = (1,)
ENTRY_POINT_GROUP = "project_mcp.plugins"
# The plugins shipped with project-mcp, as "module:attribute" of each descriptor,
# loaded by name so that core never imports a plugin module.
BUILTIN_PLUGINS = (
    "project_mcp.plugins.python.descriptor:DESCRIPTOR",
    "project_mcp.plugins.javascript.descriptor:DESCRIPTOR",
    "project_mcp.plugins.rust.descriptor:DESCRIPTOR",
    "project_mcp.plugins.django.descriptor:DESCRIPTOR",
)


class PluginRegistry:
    def __init__(self) -> None:
        self._descriptor_by_extension: dict[str, PluginDescriptor] = {}
        self._descriptor_by_language: dict[str, PluginDescriptor] = {}
        self._framework_descriptors: list[PluginDescriptor] = []
        self._analyzers: dict[str, object] = {}
        self._descriptor_by_name: dict[str, PluginDescriptor] = {}
        self._claimants: dict[str, list[PluginDescriptor]] = {}
        self.failed_plugins: dict[str, str] = {}
        self.disabled_plugins: set[str] = set()
        self.plugin_settings: dict[str, dict] = {}
        for descriptor in FORMAT_DESCRIPTORS:
            self.register(descriptor)

    def register(self, descriptor: PluginDescriptor) -> None:
        """Label files by `descriptor`; fail its analyzer if its api_version is unsupported.

        A malformed descriptor is failed and registers nothing.
        """
        problem = descriptor_problem(descriptor)
        if problem is not None:
            self.failed_plugins[descriptor.name] = f"invalid descriptor: {problem}"
            return
        if descriptor.api_version not in SUPPORTED_API_VERSIONS:
            supported = ", ".join(str(v) for v in SUPPORTED_API_VERSIONS)
            self.failed_plugins[descriptor.name] = (
                f"unsupported api_version {descriptor.api_version} (supported: {supported})"
            )
        if descriptor.analyzer is not None:
            self._descriptor_by_name[descriptor.name] = descriptor
            for extension in descriptor.extensions:
                self._claimants.setdefault(extension, []).append(descriptor)
        if descriptor.kind == "framework":
            self._framework_descriptors.append(descriptor)
        for extension, language in descriptor.extensions.items():
            self._descriptor_by_extension[extension] = descriptor
            self._descriptor_by_language[language] = descriptor

    def language_descriptors(self) -> list[PluginDescriptor]:
        """Every registered plugin that analyzes source files, in registration order."""
        unique = {id(d): d for d in self._descriptor_by_language.values()}.values()
        return [descriptor for descriptor in unique if descriptor.analyzer is not None]

    def language_for(self, path: Path) -> str | None:
        suffix = Path(path).suffix
        descriptor = self._descriptor_by_extension.get(suffix)
        return None if descriptor is None else descriptor.extensions[suffix]

    def file_kind_for(self, path: Path) -> str:
        descriptor = self._descriptor_by_extension.get(Path(path).suffix)
        return "source" if descriptor is None else descriptor.file_kind

    def analyzer_for(self, language: str | None):
        """The analyzer of the plugin owning `language`, loaded on first use."""
        descriptor = self._descriptor_by_language.get(language)
        if descriptor is None or not self._active(descriptor):
            return None
        return self._load(descriptor)

    def fingerprint(self, language: str | None) -> str | None:
        """`name@version#confighash` of the active plugin analyzing `language`,
        else None.

        A file indexed under a different fingerprint needs re-indexing. The
        hash covers the plugin's settings and, when its analyzer names one,
        the parser `backend` it runs on.
        """
        descriptor = self._descriptor_by_language.get(language)
        if descriptor is None or not self._active(descriptor):
            return None
        hashed = dict(self.plugin_settings.get(descriptor.name, {}))
        backend = getattr(self._load(descriptor), "backend", None)
        if backend is not None:
            hashed["backend"] = backend
        settings = json.dumps(hashed, sort_keys=True, default=str)
        config_hash = hashlib.sha256(settings.encode()).hexdigest()[:12]
        return f"{descriptor.name}@{descriptor.version}#{config_hash}"

    def analyzed(self, language: str | None) -> bool:
        """Whether an enabled, loadable plugin analyzes `language` files."""
        return self.analyzer_for(language) is not None

    def resolve_extension_claims(self) -> None:
        """Give each extension to the one active plugin claiming it.

        Two active plugins claiming one extension is a config error.
        """
        for extension, claimants in self._claimants.items():
            active = [d for d in claimants if self._active(d)]
            if len(active) > 1:
                names = " and ".join(sorted(d.name for d in active))
                raise ConfigError(
                    f"plugins {names} {'both' if len(active) == 2 else 'all'} claim"
                    f" {extension}; disable all but one in mcpctl.toml [plugins]"
                )
            if active:
                (owner,) = active
                self._descriptor_by_extension[extension] = owner
                self._descriptor_by_language[owner.extensions[extension]] = owner

    def disable(self, name: str) -> None:
        """Keep plugin `name` labelling its files, but never load its analyzer."""
        self.disabled_plugins.add(name)

    def plugin_names(self) -> list[str]:
        """Every registered plugin with an analyzer, in registration order."""
        return list(self._descriptor_by_name)

    def active_plugins(self) -> list[str]:
        """Plugins that run on a scan, in registration order.

        Disabled and failed plugins are left out, as are frameworks whose
        language plugin is inactive.
        """
        return [
            name
            for name, descriptor in self._descriptor_by_name.items()
            if self._active(descriptor) and not self._inactive_requirements(descriptor)
        ]

    def plugin_warnings(self) -> dict[str, list[str]]:
        """The `warnings` each active plugin's analyzer reports, such as a
        parser it fell back to."""
        warnings = {}
        for name in self.active_plugins():
            analyzer = self._load(self._descriptor_by_name[name])
            if getattr(analyzer, "warnings", None):
                warnings[name] = list(analyzer.warnings)
        return warnings

    def _active(self, descriptor: PluginDescriptor) -> bool:
        return (
            descriptor.analyzer is not None
            and descriptor.name not in self.failed_plugins
            and descriptor.name not in self.disabled_plugins
        )

    def frameworks(self) -> list:
        """The analyzers of every registered framework plugin, loaded on first use."""
        loaded = [
            self._load(descriptor)
            for descriptor in self._framework_descriptors
            if self._active(descriptor) and not self._inactive_requirements(descriptor)
        ]
        return [framework for framework in loaded if framework is not None]

    def migration_kinds(self) -> set[str]:
        """The `framework_kind`s every registered plugin marks as migrations."""
        return {
            kind
            for descriptor in self._descriptor_by_name.values()
            for kind in descriptor.migration_kinds
        }

    def skipped_frameworks(self) -> dict[str, list[str]]:
        """Enabled framework plugins skipped, with the inactive plugins they require."""
        return {
            descriptor.name: missing
            for descriptor in self._framework_descriptors
            if self._active(descriptor)
            and (missing := self._inactive_requirements(descriptor))
        }

    def _inactive_requirements(self, descriptor: PluginDescriptor) -> list[str]:
        return [
            name
            for name in descriptor.requires
            if name not in self._descriptor_by_name
            or not self._active(self._descriptor_by_name[name])
        ]

    def _load(self, descriptor: PluginDescriptor):
        """The plugin's analyzer; a plugin whose analyzer cannot load is failed."""
        if descriptor.name not in self._analyzers:
            try:
                self._analyzers[descriptor.name] = _import_object(descriptor.analyzer)()
            except Exception as exc:
                self.failed_plugins[descriptor.name] = f"failed to load: {exc}"
                return None
        return self._analyzers[descriptor.name]


def _import_object(spec: str):
    """The object a "module:attribute" spec names."""
    module_name, _, attribute = spec.partition(":")
    return getattr(importlib.import_module(module_name), attribute)


def builtin_registry() -> PluginRegistry:
    """A registry holding every built-in and installed plugin's descriptor.

    Installed plugins publish their descriptor in the `project_mcp.plugins`
    entry-point group; one reusing a registered plugin's name is failed.
    """
    registry = PluginRegistry()
    for spec in BUILTIN_PLUGINS:
        registry.register(_import_object(spec))
    for entry_point in entry_points(group=ENTRY_POINT_GROUP):
        try:
            descriptor = entry_point.load()
        except Exception as exc:
            registry.failed_plugins[entry_point.name] = f"failed to load: {exc}"
            continue
        if descriptor.name in registry.plugin_names():
            # Keyed by the entry point, so the plugin already holding the name stays active.
            registry.failed_plugins[entry_point.value] = (
                f"not registered: plugin name {descriptor.name} is already registered"
            )
            continue
        registry.register(descriptor)
    return registry


def configured_registry(config) -> PluginRegistry:
    """The built-in plugins, with those the project's config leaves out disabled.

    Without `plugins_enabled` every plugin is enabled; naming a plugin there
    that isn't installed is a config error. `plugins_disabled` then disables
    plugins by name. Each plugin's `[plugins.<name>]` settings
    feed its fingerprint.
    """
    registry = builtin_registry()
    registry.plugin_settings = dict(config.plugin_settings)
    known = set(registry.plugin_names()) | set(registry.failed_plugins)
    for name in config.plugins_enabled or []:
        if name not in known:
            raise ConfigError(
                f"unknown plugin {name} in mcpctl.toml plugins.enabled"
                f" (installed: {', '.join(registry.plugin_names())})"
            )
    for name in registry.plugin_names():
        left_out = config.plugins_enabled is not None and name not in config.plugins_enabled
        if left_out or name in config.plugins_disabled:
            registry.disable(name)
    registry.resolve_extension_claims()
    return registry
