from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class PluginDescriptor:
    """Static facts about a plugin, loaded even when the plugin is disabled.

    Holds data only, no analysis code. `extensions` maps each file extension
    the plugin claims to the language label those files get; `file_kind` is
    the kind those files are indexed as. `analyzer` names the analyzer class
    as "module:attribute", imported only when the plugin is used.
    """

    name: str
    version: str
    api_version: int
    extensions: Mapping[str, str]
    file_kind: str = "source"
    analyzer: str | None = None
