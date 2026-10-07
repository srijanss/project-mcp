import importlib
from pathlib import Path

from project_mcp.plugins.descriptor import PluginDescriptor
from project_mcp.plugins.formats import FORMAT_DESCRIPTORS

SUPPORTED_API_VERSIONS = (1,)


class PluginRegistry:
    def __init__(self) -> None:
        self._descriptor_by_extension: dict[str, PluginDescriptor] = {}
        self._descriptor_by_language: dict[str, PluginDescriptor] = {}
        self._framework_descriptors: list[PluginDescriptor] = []
        self._analyzers: dict[str, object] = {}
        self.failed_plugins: dict[str, str] = {}
        for descriptor in FORMAT_DESCRIPTORS:
            self.register(descriptor)

    def register(self, descriptor: PluginDescriptor) -> None:
        """Label files by `descriptor`; fail its analyzer if its api_version is unsupported."""
        if descriptor.api_version not in SUPPORTED_API_VERSIONS:
            supported = ", ".join(str(v) for v in SUPPORTED_API_VERSIONS)
            self.failed_plugins[descriptor.name] = (
                f"unsupported api_version {descriptor.api_version} (supported: {supported})"
            )
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
        if (
            descriptor is None
            or descriptor.analyzer is None
            or descriptor.name in self.failed_plugins
        ):
            return None
        return self._load(descriptor)

    def frameworks(self) -> list:
        """The analyzers of every registered framework plugin, loaded on first use."""
        return [
            self._load(descriptor)
            for descriptor in self._framework_descriptors
            if descriptor.analyzer is not None
            and descriptor.name not in self.failed_plugins
        ]

    def _load(self, descriptor: PluginDescriptor):
        if descriptor.name not in self._analyzers:
            module_name, _, attribute = descriptor.analyzer.partition(":")
            analyzer_class = getattr(importlib.import_module(module_name), attribute)
            self._analyzers[descriptor.name] = analyzer_class()
        return self._analyzers[descriptor.name]


def builtin_registry() -> PluginRegistry:
    """A registry holding every built-in plugin's descriptor."""
    from project_mcp.plugins.django.descriptor import DESCRIPTOR as django
    from project_mcp.plugins.javascript.descriptor import DESCRIPTOR as javascript
    from project_mcp.plugins.python.descriptor import DESCRIPTOR as python
    from project_mcp.plugins.rust.descriptor import DESCRIPTOR as rust

    registry = PluginRegistry()
    for descriptor in (python, javascript, rust, django):
        registry.register(descriptor)
    return registry
