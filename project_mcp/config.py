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


_LEGACY_THRESHOLD_KEYS = (
    "large_file_lines",
    "large_symbol_lines",
    "high_churn_count",
    "high_fan_in_count",
    "high_fan_out_count",
    "high_temporal_coupling_count",
)


def _validate_legacy_thresholds(raw: dict) -> None:
    for key in _LEGACY_THRESHOLD_KEYS:
        if key not in raw:
            continue
        value = raw[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ConfigError(
                f"invalid config: {key} must be a non-negative integer, got {value!r}"
            )


@dataclass
class ProjectConfig:
    project_root: Path
    exclude: list[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDE))
    source_roots: list[str] = field(default_factory=list)
    test_roots: list[str] = field(default_factory=list)
    architecture_docs: list[str] = field(default_factory=list)
    legacy_paths: list[str] = field(default_factory=list)
    git_history_limit: int = 100
    large_file_lines: int = 500
    large_symbol_lines: int = 100
    high_churn_count: int = 20
    high_fan_in_count: int = 15
    high_fan_out_count: int = 15
    high_temporal_coupling_count: int = 5
    max_file_bytes: int = 1024 * 1024
    plugins_enabled: list[str] | None = None
    plugins_disabled: list[str] = field(default_factory=list)
    plugin_settings: dict[str, dict] = field(default_factory=dict)


def _plugin_selection(project_root: Path) -> dict:
    """`[plugins] enabled / disabled` and each plugin's `[plugins.<name>]`
    settings table from the project's mcpctl.toml.

    No `enabled` list means every installed plugin is enabled.
    """
    mcpctl_path = project_root / "mcpctl.toml"
    if not mcpctl_path.exists():
        return {}
    try:
        plugins = tomllib.loads(mcpctl_path.read_text()).get("plugins", {})
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid config toml at {mcpctl_path}: {exc}") from exc
    selection = {}
    for key in ("enabled", "disabled"):
        if key not in plugins:
            continue
        names = plugins[key]
        if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
            raise ConfigError(
                f"invalid config: plugins.{key} must be a list of plugin names, got {names!r}"
            )
        selection[f"plugins_{key}"] = names
    settings = {name: table for name, table in plugins.items() if isinstance(table, dict)}
    if settings:
        selection["plugin_settings"] = settings
    return selection


def load_config(project_root: Path) -> ProjectConfig:
    project_root = Path(project_root)
    if not project_root.exists():
        raise ConfigError(f"project root does not exist: {project_root}")

    (project_root / ".project-mcp").mkdir(exist_ok=True)

    plugins = _plugin_selection(project_root)
    config_toml_path = project_root / ".project-mcp" / "config.toml"
    if not config_toml_path.exists():
        return ProjectConfig(project_root=project_root, **plugins)

    try:
        raw = tomllib.loads(config_toml_path.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid config toml at {config_toml_path}: {exc}") from exc

    _validate_legacy_thresholds(raw)

    return ProjectConfig(
        project_root=project_root,
        exclude=raw.get("exclude", list(DEFAULT_EXCLUDE)),
        source_roots=raw.get("source_roots", []),
        test_roots=raw.get("test_roots", []),
        architecture_docs=raw.get("architecture_docs", []),
        legacy_paths=raw.get("legacy_paths", []),
        git_history_limit=raw.get("git_history_limit", 100),
        large_file_lines=raw.get("large_file_lines", 500),
        large_symbol_lines=raw.get("large_symbol_lines", 100),
        high_churn_count=raw.get("high_churn_count", 20),
        high_fan_in_count=raw.get("high_fan_in_count", 15),
        high_fan_out_count=raw.get("high_fan_out_count", 15),
        high_temporal_coupling_count=raw.get("high_temporal_coupling_count", 5),
        max_file_bytes=raw.get("max_file_bytes", 1024 * 1024),
        **plugins,
    )
