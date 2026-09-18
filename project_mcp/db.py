import sqlite3
from pathlib import Path


def get_connection(project_root: Path) -> sqlite3.Connection:
    project_root = Path(project_root)
    db_path = project_root / ".project-mcp" / "index.db"
    return sqlite3.connect(db_path)
