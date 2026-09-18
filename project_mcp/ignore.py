from pathlib import Path

from project_mcp.config import ProjectConfig

SECRET_PATTERNS = [
    ".env",
    "*.pem",
    "*.key",
]


def should_exclude(relative_path: Path, config: ProjectConfig) -> bool:
    relative_path = Path(relative_path)
    parts = relative_path.parts

    for excluded in config.exclude:
        if excluded in parts:
            return True

    for pattern in SECRET_PATTERNS:
        if relative_path.match(pattern):
            return True

    return False
