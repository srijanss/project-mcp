import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_EXCLUDE = [
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "target",
    "dist",
    "build",
]


class ConfigError(Exception):
    pass


@dataclass
class ProjectConfig:
    project_root: Path
    exclude: list[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDE))
    source_roots: list[str] = field(default_factory=list)
    test_roots: list[str] = field(default_factory=list)
    architecture_docs: list[str] = field(default_factory=list)
    legacy_paths: list[str] = field(default_factory=list)


def load_config(project_root: Path) -> ProjectConfig:
    project_root = Path(project_root)
    if not project_root.exists():
        raise ConfigError(f"project root does not exist: {project_root}")

    (project_root / ".project-mcp").mkdir(exist_ok=True)

    config_toml_path = project_root / ".project-mcp" / "config.toml"
    if not config_toml_path.exists():
        return ProjectConfig(project_root=project_root)

    try:
        raw = tomllib.loads(config_toml_path.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid config toml at {config_toml_path}: {exc}") from exc
    return ProjectConfig(
        project_root=project_root,
        exclude=raw.get("exclude", list(DEFAULT_EXCLUDE)),
        source_roots=raw.get("source_roots", []),
        test_roots=raw.get("test_roots", []),
        architecture_docs=raw.get("architecture_docs", []),
        legacy_paths=raw.get("legacy_paths", []),
    )
