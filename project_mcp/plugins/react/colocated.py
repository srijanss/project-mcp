"""The source file a colocated test file is named after."""
from pathlib import PurePosixPath

_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx")
_TEST_SUFFIXES = (".test", ".spec")
_TESTS_DIR = "__tests__"


def colocated_source(test_path: str, paths) -> str | None:
    """The indexed source `test_path` tests by naming convention, if any.

    `Name.test.tsx` or `Name.spec.tsx` tests `Name.*` in its own directory;
    a file in a `__tests__` directory, with or without that suffix, tests
    `Name.*` in the directory above.
    """
    path = PurePosixPath(test_path)
    stem = path.stem
    suffixed = stem.endswith(_TEST_SUFFIXES)
    if suffixed:
        stem = stem.rpartition(".")[0]
    if path.parent.name == _TESTS_DIR:
        directory = path.parent.parent
    elif suffixed:
        directory = path.parent
    else:
        return None
    return next(
        (str(c) for c in (directory / f"{stem}{ext}" for ext in _EXTENSIONS) if str(c) in paths),
        None,
    )
