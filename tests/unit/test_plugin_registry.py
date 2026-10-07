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
