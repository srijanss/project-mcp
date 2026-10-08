"""Which files of a react project are statically recognisable pages."""
from pathlib import PurePosixPath

_EXTENSIONS = (".js", ".jsx", ".ts", ".tsx")


def is_page_path(path: str) -> bool:
    """True for a source file under a `pages/` directory or an `app/**/page.*` file."""
    file = PurePosixPath(path)
    if file.suffix not in _EXTENSIONS:
        return False
    directories = file.parts[:-1]
    return "pages" in directories or ("app" in directories and file.stem == "page")
