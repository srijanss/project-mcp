from pathlib import Path

from project_mcp.plugins.descriptor import PluginDescriptor
from project_mcp.plugins.formats import FORMAT_DESCRIPTORS


class PluginRegistry:
    def __init__(self) -> None:
        self._descriptor_by_extension: dict[str, PluginDescriptor] = {}
        for descriptor in FORMAT_DESCRIPTORS:
            self.register(descriptor)

    def register(self, descriptor: PluginDescriptor) -> None:
        for extension in descriptor.extensions:
            self._descriptor_by_extension[extension] = descriptor

    def language_for(self, path: Path) -> str | None:
        suffix = Path(path).suffix
        descriptor = self._descriptor_by_extension.get(suffix)
        return None if descriptor is None else descriptor.extensions[suffix]

    def file_kind_for(self, path: Path) -> str:
        descriptor = self._descriptor_by_extension.get(Path(path).suffix)
        return "source" if descriptor is None else descriptor.file_kind


def builtin_registry() -> PluginRegistry:
    """A registry holding every built-in plugin's descriptor."""
    from project_mcp.plugins.javascript.descriptor import DESCRIPTOR as javascript
    from project_mcp.plugins.python.descriptor import DESCRIPTOR as python
    from project_mcp.plugins.rust.descriptor import DESCRIPTOR as rust

    registry = PluginRegistry()
    for descriptor in (python, javascript, rust):
        registry.register(descriptor)
    return registry
