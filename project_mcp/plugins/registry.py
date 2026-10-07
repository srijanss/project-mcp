from pathlib import Path

from project_mcp.plugins.descriptor import PluginDescriptor


class PluginRegistry:
    def __init__(self) -> None:
        self._language_by_extension: dict[str, str] = {}

    def register(self, descriptor: PluginDescriptor) -> None:
        self._language_by_extension.update(descriptor.extensions)

    def language_for(self, path: Path) -> str | None:
        return self._language_by_extension.get(Path(path).suffix)


def builtin_registry() -> PluginRegistry:
    """A registry holding every built-in plugin's descriptor."""
    from project_mcp.plugins.javascript.descriptor import DESCRIPTOR as javascript
    from project_mcp.plugins.python.descriptor import DESCRIPTOR as python
    from project_mcp.plugins.rust.descriptor import DESCRIPTOR as rust

    registry = PluginRegistry()
    for descriptor in (python, javascript, rust):
        registry.register(descriptor)
    return registry
