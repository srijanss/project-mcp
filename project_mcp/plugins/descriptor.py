from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class PluginDescriptor:
    """Static facts about a plugin, loaded even when the plugin is disabled.

    Holds data only, no analysis code. `extensions` maps each file extension
    the plugin claims to the language label those files get; `file_kind` is
    the kind those files are indexed as. `analyzer` names the analyzer class
    as "module:attribute", imported only when the plugin is used.
    `manifests` are the file names that declare a project's dependencies in
    the plugin's `ecosystem` (e.g. "pyproject.toml" for "python").
    A `kind="framework"` plugin claims no files; its analyzer enriches the
    files of the language plugins named in `requires`.
    `migration_kinds` are the `framework_kind` values the plugin gives
    generated migration history, which find_symbol leaves out by default.
    """

    name: str
    version: str
    api_version: int
    extensions: Mapping[str, str]
    file_kind: str = "source"
    analyzer: str | None = None
    manifests: tuple[str, ...] = ()
    ecosystem: str | None = None
    kind: str = "language"
    requires: tuple[str, ...] = ()
    migration_kinds: tuple[str, ...] = ()


def descriptor_problem(descriptor: PluginDescriptor) -> str | None:
    """Why `descriptor` is malformed, or None.

    Checks the collection fields core iterates (extensions, manifests,
    requires, migration_kinds), whose wrong types would otherwise crash
    every scan or query rather than fail only this plugin.
    """
    extensions = descriptor.extensions
    if not isinstance(extensions, Mapping) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in extensions.items()
    ):
        return f"extensions must map extensions to language names, got {extensions!r}"
    for field in ("manifests", "requires", "migration_kinds"):
        value = getattr(descriptor, field)
        if not isinstance(value, (tuple, list)) or not all(isinstance(v, str) for v in value):
            return f"{field} must be a tuple of strings, got {value!r}"
    return None
